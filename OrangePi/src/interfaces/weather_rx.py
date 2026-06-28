"""
UART интерфейс метеостанции (Arduino Nano, синхронный).

Протокол: отправляем 0x01, получаем 8 байт (4× uint16 LE):
  [0:2] wind_dir      — градусы 0..359
  [2:4] wind_spd      — м/с × 10
  [4:6] temperature   — °C × 10 + 1000 (offset encoding)
  [6:8] humidity      — % × 10
"""

import logging
import struct
import threading
from typing import Optional

import serial

REQUEST_BYTE = 0x01
RESPONSE_LEN = 8
TEMP_OFFSET  = 1000


class WeatherStation:
    def __init__(
        self,
        port:     str   = "/dev/ttyUSB1",
        baudrate: int   = 115200,
        timeout:  float = 2.0,
        logger:   Optional[logging.Logger] = None,
    ):
        self._port     = port
        self._baudrate = baudrate
        self._timeout  = timeout
        self._ser:     Optional[serial.Serial] = None
        self._lock     = threading.Lock()
        self.log       = logger or logging.getLogger(__name__)

    def connect(self) -> bool:
        try:
            self._ser = serial.Serial(
                port=self._port,
                baudrate=self._baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self._timeout,
            )
            self.log.info("WeatherStation UART открыт: %s @ %d", self._port, self._baudrate)
            return True
        except Exception as e:
            self.log.error("WeatherStation UART открыть не удалось: %s", e)
            return False

    def disconnect(self) -> None:
        if self._ser and self._ser.is_open:
            self._ser.close()
            self.log.info("WeatherStation UART закрыт")
        self._ser = None

    @property
    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def read_weather(self) -> Optional[dict]:
        if not self.is_connected:
            self.log.error("WeatherStation: порт не открыт")
            return None
        with self._lock:
            try:
                self._ser.reset_input_buffer()
                self._ser.write(bytes([REQUEST_BYTE]))
                self._ser.flush()
                resp = self._ser.read(RESPONSE_LEN)
                if len(resp) != RESPONSE_LEN:
                    self.log.warning("WeatherStation: ожидали %d байт, получили %d", RESPONSE_LEN, len(resp))
                    return None
                wind_dir, wind_spd, temp_raw, hum_raw = struct.unpack("<HHHH", resp)
                return {
                    "wind_dir":    wind_dir,
                    "wind_speed":  wind_spd,
                    "temperature": (temp_raw - TEMP_OFFSET) / 10.0,
                    "humidity":    hum_raw / 10.0,
                }
            except Exception as e:
                self.log.error("WeatherStation read ошибка: %s", e)
                return None
