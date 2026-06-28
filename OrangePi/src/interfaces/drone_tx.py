"""
Отправка CRSF команд дрону.

CRSF: ADDR(1) + LEN(1) + TYPE(1) + PAYLOAD + CRC8(poly=0xD5)
"""

import logging
from typing import Optional

import serial

SERVER_CMD_TO_CRSF = {
    20: 0x11,  # COMBAT_MODE
    21: 0x12,  # TARGET_INTERCEPTION
    22: 0x17,  # DEMO_MODE
    23: 0x13,  # SECTOR_SEARCH
    24: 0x16,  # DIAGNOSTIC_FLIGHT
    25: 0x14,  # DRONE_FLIGHT
    26: 0x1A,  # STOP
    27: 0x1B,  # RETURN
    28: 0x15,  # PRE_FLIGHT
    29: 0x19,  # COORDINATE_NED
}

CRSF_ADDR_DRONE = 0xC8


def _crc8_d5(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0xD5) & 0xFF if (crc & 0x80) else (crc << 1) & 0xFF
    return crc


def _build_crsf(msg_type: int, payload: bytes = b"", addr: int = CRSF_ADDR_DRONE) -> bytes:
    length = 1 + len(payload) + 1  # TYPE + PAYLOAD + CRC
    type_and_payload = bytes([msg_type]) + payload
    crc = _crc8_d5(type_and_payload)
    return bytes([addr, length]) + type_and_payload + bytes([crc])


class DroneTX:
    def __init__(
        self,
        ser:    serial.Serial,
        logger: Optional[logging.Logger] = None,
    ):
        self._ser = ser
        self.log  = logger or logging.getLogger(__name__)

    def send_command(self, cmd: int, data: bytes = b"") -> bool:
        if self._ser is None:
            self.log.debug("[STUB] DroneTX CMD=%d (нет serial)", cmd)
            return True
        msg_type = SERVER_CMD_TO_CRSF.get(cmd, cmd & 0xFF)
        try:
            pkt = _build_crsf(msg_type, data)
            self._ser.write(pkt)
            self.log.debug("DroneTX: CMD=%d CRSF_TYPE=0x%02X", cmd, msg_type)
            return True
        except Exception as e:
            self.log.error("DroneTX send ошибка: %s", e)
            return False
