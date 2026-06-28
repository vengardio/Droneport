import logging
import time
from typing import Optional

import serial
import pynmea2


class GPS:
    def __init__(self, port: str = "/dev/ttyACM0", baudrate: int = 9600,
                 logger: Optional[logging.Logger] = None):
        self._port     = port
        self._baudrate = baudrate
        self.log       = logger or logging.getLogger(__name__)
        self._ser:     Optional[serial.Serial] = None

    def connect(self) -> bool:
        try:
            self._ser = serial.Serial(self._port, self._baudrate, timeout=2.0)
            self.log.info("GPS открыт: %s @ %d", self._port, self._baudrate)
            return True
        except Exception as e:
            self.log.error("GPS: %s", e)
            return False

    @property
    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def get_coordinates(self, timeout_sec: float = 10.0) -> Optional[dict]:
        if not self.is_connected:
            return None
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            try:
                line = self._ser.readline().decode("ascii", errors="replace").strip()
            except Exception as e:
                self.log.error("GPS read: %s", e)
                return None
            if not line.startswith("$GPGGA"):
                continue
            try:
                msg = pynmea2.parse(line)
            except Exception:
                continue
            if not msg.gps_qual or msg.gps_qual == 0:
                continue
            return {
                "latitude":    msg.latitude,
                "longitude":   msg.longitude,
                "altitude":    float(msg.altitude) if msg.altitude else 0.0,
                "fix_quality": msg.gps_qual,
                "satellites":  int(msg.num_sats) if msg.num_sats else 0,
                "timestamp":   time.monotonic(),
            }
        self.log.warning("GPS: нет фикса за %.0fс", timeout_sec)
        return None
