"""
src/interfaces/udp_server_tx.py
Формирование и отправка UDP пакетов серверу.

Структура пакета (спека р. 4.4):
    [DLE STX] [ID:2 LE] [NUM:1] [LEN:1] [CMD:2 LE] [DATA:LEN] [CS:1] [DLE ETX]
"""

import logging
import struct
from enum import IntEnum
from typing import Optional, Tuple

from .udp_server_init import UDPInitializer

DLE = 0x10
STX = 0x02
ETX = 0x03
ACK  = 0xF1
NACK = 0xF2

MAX_DATA_LEN = 71
DEFAULT_SUBSYSTEM_ID = 2001


# ---------------------------------------------------------------------------
# Перечисление команд
# ---------------------------------------------------------------------------

class DroneportCommand(IntEnum):
    """Команды от Дронпорта к Серверу (спека р. 6.3)."""
    RESULT_STATUS_SHUTTERS       = 30
    RESULT_DIAGNOSTIC            = 31
    RESULT_CONDITION_DRONE       = 32
    RESULT_EXTERNAL_PARAM        = 33
    RESPONSE_COORDINATE_DRONEPORT = 34
    STATUS_DRONEPORT             = 35
    TELEMETRY_FAST               = 40
    TELEMETRY_SLOW               = 41
    SOS                          = 42
    DEMO_RESULT                  = 43
    BOARDING_REQUEST             = 44
    DIAG_RESULT                  = 45
    TARGET                       = 46
    RETURN_DRONE                 = 47
    ERROR                        = 48


# ---------------------------------------------------------------------------
# Модуль отправки
# ---------------------------------------------------------------------------

class UDPServerTX:
    """
    Собирает пакеты по протоколу дронпорта и отправляет через UDPInitializer.
    """

    def __init__(
        self,
        logger:       logging.Logger,
        udp_init:     UDPInitializer,
        droneport_num: int = 1,
        subsystem_id:  int = DEFAULT_SUBSYSTEM_ID,
        log_raw:       bool = False,
    ):
        self.logger        = logger
        self.udp_init      = udp_init
        self.droneport_num = droneport_num
        self.subsystem_id  = subsystem_id
        self.log_raw       = log_raw

        self.logger.info(
            "UDPServerTX init: droneport_id=%d, subsystem_id=%d",
            droneport_num, subsystem_id,
        )

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    async def send_packet(
        self,
        cmd:  int,
        data: bytes = b"",
        addr: Optional[Tuple[str, int]] = None,
    ) -> bool:
        """Собрать и отправить пакет с произвольной командой."""
        try:
            raw = self._build_packet(cmd, data)
            ok  = await self.udp_init.send_raw(raw, addr)
            if ok:
                self.logger.debug(
                    "Sent CMD=%d (%s), %d bytes", cmd, self._cmd_name(cmd), len(raw)
                )
            return ok
        except Exception as exc:
            self.logger.error("send_packet error: %s", exc, exc_info=True)
            return False

    async def send_ack(
        self,
        original_cmd: int,
        success:      bool = True,
        error_code:   int  = 0,
    ) -> bool:
        """Отправить ACK или NACK в ответ на команду."""
        try:
            raw = self._build_ack(original_cmd, success, error_code)
            ok  = await self.udp_init.send_raw(raw)
            if ok:
                self.logger.debug(
                    "Sent %s for CMD=%d", "ACK" if success else "NACK", original_cmd
                )
            return ok
        except Exception as exc:
            self.logger.error("send_ack error: %s", exc, exc_info=True)
            return False

    async def send_status_droneport(self, ready: bool = True) -> bool:
        """CMD=35 STATUS_DRONEPORT: 1=готов, 0=не готов."""
        payload = bytes([1 if ready else 0])
        return await self.send_packet(DroneportCommand.STATUS_DRONEPORT, payload)

    async def send_external_param(
        self,
        temp_inside:   int,
        temp_outside:  int,
        wind_speed:    int,
        wind_direction: int,
        light_sensor:  int = 0,
    ) -> bool:
        """CMD=33 RESULT_EXTERNAL_PARAM: struct '<hhBhB'."""
        data = struct.pack(
            "<hhBhB",
            temp_inside, temp_outside, wind_speed, wind_direction, light_sensor,
        )
        return await self.send_packet(DroneportCommand.RESULT_EXTERNAL_PARAM, data)

    async def send_error_packet(self, errors: list) -> bool:
        """CMD=48 ERROR: список байтовых структур ошибок."""
        return await self.send_packet(DroneportCommand.ERROR, b"".join(errors))

    # ------------------------------------------------------------------
    # Сборка пакетов
    # ------------------------------------------------------------------

    def _checksum(self, data: bytes) -> int:
        return sum(data) & 0xFF

    def _build_packet(
        self,
        cmd:          int,
        data:         bytes = b"",
        num:          Optional[int] = None,
        subsystem_id: Optional[int] = None,
    ) -> bytes:
        if len(data) > MAX_DATA_LEN:
            raise ValueError(
                f"Data too long: {len(data)} bytes (max {MAX_DATA_LEN})"
            )

        num_val = num if num is not None else self.droneport_num
        sid     = subsystem_id if subsystem_id is not None else self.subsystem_id

        header = struct.pack("<HBBH", sid, num_val, len(data), cmd)
        core   = header + data

        return bytes([DLE, STX]) + core + bytes([self._checksum(core), DLE, ETX])

    def _build_ack(self, original_cmd: int, success: bool, error_code: int) -> bytes:
        cmd_byte = ACK if success else NACK
        payload  = bytes([original_cmd & 0xFF, error_code & 0xFF])
        return self._build_packet(cmd_byte, payload)

    def _cmd_name(self, cmd: int) -> str:
        try:
            return DroneportCommand(cmd).name
        except ValueError:
            return f"UNKNOWN({cmd})"