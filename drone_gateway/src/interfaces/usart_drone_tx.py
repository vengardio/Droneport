"""Build and send CRSF frames to UAV radio."""

import logging
from enum import IntEnum
from typing import Union

from .usart_drone_init import DroneRadioType, USARTDroneInitializer


class DroneCommandType(IntEnum):
    """Server command codes used by current scenario engine."""

    COMBAT_MODE = 20
    TARGET_INTERCEPTION = 21
    DEMO_MODE = 22
    SECTOR_SEARCH = 23
    DIAGNOSTIC_FLIGHT = 24
    DRONE_FLIGHT = 25
    STOP = 26
    RETURN = 27
    PRE_FLIGHT = 28
    COORDINATE_NED = 29


CRSF_ADDR_DRONE = 0xC8

# Mapping server commands -> CRSF TYPE based on specification section 7.
SERVER_CMD_TO_CRSF_TYPE = {
    20: 0x11,  # COMBAT_MODE
    21: 0x12,  # TARGET_INTERCEPTION
    23: 0x13,  # SECTOR_SEARCH
    25: 0x14,  # DRONE_FLIGHT
    28: 0x15,  # PRE_FLIGHT
    24: 0x16,  # DIAGNOSTIC_FLIGHT
    26: 0x1A,  # STOP
    27: 0x1B,  # RETURN
}


def crc8_d5(data: bytes) -> int:
    """CRC8 with polynomial 0xD5 (CRSF)."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0xD5) & 0xFF if (crc & 0x80) else (crc << 1) & 0xFF
    return crc


class USARTDroneTX:
    """Transmit side of radio link."""

    def __init__(
        self,
        logger: logging.Logger,
        usart_init: USARTDroneInitializer,
        radio_type: DroneRadioType = DroneRadioType.CUSTOM,
        log_raw: bool = False,
    ) -> None:
        self.logger = logger
        self.usart_init = usart_init
        self.radio_type = radio_type
        self.log_raw = log_raw

    def _resolve_type(self, command: int) -> int:
        if command in SERVER_CMD_TO_CRSF_TYPE:
            return SERVER_CMD_TO_CRSF_TYPE[command]
        if 0 <= command <= 0xFF:
            # Allows direct use of CRSF TYPE or unsupported temporary commands.
            return command
        raise ValueError(f"Unsupported command code: {command}")

    def _build_packet(self, msg_type: int, payload: bytes = b"", addr: int = CRSF_ADDR_DRONE) -> bytes:
        """CRSF frame: ADDR + LEN + TYPE + PAYLOAD + CRC8."""
        if len(payload) > 60:
            raise ValueError("CRSF payload must be <= 60 bytes")
        length = 1 + len(payload) + 1  # TYPE + PAYLOAD + CRC
        type_and_payload = bytes([msg_type]) + payload
        crc = crc8_d5(type_and_payload)
        packet = bytes([addr, length]) + type_and_payload + bytes([crc])
        return packet

    async def send_command(self, command: Union[DroneCommandType, int], data: bytes = b"", **_: object) -> bool:
        """Send one command frame to UAV."""
        try:
            cmd_value = int(command)
            msg_type = self._resolve_type(cmd_value)
            packet = self._build_packet(msg_type=msg_type, payload=data)

            if self.log_raw:
                self.logger.debug("CRSF TX: %s", packet.hex(" "))

            return await self.usart_init.send_raw(packet)
        except Exception as exc:
            self.logger.error("CRSF send failed: %s", exc, exc_info=True)
            return False