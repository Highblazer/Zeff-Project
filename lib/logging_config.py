#!/usr/bin/env python3
"""
Standardized logging for all OpenClaw bots and services.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = '/root/.openclaw/workspace/logs'
MAX_LOG_SIZE = 5 * 1024 * 1024  # 5 MB
BACKUP_COUNT = 3
LOG_FORMAT = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


def get_logger(name: str, log_file: str = None, level=logging.INFO) -> logging.Logger:
    """Get a configured logger with both console and file output.

    Args:
        name: Logger name (typically the bot/service name).
        log_file: Log filename (placed in LOG_DIR). If None, uses {name}.log.
        level: Logging level (default INFO).
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # Already configured

    logger.setLevel(level)
    logger.propagate = False  # Prevent duplicate log entries from root logger

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # File handler with rotation
    if log_file is None:
        log_file = f"{name}.log"

    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, log_file)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=MAX_LOG_SIZE,
        backupCount=BACKUP_COUNT
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
