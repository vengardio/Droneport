"""
Парсер входящих пакетов STM32 → OrangePi.

В MVP все ответы синхронные (через transact()),
этот модуль нужен для decode ошибок и drain мусора после ресета.
"""

import logging
from typing import Optional

from .uart_stm32_init import (
    STM32Transport,
    STM32PacketError,
    ACK_TYPE,
    NACK_TYPE,
    ERROR_TYPE_SOFTWARE,
    SOURCE_MASK,
    CMD_TYPE_MASK,
    SYS_PART_MASK,
)

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Декодирование TYPE-байта (пакеты STM32 → OrangePi)
# ──────────────────────────────────────────────

# Значения Command Type (биты 2..1)
CMD_TYPE_STATUS_RESPONSE = 0b01   # ответ на запрос статуса
CMD_TYPE_ACK_NACK        = 0b10   # не используется в TYPE напрямую (ACK/NACK — отдельные константы)
CMD_TYPE_ERROR           = 0b11   # пакет об ошибке

# Значения System Part (биты 5..3)
SYS_PART_SOFTWARE   = 0b000
SYS_PART_HALL       = 0b001
SYS_PART_VOLTAGE    = 0b010
SYS_PART_DHT22      = 0b011

# Коды ошибок — DATA[0] в Error-пакете
ERROR_CODES = {
    # Hall-ошибки (SysPart=001)
    1:  "Датчик Холла 1 (крыша открыта) не сработал",
    2:  "Датчик Холла 2 (крыша закрыта) не сработал",
    3:  "Датчик Холла 3 (стол поднят) не сработал",
    4:  "Датчик Холла 4 (стол опущен) не сработал",
    7:  "Датчик Холла 7 (лапки сжаты) не сработал",
    # Voltage-ошибки (SysPart=010)
    # (зарезервировано: 1=ниже порога, 2=выше порога)
    # DHT22-ошибки (SysPart=011)
    # (зарезервировано: 4=ошибка CRC датчика)
    # Software-ошибки (SysPart=000)
    0:  "Ошибка CRC пакета",
    # code=3 — ошибка чтения/неизвестная команда
}
ERROR_CODE_SOFTWARE_PARSE = 3   # превышена длина LEN или неверная команда


def decode_type(type_byte: int) -> dict:
    """
    Разобрать байт TYPE пакета STM32→OrangePi.

    Возвращает словарь:
        source       : int  — 0=STM32, 1=OrangePi
        cmd_type     : int  — 0b00..0b11
        sys_part     : int  — 0b000..0b111
        is_ack       : bool
        is_nack      : bool
        is_error     : bool
        is_response  : bool — ответ на запрос статуса
    """
    source   = type_byte & SOURCE_MASK
    cmd_type = (type_byte & CMD_TYPE_MASK) >> 1
    sys_part = (type_byte & SYS_PART_MASK) >> 3
    return {
        "source":      source,
        "cmd_type":    cmd_type,
        "sys_part":    sys_part,
        "is_ack":      type_byte == ACK_TYPE,
        "is_nack":     type_byte == NACK_TYPE,
        "is_error":    cmd_type == CMD_TYPE_ERROR and source == 0,
        "is_response": cmd_type == CMD_TYPE_STATUS_RESPONSE and source == 0,
    }


def decode_error_packet(type_byte: int, data: bytes) -> str:
    """
    Декодировать Error-пакет от STM32 в читаемую строку.

    type_byte: TYPE поля пакета (ожидается CommandType=11)
    data:      DATA поля (обычно 1 байт — код ошибки)
    """
    decoded = decode_type(type_byte)
    sys_part = decoded["sys_part"]
    code = data[0] if data else -1

    sys_names = {
        SYS_PART_SOFTWARE: "Software",
        SYS_PART_HALL:     "Hall",
        SYS_PART_VOLTAGE:  "Voltage",
        SYS_PART_DHT22:    "DHT22",
    }
    sys_name = sys_names.get(sys_part, f"SysPart={sys_part}")
    description = ERROR_CODES.get(code, f"Неизвестный код {code}")

    return f"[STM32 Error] sys={sys_name} code={code}: {description}"


# ──────────────────────────────────────────────
# Фасад приёмника
# ──────────────────────────────────────────────

class STM32RX:
    """
    Вспомогательный класс для работы с входящими пакетами STM32.

    В текущей архитектуре (синхронный STM32 + transact()) большинство
    ответов обрабатываются прямо в STM32TX.transact(). STM32RX используется:
        1. Для разбора уже полученных пакетов (decode_*)
        2. При необходимости принять и отбросить «мусорный» пакет
           (например незапрошенный Error после сброса STM32)
    """

    def __init__(self, transport: STM32Transport):
        self._t = transport

    async def drain_unexpected(self, timeout_sec: float = 0.3) -> list[tuple[int, bytes]]:
        """
        Вычитать все незапрошенные пакеты из порта (если есть).
        Используется для «очистки» линии перед новой транзакцией.

        Возвращает список (type_byte, data) прочитанных пакетов.
        """
        packets = []
        while True:
            try:
                tp, data = await self._t.recv_packet(timeout_sec=timeout_sec)
                decoded = decode_type(tp)
                if decoded["is_error"]:
                    msg = decode_error_packet(tp, data)
                    log.warning("Незапрошенный Error от STM32: %s", msg)
                else:
                    log.debug("Незапрошенный пакет TYPE=0x%02X: %s", tp, data.hex())
                packets.append((tp, data))
            except (TimeoutError, STM32PacketError):
                break   # линия чиста
        return packets

    @staticmethod
    def interpret_error(type_byte: int, data: bytes) -> str:
        """Вернуть читаемое описание Error-пакета."""
        return decode_error_packet(type_byte, data)

    @staticmethod
    def is_ack(type_byte: int) -> bool:
        return type_byte == ACK_TYPE

    @staticmethod
    def is_nack(type_byte: int) -> bool:
        return type_byte == NACK_TYPE