"""Receive and parse CRSF frames from UAV radio."""

import asyncio
import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Awaitable, Callable, Dict, Optional


def crc8_d5(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0xD5) & 0xFF if (crc & 0x80) else (crc << 1) & 0xFF
    return crc


@dataclass
class DroneTelemetryPacket:
    """Parsed CRSF packet."""

    addr: int
    msg_type: int
    payload: bytes
    raw: bytes = field(default=b"", repr=False)
    timestamp: float = field(default_factory=lambda: asyncio.get_event_loop().time())

    @property
    def packet_type(self) -> str:
        return f"0x{self.msg_type:02X}"

    @property
    def data(self) -> Dict[str, object]:
        return {"addr": self.addr, "msg_type": self.msg_type, "payload": self.payload}

    @property
    def is_valid(self) -> bool:
        return len(self.raw) >= 5


class DroneProtocolType(IntEnum):
    UNKNOWN = 0
    MAVLINK = 1
    FRSKY = 2
    TBS_CROSSFIRE = 3
    CUSTOM = 4


class USARTDroneRX:
    """Streaming CRSF parser and callback dispatcher."""

    def __init__(
        self,
        logger: logging.Logger,
        protocol_type: DroneProtocolType = DroneProtocolType.TBS_CROSSFIRE,
        log_raw: bool = False,
    ) -> None:
        self.logger = logger
        self.protocol_type = protocol_type
        self.log_raw = log_raw

        self._buffer = bytearray()
        self._max_buffer_size = 8192
        self._handlers: Dict[int, Callable[[DroneTelemetryPacket], Awaitable[object]]] = {}
        self._packet_queue: asyncio.Queue[DroneTelemetryPacket] = asyncio.Queue()

    def register_handler(
        self,
        packet_type: int,
        handler: Callable[[DroneTelemetryPacket], Awaitable[object]],
    ) -> None:
        self._handlers[int(packet_type) & 0xFF] = handler

    def _extract_one_packet(self) -> Optional[DroneTelemetryPacket]:
        """
        Parse one packet from internal buffer.
        CRSF layout: ADDR | LEN | TYPE | PAYLOAD | CRC
        """
        if len(self._buffer) < 5:
            return None

        addr = self._buffer[0]
        length = self._buffer[1]
        frame_len = 2 + length  # full frame from ADDR to CRC inclusive

        if length < 2:
            del self._buffer[0]
            return None

        if frame_len > len(self._buffer):
            return None

        frame = bytes(self._buffer[:frame_len])
        del self._buffer[:frame_len]

        msg_type = frame[2]
        payload = frame[3:-1]
        crc_rx = frame[-1]
        crc_calc = crc8_d5(frame[2:-1])
        if crc_calc != crc_rx:
            self.logger.warning(
                "CRSF RX bad CRC: type=0x%02X rx=0x%02X calc=0x%02X",
                msg_type,
                crc_rx,
                crc_calc,
            )
            return None

        return DroneTelemetryPacket(addr=addr, msg_type=msg_type, payload=payload, raw=frame)

    async def _dispatch(self, packet: DroneTelemetryPacket) -> None:
        await self._packet_queue.put(packet)
        handler = self._handlers.get(packet.msg_type)
        if handler is None:
            return
        try:
            await asyncio.wait_for(handler(packet), timeout=5.0)
        except asyncio.TimeoutError:
            self.logger.warning("CRSF RX handler timeout for type=%s", packet.packet_type)
        except Exception as exc:
            self.logger.error("CRSF RX handler failed: %s", exc, exc_info=True)

    def on_data_received(self, data: bytes) -> None:
        """Callback for USART transport."""
        if not data:
            return
        self._buffer.extend(data)
        if self.log_raw:
            self.logger.debug("CRSF RX raw: %s", data.hex(" "))

        if len(self._buffer) > self._max_buffer_size:
            self.logger.warning("CRSF RX buffer overflow, clearing")
            self._buffer.clear()
            return

        while True:
            packet = self._extract_one_packet()
            if packet is None:
                break
            asyncio.create_task(self._dispatch(packet))

    async def wait_packet(self, timeout: float = 20.0) -> DroneTelemetryPacket:
        return await asyncio.wait_for(self._packet_queue.get(), timeout=timeout)

    def clear_buffer(self) -> None:
        self._buffer.clear()

    def get_buffer_size(self) -> int:
        return len(self._buffer)