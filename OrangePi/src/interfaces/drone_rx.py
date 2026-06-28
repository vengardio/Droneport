"""
Приём CRSF пакетов от дрона (фоновый поток → drone_q).

CRSF: ADDR(1) + LEN(1) + TYPE(1) + PAYLOAD + CRC8(poly=0xD5)
LEN = TYPE(1) + PAYLOAD + CRC(1)
"""

import logging
import threading
import time
from typing import Optional

import serial

from services.message_queue import MessageQueue

# Только фреймы канала Дрон → Дронпорт (ADDR=0x80).
# 0x28/0x29/0x2B/0x2D/0x2E/0x2F идут к НавСтанции (ADDR=0xEE) — на нашем радио не появятся.
CRSF_TO_CMD = {
    0x1E: 40,   # TELEMETRY_FAST      → сервер CMD 40
    0x1F: 41,   # TELEMETRY_SLOW      → сервер CMD 41
    0x20: 42,   # SOS                 → сервер CMD 42
    0x21: 44,   # BOARDING_REQUEST    → сервер CMD 44
    0x22: 48,   # ERROR               → сервер CMD 48
}


def _crc8_d5(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0xD5) & 0xFF if (crc & 0x80) else (crc << 1) & 0xFF
    return crc


class DronePacket:
    __slots__ = ("cmd", "crsf_type", "addr", "payload", "timestamp")

    def __init__(self, cmd: int, crsf_type: int, addr: int, payload: bytes):
        self.cmd       = cmd
        self.crsf_type = crsf_type
        self.addr      = addr
        self.payload   = payload
        self.timestamp = time.monotonic()


class DroneRX:
    def __init__(
        self,
        port:     str,
        baudrate: int,
        queue:    MessageQueue,
        logger:   Optional[logging.Logger] = None,
    ):
        self._port     = port
        self._baudrate = baudrate
        self._q        = queue
        self.log       = logger or logging.getLogger(__name__)
        self._ser:     Optional[serial.Serial] = None
        self._running  = False
        self._thread:  Optional[threading.Thread] = None

    def start(self) -> bool:
        try:
            self._ser = serial.Serial(
                port=self._port,
                baudrate=self._baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.1,
            )
            self._running = True
            self._thread = threading.Thread(target=self._recv_loop, daemon=True, name="drone_rx")
            self._thread.start()
            self.log.info("DroneRX запущен: %s @ %d", self._port, self._baudrate)
            return True
        except Exception as e:
            self.log.error("DroneRX открыть не удалось: %s", e)
            return False

    @property
    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def stop(self) -> None:
        self._running = False
        if self._ser and self._ser.is_open:
            self._ser.close()
        self._ser = None

    def _recv_loop(self) -> None:
        buf = bytearray()

        while self._running:
            try:
                chunk = self._ser.read(128)
            except Exception as e:
                self.log.error("DroneRX serial read ошибка: %s", e)
                break

            if not chunk:
                continue

            buf.extend(chunk)

            while len(buf) >= 4:
                addr      = buf[0]
                length    = buf[1]
                frame_len = 2 + length

                if length < 2:
                    del buf[0]
                    continue

                if frame_len > len(buf):
                    break

                frame = bytes(buf[:frame_len])
                del buf[:frame_len]

                msg_type = frame[2]
                payload  = frame[3:-1]
                crc_rx   = frame[-1]
                crc_calc = _crc8_d5(frame[2:-1])

                if crc_calc != crc_rx:
                    self.log.warning(
                        "CRSF RX плохой CRC: type=0x%02X rx=0x%02X calc=0x%02X",
                        msg_type, crc_rx, crc_calc,
                    )
                    continue

                cmd = CRSF_TO_CMD.get(msg_type)
                if cmd is None:
                    self.log.debug("CRSF RX неизвестный тип 0x%02X, пропуск", msg_type)
                    continue

                pkt = DronePacket(cmd=cmd, crsf_type=msg_type, addr=addr, payload=payload)
                self._q.push(pkt)
                self.log.debug("DroneRX: CMD=%d (CRSF 0x%02X)", cmd, msg_type)
