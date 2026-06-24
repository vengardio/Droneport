"""
src/services/error_handler.py
Централизованный сбор ошибок и отправка ERROR-пакетов серверу (CMD=48).

Каждая ошибка — 4 байта: [error_class | subsystem | code | flags].
При недоступности сервера ошибки буферизуются до 50 штук.
"""

import asyncio
import logging
import traceback
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Dict, List, Optional

CMD_ERROR = 48


# ---------------------------------------------------------------------------
# Справочники
# ---------------------------------------------------------------------------

class ErrorClass(IntEnum):
    """Класс ошибки — байт 0 в структуре (спека р. 8.1)."""
    HARDWARE      = 0x01
    POWER         = 0x02
    COMMUNICATION = 0x03
    NAVIGATION    = 0x04
    MECHANICS     = 0x05
    SOFTWARE      = 0x06
    SENSORS       = 0x07
    SAFETY        = 0x08
    ENVIRONMENT   = 0x09
    SECURITY      = 0x0A


class ErrorSubsystem(IntEnum):
    """Подсистема-источник ошибки — байт 1 в структуре."""
    NAVIGATION_SYSTEM = 0x01
    DRONEPORT         = 0x02
    INTERCEPTOR_DRONE = 0x03
    CENTRAL_SERVER    = 0x04


class Severity(IntEnum):
    """Уровень критичности — биты 0-1 в байте flags."""
    INFO     = 0b00
    WARNING  = 0b01
    ERROR    = 0b10
    CRITICAL = 0b11


# Биты в байте flags
FLAG_OPERATOR_INTERVENTION = 0b00000100
FLAG_EMERGENCY_STOP        = 0b00001000


@dataclass
class ErrorCodeMapping:
    """Маппинг строкового кода ошибки → числовые поля протокола."""
    error_class: ErrorClass
    subsystem:   ErrorSubsystem
    code:        int


# Полная таблица кодов ошибок (спека р. 8.1)
ERROR_CODE_MAP: Dict[str, ErrorCodeMapping] = {
    # Дронпорт — питание
    "MAINS_LOST":             ErrorCodeMapping(ErrorClass.POWER,         ErrorSubsystem.DRONEPORT,         0x01),
    "BATTERY_LOW":            ErrorCodeMapping(ErrorClass.POWER,         ErrorSubsystem.DRONEPORT,         0x02),
    # Дронпорт — механика
    "SHUTTER_BLOCKED_OPENED": ErrorCodeMapping(ErrorClass.MECHANICS,     ErrorSubsystem.DRONEPORT,         0x10),
    "SHUTTER_BLOCKED_CLOSED": ErrorCodeMapping(ErrorClass.MECHANICS,     ErrorSubsystem.DRONEPORT,         0x11),
    "SHUTTER_TIMEOUT":        ErrorCodeMapping(ErrorClass.MECHANICS,     ErrorSubsystem.DRONEPORT,         0x12),
    "TABLE_BLOCKED_UP":       ErrorCodeMapping(ErrorClass.MECHANICS,     ErrorSubsystem.DRONEPORT,         0x13),
    "TABLE_BLOCKED_DOWN":     ErrorCodeMapping(ErrorClass.MECHANICS,     ErrorSubsystem.DRONEPORT,         0x14),
    "TABLE_TIMEOUT":          ErrorCodeMapping(ErrorClass.MECHANICS,     ErrorSubsystem.DRONEPORT,         0x15),
    "ERROR_HEATING":          ErrorCodeMapping(ErrorClass.MECHANICS,     ErrorSubsystem.DRONEPORT,         0x16),
    # Дронпорт — связь
    "DRONE_NOT_DETECTED":     ErrorCodeMapping(ErrorClass.COMMUNICATION, ErrorSubsystem.DRONEPORT,         0x20),
    "DRONE_NO_RESPONSE":      ErrorCodeMapping(ErrorClass.COMMUNICATION, ErrorSubsystem.DRONEPORT,         0x21),
    # Дронпорт — датчики / среда
    "TEMP_SENSOR_FAIL":       ErrorCodeMapping(ErrorClass.SENSORS,       ErrorSubsystem.DRONEPORT,         0x30),
    "TEMP_OUT_OF_RANGE":      ErrorCodeMapping(ErrorClass.ENVIRONMENT,   ErrorSubsystem.DRONEPORT,         0x31),
    # Дронпорт — безопасность
    "MAINTENANCE_MODE":       ErrorCodeMapping(ErrorClass.SAFETY,        ErrorSubsystem.DRONEPORT,         0x40),
    "UNAUTHORIZED_COMMAND":   ErrorCodeMapping(ErrorClass.SECURITY,      ErrorSubsystem.DRONEPORT,         0x50),
    # БПЛА
    "BATTERY_CRITICAL":       ErrorCodeMapping(ErrorClass.POWER,         ErrorSubsystem.INTERCEPTOR_DRONE, 0x02),
    "ESC_FAIL":               ErrorCodeMapping(ErrorClass.MECHANICS,     ErrorSubsystem.INTERCEPTOR_DRONE, 0x11),
    "POSITION_LOST":          ErrorCodeMapping(ErrorClass.NAVIGATION,    ErrorSubsystem.INTERCEPTOR_DRONE, 0x20),
    "POSITION_JUMP":          ErrorCodeMapping(ErrorClass.NAVIGATION,    ErrorSubsystem.INTERCEPTOR_DRONE, 0x21),
    "CAMERA_FAIL":            ErrorCodeMapping(ErrorClass.SENSORS,       ErrorSubsystem.INTERCEPTOR_DRONE, 0x30),
    "THERMAL_FAIL":           ErrorCodeMapping(ErrorClass.SENSORS,       ErrorSubsystem.INTERCEPTOR_DRONE, 0x31),
    "TARGET_LOST":            ErrorCodeMapping(ErrorClass.SOFTWARE,      ErrorSubsystem.INTERCEPTOR_DRONE, 0x40),
    "STATION_OVERHEAT":       ErrorCodeMapping(ErrorClass.HARDWARE,      ErrorSubsystem.INTERCEPTOR_DRONE, 0x41),
    "LINK_NAV_LOST":          ErrorCodeMapping(ErrorClass.COMMUNICATION, ErrorSubsystem.INTERCEPTOR_DRONE, 0x50),
    "UNAUTHORIZED_COMMAND_DRONE": ErrorCodeMapping(ErrorClass.SECURITY,  ErrorSubsystem.INTERCEPTOR_DRONE, 0x60),
}


# ---------------------------------------------------------------------------
# Структура одной ошибки
# ---------------------------------------------------------------------------

@dataclass
class ErrorEntry:
    """
    Одна ошибка — сериализуется в 4 байта для отправки серверу.
        байт 0: error_class
        байт 1: subsystem
        байт 2: code
        байт 3: flags (severity | operator_flag | emergency_flag)
    """
    error_class:   ErrorClass
    subsystem:     ErrorSubsystem
    code:          int
    severity:      Severity = Severity.ERROR
    needs_operator: bool    = False
    emergency_stop: bool    = False

    def to_bytes(self) -> bytes:
        flags = self.severity.value & 0b11
        if self.needs_operator:
            flags |= FLAG_OPERATOR_INTERVENTION
        if self.emergency_stop:
            flags |= FLAG_EMERGENCY_STOP
        return bytes([
            self.error_class.value & 0xFF,
            self.subsystem.value  & 0xFF,
            self.code             & 0xFF,
            flags                 & 0xFF,
        ])

    def __str__(self) -> str:
        return (
            f"Error(class={self.error_class.name}, "
            f"subsystem={self.subsystem.name}, "
            f"code=0x{self.code:02X}, "
            f"severity={self.severity.name})"
        )


# ---------------------------------------------------------------------------
# Обработчик ошибок
# ---------------------------------------------------------------------------

class ErrorHandler:
    """
    Принимает ошибки из любого модуля, сериализует и отправляет серверу.
    При недоступности сервера буферизует до MAX_BUFFER_SIZE записей.
    """

    MAX_ERRORS_PER_PACKET = 17   # максимум ошибок в одном UDP-пакете
    MAX_BUFFER_SIZE       = 50   # максимум записей в буфере

    def __init__(
        self,
        logger:        logging.Logger,
        droneport_num: int = 1,
        send_callback: Optional[Callable[[int, bytes], asyncio.Future]] = None,
        buffer_errors: bool = True,
    ):
        self.logger        = logger
        self.droneport_num = droneport_num
        self.send_callback = send_callback
        self.buffer_errors = buffer_errors

        self._error_buffer: List[ErrorEntry] = []
        self._buffer_lock = asyncio.Lock()

        self.logger.debug(
            "ErrorHandler init: droneport_id=%d, buffer=%s",
            droneport_num, buffer_errors,
        )

    def set_send_callback(
        self,
        callback: Callable[[int, bytes], asyncio.Future],
    ) -> None:
        self.send_callback = callback
        self.logger.info("ErrorHandler send callback set")

    # ------------------------------------------------------------------
    # Основной метод репорта
    # ------------------------------------------------------------------

    async def report_error(
        self,
        code:           str,
        message:        str,
        context:        Optional[Dict] = None,
        severity:       Severity = Severity.ERROR,
        needs_operator: bool = False,
        emergency_stop: bool = False,
    ) -> None:
        """
        Залогировать ошибку и отправить серверу.
        Если отправка не удалась — положить в буфер.
        """
        self._log(code, message, context, severity)

        entry = self._make_entry(code, severity, needs_operator, emergency_stop)
        sent  = await self._send([entry])

        if not sent and self.buffer_errors:
            await self._buffer(entry, code)

    # ------------------------------------------------------------------
    # Шорткаты
    # ------------------------------------------------------------------

    async def report_critical_alert(
        self, code: str, message: str,
        context: Optional[Dict] = None,
        emergency_stop: bool = True,
    ) -> None:
        await self.report_error(
            code=code, message=message, context=context,
            severity=Severity.CRITICAL,
            emergency_stop=emergency_stop, needs_operator=True,
        )

    async def report_hardware_error(
        self, code: str, message: str,
        context: Optional[Dict] = None,
    ) -> None:
        await self.report_error(
            code=code, message=message, context=context,
            severity=Severity.ERROR,
        )

    async def report_communication_error(
        self, code: str, message: str,
        context: Optional[Dict] = None,
    ) -> None:
        await self.report_error(
            code=code, message=message, context=context,
            severity=Severity.WARNING,
        )

    async def report_sensor_error(
        self, code: str, message: str,
        context: Optional[Dict] = None,
    ) -> None:
        await self.report_error(
            code=code, message=message, context=context,
            severity=Severity.ERROR, needs_operator=True,
        )

    # ------------------------------------------------------------------
    # Буфер
    # ------------------------------------------------------------------

    async def flush_buffer(self) -> None:
        """Отправить всё накопленное в буфере на сервер."""
        async with self._buffer_lock:
            if not self._error_buffer:
                return

            self.logger.info("Flushing %d buffered errors...", len(self._error_buffer))
            batch = self._error_buffer[: self.MAX_ERRORS_PER_PACKET]

            if await self._send(batch):
                self._error_buffer = self._error_buffer[len(batch):]
                self.logger.info(
                    "Flushed %d errors, %d remaining",
                    len(batch), len(self._error_buffer),
                )
            else:
                self.logger.warning("Flush failed, will retry later")

    async def shutdown(self) -> None:
        """Сбросить буфер перед остановкой."""
        self.logger.info("ErrorHandler shutting down...")
        if self._error_buffer:
            await self.flush_buffer()
        self.logger.info("ErrorHandler shutdown complete")

    # ------------------------------------------------------------------
    # Утилиты
    # ------------------------------------------------------------------

    def log_exception(self, exc: Exception, context: Optional[Dict] = None) -> None:
        """Залогировать полный traceback исключения."""
        self.logger.error(
            "Exception: %s | Context: %s\n%s",
            exc, context, traceback.format_exc(),
        )

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _log(
        self,
        code:     str,
        message:  str,
        context:  Optional[Dict],
        severity: Severity,
    ) -> None:
        msg = f"[{code}] {message}"
        if context:
            ctx_str = ", ".join(f"{k}={v}" for k, v in context.items())
            msg += f" | Context: {{{ctx_str}}}"

        if severity == Severity.CRITICAL:
            self.logger.critical(msg)
        elif severity == Severity.ERROR:
            self.logger.error(msg)
        elif severity == Severity.WARNING:
            self.logger.warning(msg)
        else:
            self.logger.info(msg)

    def _make_entry(
        self,
        code:           str,
        severity:       Severity,
        needs_operator: bool,
        emergency_stop: bool,
    ) -> ErrorEntry:
        mapping = ERROR_CODE_MAP.get(code)
        if mapping is None:
            self.logger.warning("Unknown error code: %s, using SOFTWARE/DRONEPORT/0xFF", code)
            return ErrorEntry(
                error_class=ErrorClass.SOFTWARE,
                subsystem=ErrorSubsystem.DRONEPORT,
                code=0xFF,
                severity=severity,
                needs_operator=needs_operator,
                emergency_stop=emergency_stop,
            )
        return ErrorEntry(
            error_class=mapping.error_class,
            subsystem=mapping.subsystem,
            code=mapping.code,
            severity=severity,
            needs_operator=needs_operator,
            emergency_stop=emergency_stop,
        )

    async def _send(self, errors: List[ErrorEntry]) -> bool:
        if not errors:
            return True
        if self.send_callback is None:
            self.logger.warning("No send callback — errors not sent to server")
            return False
        try:
            payload = b"".join(e.to_bytes() for e in errors)
            ok = await self.send_callback(CMD_ERROR, payload)
            if ok:
                self.logger.debug("Error packet sent: %d errors", len(errors))
            else:
                self.logger.warning("Error packet send failed (server unreachable?)")
            return ok
        except Exception as exc:
            self.logger.error("Failed to send error packet: %s", exc, exc_info=True)
            return False

    async def _buffer(self, entry: ErrorEntry, code: str) -> None:
        async with self._buffer_lock:
            if len(self._error_buffer) < self.MAX_BUFFER_SIZE:
                self._error_buffer.append(entry)
                self.logger.debug(
                    "Error buffered: %s. Buffer: %d/%d",
                    code, len(self._error_buffer), self.MAX_BUFFER_SIZE,
                )
            else:
                self.logger.error("Buffer full! Dropping error: %s", code)