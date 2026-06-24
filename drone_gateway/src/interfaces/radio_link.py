"""High-level radio link bridge: USART transport + CRSF RX/TX."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional, Tuple

from .usart_drone_init import DroneRadioType, USARTConfig, USARTDroneInitializer
from .usart_drone_rx import DroneProtocolType, USARTDroneRX
from .usart_drone_tx import USARTDroneTX


@dataclass
class RadioLinkConfig:
    """Configuration for radio link over USART."""

    port: str = "/dev/ttyUSB0"
    baudrate: int = 115200
    timeout: float = 0.1
    log_raw: bool = False


class RadioLink:
    """
    Bridge layer used by CommandHandlers.

    Public API:
      - start() / stop()
      - send_command(cmd: int, data: bytes) -> bool
      - receive_packet() -> tuple[cmd:int, data:bytes]
    """

    # CRSF -> internal command codes expected by command handlers / UDP TX.
    _CRSF_TO_CMD = {
        0x1E: 40,  # TELEMETRY_FAST
        0x1F: 41,  # TELEMETRY_SLOW
        0x20: 42,  # SOS
        0x21: 44,  # BOARDING_REQUEST
        0x22: 48,  # ERROR
        0x28: 40,  # TELEMETRY_FAST (drone -> nav station channel)
        0x29: 41,  # TELEMETRY_SLOW (drone -> nav station channel)
        0x2B: 43,  # DEMO_RESULT
        0x2D: 45,  # DIAG_RESULT
        0x2E: 46,  # TARGET
        0x2F: 47,  # RETURN_DRONE (de-facto; spec marks as to clarify)
    }

    def __init__(self, logger: logging.Logger, config: RadioLinkConfig) -> None:
        self.logger = logger
        self.config = config

        usart_cfg = USARTConfig(
            port=config.port,
            baudrate=config.baudrate,
            timeout=config.timeout,
        )
        self._init = USARTDroneInitializer(
            logger=logger,
            config=usart_cfg,
            radio_type=DroneRadioType.CUSTOM,
        )
        self._rx = USARTDroneRX(
            logger=logger,
            protocol_type=DroneProtocolType.TBS_CROSSFIRE,
            log_raw=config.log_raw,
        )
        self._tx = USARTDroneTX(
            logger=logger,
            usart_init=self._init,
            radio_type=DroneRadioType.CUSTOM,
            log_raw=config.log_raw,
        )

        self._running = False
        self._rx_task: Optional[asyncio.Task] = None
        self._bridge_task: Optional[asyncio.Task] = None
        self._incoming_cmd_queue: asyncio.Queue[Tuple[int, bytes]] = asyncio.Queue(maxsize=2048)

    async def start(self) -> bool:
        if self._running:
            return True

        ok = await self._init.start()
        if not ok:
            return False

        self._init.set_receive_callback(self._rx.on_data_received)
        self._running = True

        self._rx_task = asyncio.create_task(
            self._init.start_receive_loop(),
            name="radio_usart_rx_loop",
        )
        self._bridge_task = asyncio.create_task(
            self._bridge_packets_loop(),
            name="radio_crsf_bridge_loop",
        )
        self.logger.info("RadioLink started: %s @ %d", self.config.port, self.config.baudrate)
        return True

    async def stop(self) -> None:
        self._running = False

        if self._bridge_task is not None:
            self._bridge_task.cancel()
            try:
                await self._bridge_task
            except asyncio.CancelledError:
                pass
            self._bridge_task = None

        await self._init.stop()

        if self._rx_task is not None:
            self._rx_task.cancel()
            try:
                await self._rx_task
            except asyncio.CancelledError:
                pass
            self._rx_task = None

        self.logger.info("RadioLink stopped")

    async def _bridge_packets_loop(self) -> None:
        """Move parsed CRSF packets from RX module to command queue."""
        while self._running:
            try:
                packet = await self._rx.wait_packet(timeout=1.0)
                cmd = self._CRSF_TO_CMD.get(packet.msg_type)
                if cmd is None:
                    self.logger.debug("RadioLink: unknown CRSF type 0x%02X skipped", packet.msg_type)
                    continue
                if self._incoming_cmd_queue.full():
                    _ = self._incoming_cmd_queue.get_nowait()
                    self.logger.warning("RadioLink RX queue full, oldest packet dropped")
                await self._incoming_cmd_queue.put((cmd, packet.payload))
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.logger.error("RadioLink bridge loop error: %s", exc, exc_info=True)
                await asyncio.sleep(0.2)

    async def send_command(self, cmd: int, data: bytes = b"") -> bool:
        """Send command to UAV. Accepts scenario command code."""
        return await self._tx.send_command(command=cmd, data=data)

    async def receive_packet(self) -> Tuple[int, bytes]:
        """Get next normalized packet from UAV side."""
        return await self._incoming_cmd_queue.get()