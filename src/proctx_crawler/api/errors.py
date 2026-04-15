"""Global exception handlers that convert domain errors into HTTP responses."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from proctx_crawler.models import CrawlerError, ErrorCode, ErrorDetail, ErrorResponse

if TYPE_CHECKING:
    from fastapi import FastAPI
    from pydantic import ValidationError
    from starlette.requests import Request

ERROR_STATUS_MAP: dict[ErrorCode, int] = {
    ErrorCode.INVALID_INPUT: 400,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.JOB_NOT_FOUND: 404,
    ErrorCode.FETCH_FAILED: 502,
    ErrorCode.RENDER_FAILED: 502,
    ErrorCode.INVALID_SELECTOR: 400,
}


def _crawler_error_handler(_request: Request, exc: CrawlerError) -> JSONResponse:
    """Map a CrawlerError to an ErrorResponse JSON envelope."""
    status_code = ERROR_STATUS_MAP.get(exc.code, 500)
    body = ErrorResponse(
        error=ErrorDetail(
            code=exc.code,
            message=exc.message,
            recoverable=exc.recoverable,
        ),
    )
    return JSONResponse(status_code=status_code, content=body.model_dump())


def _validation_error_handler(_request: Request, exc: ValidationError) -> JSONResponse:
    """Convert Pydantic ValidationError into an INVALID_INPUT 400 response."""
    body = ErrorResponse(
        error=ErrorDetail(
            code=ErrorCode.INVALID_INPUT,
            message=str(exc),
            recoverable=False,
        ),
    )
    return JSONResponse(status_code=400, content=body.model_dump())


def _request_validation_error_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Convert FastAPI request validation errors into an INVALID_INPUT 400 response."""
    body = ErrorResponse(
        error=ErrorDetail(
            code=ErrorCode.INVALID_INPUT,
            message=str(exc),
            recoverable=False,
        ),
    )
    return JSONResponse(status_code=400, content=body.model_dump())


def register_error_handlers(app: FastAPI) -> None:
    """Attach exception handlers to the FastAPI application."""
    from pydantic import ValidationError

    app.add_exception_handler(CrawlerError, _crawler_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ValidationError, _validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _request_validation_error_handler)  # pyright: ignore[reportArgumentType]
