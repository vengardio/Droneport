"""
Отправка команд и запросов на STM32.

Пакет: [0xBF | TYPE | LEN | DATA | CRC | 0xFF]
Сборка пакета — здесь. Приём ответа — через stm32_rx.recv_packet().
"""

import logging
import struct
import threading
from typing import Optional

import serial

from interfaces.stm32_rx import recv_packet, STM32RxError, BYTE_START, BYTE_END

ACK_TYPE  = 0x40
NACK_TYPE = 0xC0
MAX_DATA  = 100

_TYPE_ACTION  = 0x05
_TYPE_HALL    = 0x09
_TYPE_VOLTAGE = 0x11
_TYPE_DHT22   = 0x19

_ACTION_TIMEOUTS = {
    17: 35.0,   # открыть крышу
    18: 35.0,   # закрыть крышу
    13: 25.0,   # поднять стол
    14: 25.0,   # опустить стол
    15: 12.0,   # открыть лапки
    16: 12.0,   # закрыть лапки
    9:  12.0,   # открыть заслонки
    10: 12.0,   # закрыть заслонки
    21: 3.0,    # стол на порцию
    22: 45.0,   # крыша + стол параллельно
}
_ACTION_TIMEOUT_DEFAULT = 5.0
_REQUEST_TIMEOUT        = 2.0


class STM32Error(Exception):
    pass


class STM32Interface:
    def __init__(self, port: str, baudrate: int = 115200, logger: Optional[logging.Logger] = None):
        self._port     = port
        self._baudrate = baudrate
        self.log       = logger or logging.getLogger(__name__)
        self._ser:     Optional[serial.Serial] = None
        self._lock     = threading.Lock()

    def connect(self) -> bool:
        try:
            self._ser = serial.Serial(
                port=self._port, baudrate=self._baudrate,
                bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE, timeout=0.15,
            )
            self.log.info("STM32 UART открыт: %s @ %d", self._port, self._baudrate)
            return True
        except Exception as e:
            self.log.error("STM32 UART: %s", e)
            return False

    def disconnect(self) -> None:
        if self._ser and self._ser.is_open:
            self._ser.close()
        self._ser = None

    @property
    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def drain(self) -> None:
        if self._ser and self._ser.is_open:
            n = self._ser.in_waiting
            if n:
                self._ser.read(n)

    # ─── Внутренняя транзакция ───────────────────────────────────────────────

    def _transact(self, type_byte: int, data: bytes = b"", timeout_sec: float = 2.0) -> tuple:
        with self._lock:
            crc = (type_byte + len(data) + sum(data)) & 0xFF
            pkt = bytes([BYTE_START, type_byte, len(data)]) + data + bytes([crc, BYTE_END])
            self._ser.write(pkt)
            self.log.debug("→ STM32 TYPE=0x%02X DATA=%s", type_byte, data.hex())

            try:
                resp_type, resp_data = recv_packet(self._ser, timeout_sec)
            except STM32RxError as e:
                raise STM32Error(str(e))

            if resp_type == NACK_TYPE:
                try:
                    _, err_data = recv_packet(self._ser, 1.0)
                    code = err_data[0] if err_data else -1
                except Exception:
                    code = -1
                raise STM32Error(f"NACK от STM32, код={code}")

            self.log.debug("← STM32 TYPE=0x%02X DATA=%s", resp_type, resp_data.hex())
            return resp_type, resp_data

    # ─── Публичный API ───────────────────────────────────────────────────────

    def send_action(self, code: int) -> bool:
        timeout = _ACTION_TIMEOUTS.get(code, _ACTION_TIMEOUT_DEFAULT)
        self.log.debug("→ STM32 ACTION code=%d timeout=%.1fs", code, timeout)
        try:
            resp_type, _ = self._transact(_TYPE_ACTION, bytes([code]), timeout)
            return resp_type == ACK_TYPE
        except (STM32Error, TimeoutError) as e:
            self.log.error("send_action(%d): %s", code, e)
            return False

    def read_hall_sensors(self) -> Optional[int]:
        try:
            _, data = self._transact(_TYPE_HALL, b"", _REQUEST_TIMEOUT)
            return data[0] if data else None
        except (STM32Error, TimeoutError) as e:
            self.log.error("read_hall_sensors: %s", e)
            return None

    def read_voltage(self) -> Optional[float]:
        try:
            _, data = self._transact(_TYPE_VOLTAGE, b"", _REQUEST_TIMEOUT)
            if len(data) < 2:
                return None
            return struct.unpack(">H", data[:2])[0] / 10.0
        except (STM32Error, TimeoutError) as e:
            self.log.error("read_voltage: %s", e)
            return None

    def read_dht22(self) -> Optional[tuple]:
        try:
            _, data = self._transact(_TYPE_DHT22, b"", _REQUEST_TIMEOUT)
            if len(data) < 4:
                return None
            hum_raw  = (data[0] << 8) | data[1]
            temp_raw = (data[2] << 8) | data[3]
            temp = -((temp_raw & 0x7FFF) / 10.0) if (temp_raw & 0x8000) else temp_raw / 10.0
            return temp, hum_raw / 10.0
        except (STM32Error, TimeoutError) as e:
            self.log.error("read_dht22: %s", e)
            return None
