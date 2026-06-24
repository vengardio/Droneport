"""
Команды OrangePi → STM32.

TYPE-байты см. в константах ниже.
Подробности протокола — в спеке р. 4.8.
"""

import asyncio
import logging
import struct
from typing import Optional

from .uart_stm32_init import (
    STM32Transport,
    STM32PacketError,
    ACK_TYPE,
    NACK_TYPE,
    SYS_PART_MASK,
    CMD_TYPE_MASK,
)

log = logging.getLogger(__name__)

# TYPE-байты для запросов от OrangePi
_TYPE_REQUEST_HALL    = 0b00001001   # 0x09
_TYPE_REQUEST_VOLTAGE = 0b00010001   # 0x11
_TYPE_REQUEST_DHT22   = 0b00011001   # 0x19
_TYPE_ACTION          = 0b00000101   # 0x05  (данные: 1 байт — код команды 1..22)

# Таймауты транзакций (секунды)
# Запросы данных — быстрые
_TIMEOUT_REQUEST = 2.0
# Команды действия — могут быть очень долгими (крыша, стол)
# STM32 сначала шлёт ACK после завершения, поэтому таймаут = аппаратный таймаут + запас
_ACTION_TIMEOUTS = {
    17: 35.0,   # открыть крышу
    18: 35.0,   # закрыть крышу
    13: 25.0,   # поднять стол
    14: 25.0,   # опустить стол
    15: 12.0,   # открыть лапки
    16: 12.0,   # закрыть лапки
    9:  12.0,   # открыть заслонки
    10: 12.0,   # закрыть заслонки
    21: 3.0,    # поднять стол на порцию (50 шагов ≈ 50мс, с запасом)
    22: 45.0,   # параллельное открытие крыши + подъём стола
}
_ACTION_TIMEOUT_DEFAULT = 5.0


class STM32TX:
    """
    Отправка команд и запросов на STM32.

    Все методы — async. Бросают STM32PacketError при ошибке протокола,
    TimeoutError при таймауте ожидания ответа от STM32.
    """

    def __init__(self, transport: STM32Transport):
        self._t = transport

    # ------------------------------------------------------------------
    # Команды действия (CMD 1–21)
    # ------------------------------------------------------------------

    async def send_action(self, code: int) -> bool:
        """Отправить команду действия (code 1..22). True = ACK, False = ошибка."""
        if not 1 <= code <= 22:
            log.error("send_action: код вне диапазона 1..22: %d", code)
            return False

        timeout = _ACTION_TIMEOUTS.get(code, _ACTION_TIMEOUT_DEFAULT)
        log.debug("→ STM32 ACTION code=%d, timeout=%.1fs", code, timeout)

        try:
            resp_type, _ = await self._t.transact(
                type_byte=_TYPE_ACTION,
                data=bytes([code]),
                timeout_sec=timeout,
            )
        except STM32PacketError as e:
            log.error("send_action(%d) NACK: %s", code, e)
            return False
        except TimeoutError as e:
            log.error("send_action(%d) таймаут: %s", code, e)
            return False

        if resp_type == ACK_TYPE:
            log.debug("← STM32 ACK для action=%d", code)
            return True

        log.error("send_action(%d): неожиданный TYPE=0x%02X", code, resp_type)
        return False

    # ------------------------------------------------------------------
    # Запросы данных
    # ------------------------------------------------------------------

    async def request_hall_sensors(self) -> Optional[int]:
        """Запросить битовую маску датчиков Холла (uint8). None при ошибке."""
        log.debug("→ STM32 REQUEST_HALL")
        try:
            resp_type, data = await self._t.transact(
                type_byte=_TYPE_REQUEST_HALL,
                data=b"",
                timeout_sec=_TIMEOUT_REQUEST,
            )
        except (STM32PacketError, TimeoutError) as e:
            log.error("request_hall_sensors: %s", e)
            return None

        if len(data) < 1:
            log.error("request_hall_sensors: пустой ответ")
            return None

        hall = data[0]
        log.debug("← STM32 HALL=0b%08b", hall)
        return hall

    async def request_voltage(self) -> Optional[float]:
        """Запросить напряжение АКБ в вольтах (float). None при ошибке."""
        log.debug("→ STM32 REQUEST_VOLTAGE")
        try:
            resp_type, data = await self._t.transact(
                type_byte=_TYPE_REQUEST_VOLTAGE,
                data=b"",
                timeout_sec=_TIMEOUT_REQUEST,
            )
        except (STM32PacketError, TimeoutError) as e:
            log.error("request_voltage: %s", e)
            return None

        if len(data) < 2:
            log.error("request_voltage: короткий ответ: %d байт", len(data))
            return None

        raw = struct.unpack(">H", data[:2])[0]   # big-endian uint16
        voltage = raw / 10.0
        log.debug("← STM32 VOLTAGE raw=%d → %.2fV", raw, voltage)
        return voltage

    async def request_dht22(self) -> Optional[tuple[float, float]]:
        """Запросить DHT22: (температура_°C, влажность_%). None при ошибке."""
        log.debug("→ STM32 REQUEST_DHT22")
        try:
            resp_type, data = await self._t.transact(
                type_byte=_TYPE_REQUEST_DHT22,
                data=b"",
                timeout_sec=_TIMEOUT_REQUEST,
            )
        except (STM32PacketError, TimeoutError) as e:
            log.error("request_dht22: %s", e)
            return None

        if len(data) < 5:
            log.error("request_dht22: короткий ответ: %d байт", len(data))
            return None

        # Декодирование DHT22: humidity × 10 и temperature × 10
        hum_raw  = (data[0] << 8) | data[1]
        temp_raw = (data[2] << 8) | data[3]

        humidity    = hum_raw / 10.0
        # Бит 15 в temp_raw — знак отрицательной температуры
        if temp_raw & 0x8000:
            temperature = -((temp_raw & 0x7FFF) / 10.0)
        else:
            temperature = temp_raw / 10.0

        log.debug("← STM32 DHT22 temp=%.1f°C hum=%.1f%%", temperature, humidity)
        return temperature, humidity