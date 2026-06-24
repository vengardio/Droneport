"""
src/interfaces/udp_server_rx.py
Приём и парсинг входящих UDP пакетов от сервера.

Структура пакета (спека р. 4.3):
    [DLE STX] [ID:2 LE] [NUM:1] [LEN:1] [CMD:2 LE] [DATA:LEN] [CS:1] [DLE ETX]
"""

import asyncio
import logging
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Awaitable, Callable, Dict, Optional

DLE = 0x10
STX = 0x02
ETX = 0x03
ACK = 0xF1
NACK = 0xF2

MIN_PACKET_SIZE = 11  # DLE+STX(2) + ID(2) + NUM(1) + LEN(1) + CMD(2) + CS(1) + DLE+ETX(2)


# ---------------------------------------------------------------------------
# Перечисление команд
# ---------------------------------------------------------------------------

class ServerCommand(IntEnum):
    """Команды от Сервера к Дронпорту (спека р. 6.2)."""
    OPEN_DRONPORT       = 1
    CLOSE_DRONPORT      = 2
    DIAGNOSTIC          = 3
    CONDITION_DRON      = 4
    EXTERNAL_PARAM      = 5
    REQUEST_COORDINATE  = 6
    STATUS_SHUTTERS     = 7
    STATUS              = 8
    COMBAT_MODE         = 20
    TARGET_INTERCEPTION = 21
    DEMO_MODE           = 22
    SECTOR_SEARCH       = 23
    DIAGNOSTIC_FLIGHT   = 24
    DRONE_FLIGHT        = 25
    STOP                = 26
    RETURN              = 27
    PRE_FLIGHT          = 28
    COORDINATE_NED      = 29
    DRONE_COMM_STATUS   = 50


# ---------------------------------------------------------------------------
# Структура пакета
# ---------------------------------------------------------------------------

@dataclass
class DronePortPacket:
    """Распарсенный пакет от сервера."""
    id:       int
    num:      int
    cmd:      int
    cmd_name: str
    data:     bytes
    raw:      bytes = field(default=b'', repr=False)
    addr:     tuple = field(default_factory=tuple)

    @property
    def is_valid(self) -> bool:
        return (
            0 <= self.num <= 254
            and 0 <= len(self.data) <= 71
            and 0 < self.id < 2 ** 32
        )

    @property
    def is_ack(self) -> bool:
        return self.cmd == ACK

    @property
    def is_nack(self) -> bool:
        return self.cmd == NACK


# ---------------------------------------------------------------------------
# Модуль приёма
# ---------------------------------------------------------------------------

class UDPServerRX:
    """
    Принимает UDP-датаграммы, парсит их по протоколу дронпорта
    и вызывает зарегистрированный хендлер для каждой команды.
    """

    def __init__(
        self,
        logger: logging.Logger,
        droneport_num: int = 1,
        subsystem_id:  int = 2001,
        log_raw:       bool = False,
    ):
        self.logger        = logger
        self.droneport_num = droneport_num
        self.subsystem_id  = subsystem_id
        self.log_raw       = log_raw

        self._handlers: Dict[int, Callable[[DronePortPacket], Awaitable[Dict]]] = {}

        self.logger.info(
            "UDPServerRX init: droneport_id=%d, subsystem_id=%d",
            droneport_num, subsystem_id,
        )

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def register_handler(
        self,
        cmd_code: int,
        handler: Callable[[DronePortPacket], Awaitable[Dict]],
    ) -> None:
        """Привязать асинхронный хендлер к коду команды."""
        self._handlers[cmd_code] = handler
        self.logger.debug("Registered handler for CMD=%d", cmd_code)

    def get_handler_count(self) -> int:
        return len(self._handlers)

    def on_datagram_received(self, data: bytes, addr: tuple) -> None:
        """
        Callback от UDPInitializer. Парсит пакет и запускает хендлер
        как asyncio.Task — не блокирует приём следующих датаграмм.
        """
        packet = self._parse_packet(data, addr)
        if packet is None:
            self.logger.warning("Invalid packet from %s, ignored", addr)
            return
        asyncio.create_task(self._dispatch(packet))

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _checksum(self, data: bytes) -> int:
        """Контрольная сумма: sum(bytes) % 256."""
        return sum(data) & 0xFF

    def _cmd_name(self, cmd: int) -> str:
        try:
            return ServerCommand(cmd).name
        except ValueError:
            if cmd == ACK:
                return "ACK"
            if cmd == NACK:
                return "NACK"
            return f"UNKNOWN({cmd})"

    def _parse_packet(self, raw: bytes, addr: tuple) -> Optional[DronePortPacket]:
        """
        Парсит сырые байты в DronePortPacket.
        Возвращает None если пакет невалиден.
        """
        if len(raw) < MIN_PACKET_SIZE:
            self.logger.warning("Packet too short: %d bytes", len(raw))
            return None

        if raw[:2] != bytes([DLE, STX]) or raw[-2:] != bytes([DLE, ETX]):
            self.logger.warning(
                "Bad framing: prefix=%s suffix=%s",
                raw[:2].hex(), raw[-2:].hex(),
            )
            return None

        core     = raw[2:-3]
        checksum = raw[-3]

        if checksum != self._checksum(core):
            self.logger.warning(
                "Checksum mismatch: got %02X, expected %02X",
                checksum, self._checksum(core),
            )
            return None

        if len(core) < 6:
            self.logger.warning("Core too short: %d bytes", len(core))
            return None

        id_val, num, length, cmd = struct.unpack("<HBBH", core[:6])
        data = core[6 : 6 + length] if length > 0 else b""

        if len(data) != length:
            self.logger.warning(
                "Data length mismatch: declared=%d actual=%d", length, len(data)
            )
            return None

        if id_val != self.subsystem_id or num != self.droneport_num:
            self.logger.warning(
                "Packet not for us: id=%d (want %d), num=%d (want %d)",
                id_val, self.subsystem_id, num, self.droneport_num,
            )
            return None

        if self.log_raw:
            self.logger.debug("Raw packet: %s", raw.hex())

        return DronePortPacket(
            id=id_val, num=num,
            cmd=cmd, cmd_name=self._cmd_name(cmd),
            data=data, raw=raw, addr=addr,
        )

    async def _dispatch(self, packet: DronePortPacket) -> Optional[Dict]:
        """Найти и вызвать хендлер для пакета."""
        self.logger.info(
            "Received CMD=%d (%s) from %s", packet.cmd, packet.cmd_name, packet.addr
        )

        handler = self._handlers.get(packet.cmd)
        if handler is None:
            self.logger.warning("No handler for CMD=%d", packet.cmd)
            return None

        try:
            return await asyncio.wait_for(handler(packet), timeout=30.0)
        except asyncio.TimeoutError:
            self.logger.error("Handler timeout for CMD=%d", packet.cmd)
            return {"error": "timeout", "cmd": packet.cmd}
        except Exception as exc:
            self.logger.error("Handler error for CMD=%d: %s", packet.cmd, exc, exc_info=True)
            return {"error": str(exc), "cmd": packet.cmd}