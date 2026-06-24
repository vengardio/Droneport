"""USART transport for OrangePi <-> radio module."""

import asyncio
import logging
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Optional

try:
    import serial_asyncio
except ImportError:
    serial_asyncio = None

try:
    import serial
except ImportError:
    serial = None


@dataclass
class USARTConfig:
    """USART connection settings."""

    port: str = "/dev/ttyUSB0"
    baudrate: int = 115200
    bytesize: int = 8
    parity: str = "N"
    stopbits: float = 1.0
    timeout: float = 0.1
    write_timeout: float = 0.2
    rtscts: bool = False
    dsrdtr: bool = False


class DroneRadioType(IntEnum):
    UNKNOWN = 0
    FRSKY = 1
    TBS_CROSSFIRE = 2
    ELRS = 3
    CUSTOM = 4


class USARTDroneInitializer:
    """Low-level asynchronous USART transport."""

    def __init__(
        self,
        logger: logging.Logger,
        config: USARTConfig,
        radio_type: DroneRadioType = DroneRadioType.CUSTOM,
    ) -> None:
        self.logger = logger
        self.config = config
        self.radio_type = radio_type

        self._reader = None
        self._writer = None
        self._port = None
        self._receive_callback: Optional[Callable[[bytes], None]] = None
        self._running = False

        self.logger.info(
            "USART created: port=%s baud=%d type=%s",
            self.config.port,
            self.config.baudrate,
            self.radio_type.name,
        )

    def set_receive_callback(self, callback: Callable[[bytes], None]) -> None:
        self._receive_callback = callback
        self.logger.debug("USART receive callback registered")

    async def start(self) -> bool:
        """Open serial connection with async-first fallback strategy."""
        if self._running:
            self.logger.debug("USART already running")
            return True

        if serial_asyncio is None and serial is None:
            self.logger.error("serial libraries are missing")
            return False

        try:
            if serial_asyncio is not None:
                self._reader, self._writer = await serial_asyncio.open_serial_connection(
                    url=self.config.port,
                    baudrate=self.config.baudrate,
                    bytesize=self.config.bytesize,
                    parity=self.config.parity,
                    stopbits=self.config.stopbits,
                )
            else:
                self._port = serial.Serial(
                    port=self.config.port,
                    baudrate=self.config.baudrate,
                    bytesize=self.config.bytesize,
                    parity=self.config.parity,
                    stopbits=self.config.stopbits,
                    timeout=self.config.timeout,
                    write_timeout=self.config.write_timeout,
                    rtscts=self.config.rtscts,
                    dsrdtr=self.config.dsrdtr,
                )
            self._running = True
            self.logger.info("USART opened: %s", self.config.port)
            return True
        except Exception as exc:
            self.logger.error("USART open failed: %s", exc, exc_info=True)
            return False

    async def send_raw(self, data: bytes) -> bool:
        if not self.is_running:
            self.logger.warning("USART send skipped: transport is down")
            return False

        try:
            if self._writer is not None:
                self._writer.write(data)
                await self._writer.drain()
            elif self._port is not None:
                await asyncio.to_thread(self._port.write, data)
                await asyncio.to_thread(self._port.flush)
            else:
                return False
            return True
        except Exception as exc:
            self.logger.error("USART send failed: %s", exc, exc_info=True)
            return False

    async def read_raw(self, size: int = 512) -> Optional[bytes]:
        if not self.is_running:
            return None

        try:
            if self._reader is not None:
                data = await asyncio.wait_for(self._reader.read(size), timeout=self.config.timeout)
                return data if data else None
            if self._port is not None:
                data = await asyncio.to_thread(self._port.read, size)
                return data if data else None
            return None
        except asyncio.TimeoutError:
            return None
        except Exception as exc:
            self.logger.error("USART read failed: %s", exc, exc_info=True)
            return None

    async def start_receive_loop(self) -> None:
        """Read bytes and pass them to registered callback."""
        self.logger.info("USART RX loop started")
        while self._running:
            try:
                chunk = await self.read_raw(1024)
                if chunk and self._receive_callback is not None:
                    self._receive_callback(chunk)
                await asyncio.sleep(0.005)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.logger.error("USART RX loop error: %s", exc, exc_info=True)
                await asyncio.sleep(0.2)

    async def stop(self) -> None:
        self._running = False

        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

        if self._port is not None:
            await asyncio.to_thread(self._port.close)
            self._port = None

        self.logger.info("USART stopped")

    @property
    def is_running(self) -> bool:
        return self._running and (self._writer is not None or self._port is not None)