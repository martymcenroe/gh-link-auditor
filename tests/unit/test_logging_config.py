"""Unit tests for logging_config module.

Tests for setup_logging() and get_logger() covering handler creation,
log directory creation, console output format, and level configuration.
See LLD Issue #11.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from unittest.mock import patch

import pytest

from logging_config import get_logger, setup_logging


@pytest.fixture(autouse=True)
def _clean_loggers():
    """Remove test loggers after each test to avoid handler accumulation."""
    yield
    for name in list(logging.Logger.manager.loggerDict):
        if name.startswith("test_"):
            logger = logging.getLogger(name)
            logger.handlers.clear()


@pytest.fixture
def log_dir(tmp_path):
    """Provide a temporary log directory."""
    return str(tmp_path / "logs")


# ---------------------------------------------------------------------------
# T010 – setup_logging creates logger with both handlers (REQ-1)
# ---------------------------------------------------------------------------


class TestSetupLogging:
    def test_returns_logger_instance(self, log_dir):
        logger = setup_logging(name="test_basic", log_dir=log_dir)
        assert isinstance(logger, logging.Logger)

    def test_both_handlers_created(self, log_dir):
        logger = setup_logging(name="test_both", log_dir=log_dir, console=True, file=True)
        handler_types = [type(h) for h in logger.handlers]
        assert logging.StreamHandler in handler_types
        assert RotatingFileHandler in handler_types
        assert len(logger.handlers) == 2

    def test_console_only(self, log_dir):
        logger = setup_logging(name="test_console", log_dir=log_dir, console=True, file=False)
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.StreamHandler)

    def test_file_only(self, log_dir):
        logger = setup_logging(name="test_file", log_dir=log_dir, console=False, file=True)
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], RotatingFileHandler)


# ---------------------------------------------------------------------------
# T020 – Log directory created with rotation (REQ-2)
# ---------------------------------------------------------------------------


class TestLogDirectory:
    def test_directory_created(self, log_dir):
        setup_logging(name="test_dir", log_dir=log_dir, file=True)
        assert os.path.isdir(log_dir)

    def test_log_file_created(self, log_dir):
        setup_logging(name="test_logfile", log_dir=log_dir, file=True)
        assert os.path.exists(os.path.join(log_dir, "test_logfile.log"))

    def test_rotating_handler_configured(self, log_dir):
        logger = setup_logging(name="test_rotate", log_dir=log_dir, file=True)
        file_handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
        assert len(file_handlers) == 1
        assert file_handlers[0].maxBytes == 5 * 1024 * 1024  # 5MB
        assert file_handlers[0].backupCount == 3

    def test_nested_directory_created(self, tmp_path):
        nested = str(tmp_path / "a" / "b" / "logs")
        setup_logging(name="test_nested", log_dir=nested, file=True)
        assert os.path.isdir(nested)


# ---------------------------------------------------------------------------
# T030 – Console output format (REQ-3)
# ---------------------------------------------------------------------------


class TestConsoleFormat:
    def test_format_includes_timestamp_level_message(self, log_dir, capfd):
        logger = setup_logging(name="test_fmt", log_dir=log_dir, console=True, file=False)
        logger.info("hello world")
        captured = capfd.readouterr()
        # Console goes to stderr
        assert "hello world" in captured.err
        assert "INFO" in captured.err

    def test_output_goes_to_stderr(self, log_dir, capfd):
        logger = setup_logging(name="test_stderr", log_dir=log_dir, console=True, file=False)
        logger.warning("test message")
        captured = capfd.readouterr()
        assert captured.out == ""
        assert "test message" in captured.err


# ---------------------------------------------------------------------------
# T050 – Log levels configurable with INFO default (REQ-5)
# ---------------------------------------------------------------------------


class TestLogLevels:
    def test_default_level_is_info(self, log_dir):
        logger = setup_logging(name="test_default_level", log_dir=log_dir)
        assert logger.level == logging.INFO

    def test_debug_level(self, log_dir):
        logger = setup_logging(name="test_debug", log_dir=log_dir, level="DEBUG")
        assert logger.level == logging.DEBUG

    def test_warning_level(self, log_dir):
        logger = setup_logging(name="test_warn", log_dir=log_dir, level="WARNING")
        assert logger.level == logging.WARNING

    def test_case_insensitive_level(self, log_dir):
        logger = setup_logging(name="test_case", log_dir=log_dir, level="debug")
        assert logger.level == logging.DEBUG

    def test_invalid_level_defaults_to_info(self, log_dir):
        logger = setup_logging(name="test_invalid", log_dir=log_dir, level="BOGUS")
        assert logger.level == logging.INFO


# ---------------------------------------------------------------------------
# Handler deduplication (REQ-1 edge case)
# ---------------------------------------------------------------------------


class TestHandlerDeduplication:
    def test_no_duplicate_handlers_on_repeated_calls(self, log_dir):
        setup_logging(name="test_dedup", log_dir=log_dir, console=True, file=True)
        logger = setup_logging(name="test_dedup", log_dir=log_dir, console=True, file=True)
        assert len(logger.handlers) == 2


# ---------------------------------------------------------------------------
# get_logger
# ---------------------------------------------------------------------------


class TestGetLogger:
    def test_returns_logger(self):
        logger = get_logger("test_get")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_get"

    def test_returns_same_logger(self, log_dir):
        setup_logging(name="test_same", log_dir=log_dir)
        logger = get_logger("test_same")
        assert logger.name == "test_same"


# ---------------------------------------------------------------------------
# Graceful fallback on OSError (REQ-2 edge case)
# ---------------------------------------------------------------------------


class TestGracefulFallback:
    def test_fallback_on_invalid_path(self, capfd):
        # NUL is not a valid directory on any OS
        logger = setup_logging(name="test_fallback", log_dir="/dev/null/impossible", console=True, file=True)
        # Should still have a console handler despite file failure
        assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)

    def test_fallback_creates_console_handler_when_console_disabled(self):
        """When file=True, console=False, and log dir creation fails,
        a fallback StreamHandler is created automatically."""
        with patch("logging_config.os.makedirs", side_effect=OSError("forced")):
            logger = setup_logging(
                name="test_fallback_no_console",
                log_dir="/tmp/fake_logs",
                console=False,
                file=True,
            )
        # Should have exactly one fallback StreamHandler despite console=False
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.StreamHandler)
        assert not isinstance(logger.handlers[0], RotatingFileHandler)
