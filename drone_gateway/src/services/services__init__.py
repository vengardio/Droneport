"""
src/services/__init__.py
Вспомогательные сервисы: логирование, обработка ошибок, watchdog.
"""

from .logger        import setup_logger
from .error_handler import ErrorHandler, Severity

# TODO: раскомментировать когда watchdog будет реализован
# from .watchdog import Watchdog

__all__ = [
    "setup_logger",
    "ErrorHandler",
    "Severity",
]