"""Structured logging configuration using structlog."""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(*, json_format: bool = False, level: str = "INFO") -> None:
    """Configure structlog with ISO timestamps and stderr output.

    Args:
        json_format: Use JSON renderer (for server mode) instead of console renderer.
        level: Minimum log level (e.g. "DEBUG", "INFO", "WARNING").
    """
    log_level: int = getattr(logging, level.upper(), logging.INFO)

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if json_format:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )
