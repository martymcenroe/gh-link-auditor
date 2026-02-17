"""Centralized logging configuration for gh-link-auditor.

Provides setup_logging() and get_logger() for consistent file + console
logging with rotation. See LLD #11 for design rationale.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

# LLD §2.7: 5MB max per file, 3 backups (~15MB total)
_DEFAULT_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_DEFAULT_BACKUP_COUNT = 3
_DEFAULT_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DEFAULT_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def setup_logging(
    name: str = "app",
    level: str = "INFO",
    log_dir: str = "logs",
    console: bool = True,
    file: bool = True,
) -> logging.Logger:
    """Configure and return a logger with console and/or file handlers.

    Args:
        name: Logger name (usually module name).
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_dir: Directory for log files.
        console: Enable console output on stderr.
        file: Enable file output with rotation.

    Returns:
        Configured Logger instance.
    """
    logger = logging.getLogger(name)

    # LLD §7.2: Prevent handler duplication on repeated calls
    if logger.handlers:
        logger.handlers.clear()

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(numeric_level)

    formatter = logging.Formatter(_DEFAULT_FORMAT, datefmt=_DEFAULT_DATE_FORMAT)

    # LLD §2.7: Console uses stderr (Unix convention)
    if console:
        stream_handler = logging.StreamHandler()  # defaults to stderr
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    if file:
        try:
            os.makedirs(log_dir, exist_ok=True)
            file_handler = RotatingFileHandler(
                filename=os.path.join(log_dir, f"{name}.log"),
                maxBytes=_DEFAULT_MAX_BYTES,
                backupCount=_DEFAULT_BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError:
            # LLD §7.2: Graceful fallback — log warning to console if file fails
            if not console:
                fallback = logging.StreamHandler()
                fallback.setFormatter(formatter)
                logger.addHandler(fallback)
            logger.warning(
                "Could not create log directory '%s'; falling back to console only.",
                log_dir,
            )

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get an existing logger by name.

    Args:
        name: Logger name to retrieve.

    Returns:
        Logger instance (creates default if not previously configured).
    """
    return logging.getLogger(name)
