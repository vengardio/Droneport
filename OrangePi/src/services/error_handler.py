import logging
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Dict, List, Optional


CMD_ERROR = 48


class ErrorClass(IntEnum):
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
    NAVIGATION_SYSTEM = 0x01
    DRONEPORT         = 0x02
    INTERCEPTOR_DRONE = 0x03
    CENTRAL_SERVER    = 0x04


class Severity(IntEnum):
    INFO     = 0b00
    WARNING  = 0b01
    ERROR    = 0b10
    CRITICAL = 0b11


FLAG_OPERATOR_INTERVENTION = 0b00000100
FLAG_EMERGENCY_STOP        = 0b00001000


@dataclass
class ErrorCodeMapping:
    error_class: ErrorClass
    subsystem:   ErrorSubsystem
    code:        int


ERROR_CODE_MAP: Dict[str, ErrorCodeMapping] = {
    "MAINS_LOST":             ErrorCodeMapping(ErrorClass.POWER,         ErrorSubsystem.DRONEPORT,         0x01),
    "BATTERY_LOW":            ErrorCodeMapping(ErrorClass.POWER,         ErrorSubsystem.DRONEPORT,         0x02),
    "SHUTTER_BLOCKED_OPENED": ErrorCodeMapping(ErrorClass.MECHANICS,     ErrorSubsystem.DRONEPORT,         0x10),
    "SHUTTER_BLOCKED_CLOSED": ErrorCodeMapping(ErrorClass.MECHANICS,     ErrorSubsystem.DRONEPORT,         0x11),
    "SHUTTER_TIMEOUT":        ErrorCodeMapping(ErrorClass.MECHANICS,     ErrorSubsystem.DRONEPORT,         0x12),
    "TABLE_BLOCKED_UP":       ErrorCodeMapping(ErrorClass.MECHANICS,     ErrorSubsystem.DRONEPORT,         0x13),
    "TABLE_BLOCKED_DOWN":     ErrorCodeMapping(ErrorClass.MECHANICS,     ErrorSubsystem.DRONEPORT,         0x14),
    "TABLE_TIMEOUT":          ErrorCodeMapping(ErrorClass.MECHANICS,     ErrorSubsystem.DRONEPORT,         0x15),
    "ERROR_HEATING":          ErrorCodeMapping(ErrorClass.MECHANICS,     ErrorSubsystem.DRONEPORT,         0x16),
    "DRONE_NOT_DETECTED":     ErrorCodeMapping(ErrorClass.COMMUNICATION, ErrorSubsystem.DRONEPORT,         0x20),
    "DRONE_NO_RESPONSE":      ErrorCodeMapping(ErrorClass.COMMUNICATION, ErrorSubsystem.DRONEPORT,         0x21),
    "TEMP_SENSOR_FAIL":       ErrorCodeMapping(ErrorClass.SENSORS,       ErrorSubsystem.DRONEPORT,         0x30),
    "TEMP_OUT_OF_RANGE":      ErrorCodeMapping(ErrorClass.ENVIRONMENT,   ErrorSubsystem.DRONEPORT,         0x31),
    "MAINTENANCE_MODE":       ErrorCodeMapping(ErrorClass.SAFETY,        ErrorSubsystem.DRONEPORT,         0x40),
    "UNAUTHORIZED_COMMAND":   ErrorCodeMapping(ErrorClass.SECURITY,      ErrorSubsystem.DRONEPORT,         0x50),
    "BATTERY_CRITICAL":       ErrorCodeMapping(ErrorClass.POWER,         ErrorSubsystem.INTERCEPTOR_DRONE, 0x02),
    "ESC_FAIL":               ErrorCodeMapping(ErrorClass.MECHANICS,     ErrorSubsystem.INTERCEPTOR_DRONE, 0x11),
    "POSITION_LOST":          ErrorCodeMapping(ErrorClass.NAVIGATION,    ErrorSubsystem.INTERCEPTOR_DRONE, 0x20),
    "POSITION_JUMP":          ErrorCodeMapping(ErrorClass.NAVIGATION,    ErrorSubsystem.INTERCEPTOR_DRONE, 0x21),
    "CAMERA_FAIL":            ErrorCodeMapping(ErrorClass.SENSORS,       ErrorSubsystem.INTERCEPTOR_DRONE, 0x30),
    "THERMAL_FAIL":           ErrorCodeMapping(ErrorClass.SENSORS,       ErrorSubsystem.INTERCEPTOR_DRONE, 0x31),
    "TARGET_LOST":            ErrorCodeMapping(ErrorClass.SOFTWARE,      ErrorSubsystem.INTERCEPTOR_DRONE, 0x40),
    "STATION_OVERHEAT":       ErrorCodeMapping(ErrorClass.SOFTWARE,      ErrorSubsystem.INTERCEPTOR_DRONE, 0x41),
    "LINK_NAV_LOST":          ErrorCodeMapping(ErrorClass.COMMUNICATION, ErrorSubsystem.INTERCEPTOR_DRONE, 0x50),
    "MECHANICS":              ErrorCodeMapping(ErrorClass.MECHANICS,     ErrorSubsystem.DRONEPORT,         0x19),
}


@dataclass
class ErrorEntry:
    error_class:    ErrorClass
    subsystem:      ErrorSubsystem
    code:           int
    severity:       Severity = Severity.ERROR
    needs_operator: bool     = False
    emergency_stop: bool     = False

    def to_bytes(self) -> bytes:
        flags = self.severity.value & 0b11
        if self.needs_operator:
            flags |= FLAG_OPERATOR_INTERVENTION
        if self.emergency_stop:
            flags |= FLAG_EMERGENCY_STOP
        return bytes([
            self.error_class.value & 0xFF,
            self.subsystem.value   & 0xFF,
            self.code              & 0xFF,
            flags                  & 0xFF,
        ])


class ErrorHandler:
    MAX_ERRORS_PER_PACKET = 17
    MAX_BUFFER_SIZE       = 50

    def __init__(
        self,
        logger:        logging.Logger,
        droneport_num: int = 1,
        send_callback: Optional[Callable[[int, bytes], bool]] = None,
        buffer_errors: bool = True,
    ):
        self.logger        = logger
        self.droneport_num = droneport_num
        self.send_callback = send_callback
        self.buffer_errors = buffer_errors
        self._buffer: List[ErrorEntry] = []

    def report_error(
        self,
        code:           str,
        message:        str,
        severity:       Severity = Severity.ERROR,
        needs_operator: bool = False,
        emergency_stop: bool = False,
    ) -> None:
        self._log(code, message, severity)
        entry = self._make_entry(code, severity, needs_operator, emergency_stop)
        sent = self._send([entry])
        if not sent and self.buffer_errors:
            self._buffer_entry(entry, code)

    def flush_buffer(self) -> None:
        if not self._buffer:
            return
        self.logger.info("Flushing %d buffered errors", len(self._buffer))
        batch = self._buffer[:self.MAX_ERRORS_PER_PACKET]
        if self._send(batch):
            self._buffer = self._buffer[len(batch):]

    def shutdown(self) -> None:
        if self._buffer:
            self.flush_buffer()

    def _log(self, code: str, message: str, severity: Severity) -> None:
        msg = f"[{code}] {message}"
        if severity == Severity.CRITICAL:
            self.logger.critical(msg)
        elif severity == Severity.ERROR:
            self.logger.error(msg)
        elif severity == Severity.WARNING:
            self.logger.warning(msg)
        else:
            self.logger.info(msg)

    def _make_entry(self, code, severity, needs_operator, emergency_stop) -> ErrorEntry:
        m = ERROR_CODE_MAP.get(code)
        if m is None:
            self.logger.warning("Unknown error code: %s", code)
            return ErrorEntry(ErrorClass.SOFTWARE, ErrorSubsystem.DRONEPORT, 0xFF,
                              severity, needs_operator, emergency_stop)
        return ErrorEntry(m.error_class, m.subsystem, m.code,
                          severity, needs_operator, emergency_stop)

    def _send(self, errors: List[ErrorEntry]) -> bool:
        if not errors or self.send_callback is None:
            return False
        try:
            payload = b"".join(e.to_bytes() for e in errors)
            return self.send_callback(CMD_ERROR, payload)
        except Exception as e:
            self.logger.error("ErrorHandler send failed: %s", e)
            return False

    def _buffer_entry(self, entry: ErrorEntry, code: str) -> None:
        if len(self._buffer) < self.MAX_BUFFER_SIZE:
            self._buffer.append(entry)
        else:
            self.logger.error("Error buffer full, dropping: %s", code)
