"""
Приём UDP пакетов от сервера.

Структура пакета:
    [DLE STX] [ID:2 LE] [NUM:1] [LEN:1] [CMD:2 LE] [DATA:LEN] [CS:1] [DLE ETX]

Фоновый поток читает сокет, расшифровывает AES-GCM, парсит пакет,
кладёт DronePortPacket в server_q.
"""

import logging
import socket
import struct
import threading
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

from services.encrypt.encryption import load_aesgcm, decrypt_packet
from services.message_queue import MessageQueue

DLE = 0x10
STX = 0x02
ETX = 0x03
ACK  = 0xF1
NACK = 0xF2

MIN_PACKET_SIZE = 11


class ServerCommand(IntEnum):
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


@dataclass
class DronePortPacket:
    id:       int
    num:      int
    cmd:      int
    cmd_name: str
    data:     bytes
    raw:      bytes = field(default=b"", repr=False)
    addr:     tuple = field(default_factory=tuple)


class ServerRX:
    """
    Фоновый поток приёма UDP: recvfrom → decrypt → parse → server_q.push()
    """

    def __init__(
        self,
        bind_ip:      str,
        bind_port:    int,
        queue:        MessageQueue,
        logger:       logging.Logger,
        subsystem_id: int = 2001,
        droneport_num: int = 1,
        log_raw:      bool = False,
    ):
        self.bind_ip       = bind_ip
        self.bind_port     = bind_port
        self._q            = queue
        self.logger        = logger
        self.subsystem_id  = subsystem_id
        self.droneport_num = droneport_num
        self.log_raw       = log_raw

        self._aesgcm  = load_aesgcm()
        self._sock:   Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.settimeout(1.0)
            self._sock.bind((self.bind_ip, self.bind_port))
            self._running = True
            self._thread = threading.Thread(target=self._recv_loop, daemon=True, name="server_rx")
            self._thread.start()
            self.logger.info("ServerRX bound to %s:%d", self.bind_ip, self.bind_port)
            return True
        except OSError as e:
            self.logger.error("ServerRX bind failed: %s", e)
            return False

    def stop(self) -> None:
        self._running = False
        if self._sock:
            self._sock.close()
            self._sock = None

    def get_socket(self) -> Optional[socket.socket]:
        return self._sock

    def _recv_loop(self) -> None:
        while self._running:
            try:
                raw, addr = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                plain = decrypt_packet(self._aesgcm, raw)
            except Exception as e:
                self.logger.warning("AES decrypt failed from %s: %s", addr, e)
                continue

            if self.log_raw:
                self.logger.debug("RAW from %s: %s", addr, plain.hex())

            pkt = self._parse(plain, addr)
            if pkt is None:
                self.logger.warning("Bad packet from %s, ignored", addr)
                continue

            self.logger.info("RX CMD=%d (%s) from %s", pkt.cmd, pkt.cmd_name, addr)
            self._q.push(pkt)

    def _parse(self, raw: bytes, addr: tuple) -> Optional[DronePortPacket]:
        if len(raw) < MIN_PACKET_SIZE:
            return None
        if raw[:2] != bytes([DLE, STX]) or raw[-2:] != bytes([DLE, ETX]):
            return None

        core     = raw[2:-3]
        checksum = raw[-3]
        if checksum != (sum(core) & 0xFF):
            return None
        if len(core) < 6:
            return None

        id_val, num, length, cmd = struct.unpack("<HBBH", core[:6])
        data = core[6:6+length] if length > 0 else b""
        if len(data) != length:
            return None
        if id_val != self.subsystem_id or num != self.droneport_num:
            self.logger.warning(
                "Packet not for us: id=%d (want %d), num=%d (want %d)",
                id_val, self.subsystem_id, num, self.droneport_num,
            )
            return None

        return DronePortPacket(
            id=id_val, num=num, cmd=cmd,
            cmd_name=self._cmd_name(cmd),
            data=data, raw=raw, addr=addr,
        )

    def _cmd_name(self, cmd: int) -> str:
        try:
            return ServerCommand(cmd).name
        except ValueError:
            if cmd == ACK:  return "ACK"
            if cmd == NACK: return "NACK"
            return f"UNKNOWN({cmd})"
