"""Error models and exception hierarchy for the crawler."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class ErrorCode(StrEnum):
    """Machine-readable error classification codes."""

    INVALID_INPUT = "INVALID_INPUT"
    FETCH_FAILED = "FETCH_FAILED"
    NOT_FOUND = "NOT_FOUND"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    RENDER_FAILED = "RENDER_FAILED"
    INVALID_SELECTOR = "INVALID_SELECTOR"
    DISALLOWED = "DISALLOWED"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"


class ErrorDetail(BaseModel):
    """Structured error detail returned in API error responses."""

    code: ErrorCode
    message: str
    recoverable: bool


class ErrorResponse(BaseModel):
    """Envelope for API error responses."""

    success: Literal[False] = False
    error: ErrorDetail


class CrawlerError(Exception):
    """Base exception for all crawler errors."""

    def __init__(self, code: ErrorCode, message: str, *, recoverable: bool = False) -> None:
        self.code = code
        self.message = message
        self.recoverable = recoverable
        super().__init__(message)


class FetchError(CrawlerError):
    """Raised when a page fetch fails (network error, HTTP error, timeout)."""


class RenderError(CrawlerError):
    """Raised when Playwright rendering fails."""


class JobNotFoundError(CrawlerError):
    """Raised when a job ID does not exist."""


class InputValidationError(CrawlerError):
    """Raised when input validation fails."""
