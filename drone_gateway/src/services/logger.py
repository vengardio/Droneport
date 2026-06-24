"""Логгер: консоль + ротация файлов."""
import logging, os, sys
from logging.handlers import RotatingFileHandler
from typing import Optional

DEFAULT_MAX_BYTES, DEFAULT_BACKUP_COUNT = 5 * 1024 * 1024, 3
LOG_FORMAT, DATE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S"

def setup_logger(name: str, level: int = logging.INFO, log_file_path: Optional[str] = None) -> logging.Logger:
    """Настраивает и возвращает объект logger с консольным и файловым выводом."""
    logger = logging.getLogger(name)
    if logger.handlers:
        logger.setLevel(level)
        return logger

    logger.setLevel(level)
    logger.propagate = False
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # Консольный обработчик
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)
    logger.addHandler(console_handler)

    # Файловый обработчик
    if log_file_path:
        try:
            log_dir = os.path.dirname(log_file_path)
            if log_dir and not os.path.exists(log_dir): os.makedirs(log_dir, exist_ok=True)
            file_handler = RotatingFileHandler(log_file_path, maxBytes=DEFAULT_MAX_BYTES,
                backupCount=DEFAULT_BACKUP_COUNT, encoding='utf-8', delay=True)
            file_handler.setFormatter(formatter)
            file_handler.setLevel(level)
            logger.addHandler(file_handler)
            logger.info(f"Logger initialized. File logging enabled: {log_file_path}")
        except (OSError, PermissionError) as e:
            fallback = logging.getLogger(f"{name}.fallback")
            fallback.setLevel(logging.ERROR)
            if not fallback.handlers:
                ch = logging.StreamHandler(sys.stderr)
                ch.setFormatter(formatter)
                fallback.addHandler(ch)
            fallback.error(f"Failed to initialize file logging at {log_file_path}: {e}. System will continue with console logging only.")
    return logger