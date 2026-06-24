"""
UART интерфейс метеостанции (Arduino Nano).

Протокол: отправляем 0x01, получаем 8 байт (4× uint16 LE):
  [0:2] wind_dir      — градусы 0..359
  [2:4] wind_spd      — м/с × 10
  [4:6] temperature   — °C × 10 + 1000 (offset encoding)
  [6:8] humidity      — % × 10

Физика: /dev/ttyUSB1, 115200 бод, 8N1.
Arduino TX (5V) → делитель → RX OrangePi (3.3V).
"""

import asyncio
import logging
import struct
from typing import Optional

import serial  # pyserial

log = logging.getLogger(__name__)

REQUEST_BYTE  = 0x01
RESPONSE_LEN  = 8
TEMP_OFFSET   = 1000


class WeatherStation:
    """
    Фасад метеостанции Arduino Nano.
    Паттерн аналогичен STM32Interface: connect/disconnect + read_weather().
    При ошибках возвращает None (исключения не пробрасывает).
    """

    def __init__(
        self,
        port: str = "/dev/ttyUSB1",
        baudrate: int = 115200,
        timeout: float = 2.0,
        logger: Optional[logging.Logger] = None,
    ):
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._ser: Optional[serial.Serial] = None
        self._lock = asyncio.Lock()
        self.log = logger or log

    # ------------------------------------------------------------------
    # Жизненный цикл
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        def _open():
            return serial.Serial(
                port=self._port,
                baudrate=self._baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self._timeout,
            )
        try:
            self._ser = await asyncio.to_thread(_open)
            self.log.info("WeatherStation UART открыт: %s @ %d", self._port, self._baudrate)
            return True
        except Exception as e:
            self.log.error("Не удалось открыть %s: %s", self._port, e)
            return False

    async def disconnect(self) -> None:
        if self._ser and self._ser.is_open:
            await asyncio.to_thread(self._ser.close)
            self.log.info("WeatherStation UART закрыт")
        self._ser = None

    @property
    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    async def read_weather(self) -> Optional[dict]:
        """
        Запросить данные у Arduino: 0x01 → 8 байт.

        Возвращает dict:
            wind_dir        — int, градусы 0..359
            wind_speed      — int, м/с × 10 (uint16 raw)
            temperature     — float, °C (декодировано из offset)
            humidity        — float, % (декодировано)

        Или None при ошибке/таймауте.
        """
        if not self.is_connected:
            self.log.error("WeatherStation: порт не открыт")
            return None

        async with self._lock:
            try:
                return await asyncio.to_thread(self._transact)
            except Exception as e:
                self.log.error("WeatherStation: ошибка чтения: %s", e)
                return None

    # ------------------------------------------------------------------
    # Внутренняя логика (выполняется в thread)
    # ------------------------------------------------------------------

    def _transact(self) -> Optional[dict]:
        self._ser.reset_input_buffer()
        self._ser.write(bytes([REQUEST_BYTE]))
        self._ser.flush()

        resp = self._ser.read(RESPONSE_LEN)
        if len(resp) != RESPONSE_LEN:
            self.log.warning(
                "WeatherStation: ожидали %d байт, получили %d", RESPONSE_LEN, len(resp)
            )
            return None

        wind_dir, wind_spd, temp_raw, hum_raw = struct.unpack("<HHHH", resp)

        self.log.debug(
            "WeatherStation raw: dir=%d spd=%d temp=%d hum=%d",
            wind_dir, wind_spd, temp_raw, hum_raw,
        )

        return {
            "wind_dir": wind_dir,
            "wind_speed": wind_spd,               # uint16, м/с × 10
            "temperature": (temp_raw - TEMP_OFFSET) / 10.0,  # °C
            "humidity": hum_raw / 10.0,            # %
        }
