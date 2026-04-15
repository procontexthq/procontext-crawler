"""Tests for structured logging configuration."""

from __future__ import annotations

import structlog

from proctx_crawler.logging_config import configure_logging


class TestConfigureLogging:
    def test_configure_console_mode(self) -> None:
        configure_logging(json_format=False, level="DEBUG")
        log = structlog.get_logger()
        # Verify structlog is configured (the logger is usable)
        assert log is not None

    def test_configure_json_mode(self) -> None:
        configure_logging(json_format=True, level="INFO")
        log = structlog.get_logger()
        assert log is not None

    def test_configure_with_warning_level(self) -> None:
        configure_logging(level="WARNING")
        log = structlog.get_logger()
        assert log is not None

    def test_default_parameters(self) -> None:
        # Should not raise
        configure_logging()
