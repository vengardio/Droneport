import logging
import os
import sys
from logging.handlers import RotatingFileHandler

LOG_FORMAT  = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logger(name: str, level: int = logging.INFO, log_file_path: str = None) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        logger.setLevel(level)
        return logger

    logger.setLevel(level)
    logger.propagate = False
    fmt = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    ch.setLevel(level)
    logger.addHandler(ch)

    if log_file_path:
        try:
            log_dir = os.path.dirname(log_file_path)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            fh = RotatingFileHandler(
                log_file_path, maxBytes=5*1024*1024, backupCount=3,
                encoding="utf-8", delay=True
            )
            fh.setFormatter(fmt)
            fh.setLevel(level)
            logger.addHandler(fh)
        except (OSError, PermissionError) as e:
            logger.error("File logging failed: %s", e)

    return logger
