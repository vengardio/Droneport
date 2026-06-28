"""
Отправка UDP пакетов серверу.

Структура: [DLE STX] [ID:2 LE] [NUM:1] [LEN:1] [CMD:2 LE] [DATA] [CS:1] [DLE ETX]
Шифрование: AES-256-GCM.
"""

import logging
import socket
import struct
from enum import IntEnum
from typing import Optional, Tuple

from services.encrypt.encryption import load_aesgcm, encrypt_packet

DLE  = 0x10
STX  = 0x02
ETX  = 0x03
ACK  = 0xF1
NACK = 0xF2

MAX_DATA_LEN = 71


class DroneportCommand(IntEnum):
    RESULT_STATUS_SHUTTERS        = 30
    RESULT_DIAGNOSTIC             = 31
    RESULT_CONDITION_DRONE        = 32
    RESULT_EXTERNAL_PARAM         = 33
    RESPONSE_COORDINATE_DRONEPORT = 34
    STATUS_DRONEPORT              = 35
    TELEMETRY_FAST                = 40
    TELEMETRY_SLOW                = 41
    SOS                           = 42
    DEMO_RESULT                   = 43
    BOARDING_REQUEST              = 44
    DIAG_RESULT                   = 45
    TARGET                        = 46
    RETURN_DRONE                  = 47
    ERROR                         = 48


class ServerTX:
    def __init__(
        self,
        server_ip:     str,
        server_port:   int,
        sock:          socket.socket,
        logger:        logging.Logger,
        droneport_num: int = 1,
        subsystem_id:  int = 2001,
        log_raw:       bool = False,
    ):
        self.server_ip     = server_ip
        self.server_port   = server_port
        self._sock         = sock
        self.logger        = logger
        self.droneport_num = droneport_num
        self.subsystem_id  = subsystem_id
        self.log_raw       = log_raw
        self._aesgcm       = load_aesgcm()

    def send_packet(self, cmd: int, data: bytes = b"", addr: Optional[Tuple[str,int]] = None) -> bool:
        try:
            raw = self._build_packet(cmd, data)
            return self._send_raw(raw, addr)
        except Exception as e:
            self.logger.error("send_packet error: %s", e)
            return False

    def send_ack(self, original_cmd: int, success: bool = True, error_code: int = 0) -> bool:
        try:
            cmd_byte = ACK if success else NACK
            payload  = bytes([original_cmd & 0xFF, error_code & 0xFF])
            raw      = self._build_packet(cmd_byte, payload)
            ok = self._send_raw(raw)
            self.logger.debug("Sent %s for CMD=%d", "ACK" if success else "NACK", original_cmd)
            return ok
        except Exception as e:
            self.logger.error("send_ack error: %s", e)
            return False

    def _build_packet(self, cmd: int, data: bytes = b"") -> bytes:
        if len(data) > MAX_DATA_LEN:
            raise ValueError(f"Data too long: {len(data)} bytes")
        header = struct.pack("<HBBH", self.subsystem_id, self.droneport_num, len(data), cmd)
        core   = header + data
        cs     = sum(core) & 0xFF
        return bytes([DLE, STX]) + core + bytes([cs, DLE, ETX])

    def _send_raw(self, raw: bytes, addr: Optional[Tuple[str,int]] = None) -> bool:
        target = addr or (self.server_ip, self.server_port)
        try:
            encrypted = encrypt_packet(self._aesgcm, raw)
            self._sock.sendto(encrypted, target)
            if self.log_raw:
                self.logger.debug("TX to %s: %s", target, raw.hex())
            return True
        except Exception as e:
            self.logger.error("UDP send error: %s", e)
            return False
