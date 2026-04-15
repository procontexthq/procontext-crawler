"""Pure ASGI authentication middleware."""

from __future__ import annotations

import json
import secrets
from typing import TYPE_CHECKING

from proctx_crawler.models import ErrorCode, ErrorDetail, ErrorResponse

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send


class AuthMiddleware:
    """ASGI middleware that enforces ``Authorization: Bearer <key>`` when an API key is configured.

    Implemented as a pure ASGI wrapper (not ``BaseHTTPMiddleware``) to preserve
    streaming semantics for future SSE support.
    """

    def __init__(self, app: ASGIApp, *, api_key: str) -> None:
        self._app = app
        self._api_key = api_key

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        auth_value = headers.get(b"authorization", b"").decode()

        if secrets.compare_digest(auth_value, f"Bearer {self._api_key}"):
            await self._app(scope, receive, send)
            return

        body = ErrorResponse(
            error=ErrorDetail(
                code=ErrorCode.INVALID_INPUT,
                message="Missing or invalid Authorization header",
                recoverable=False,
            ),
        )
        payload = json.dumps(body.model_dump()).encode()

        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"content-length", str(len(payload)).encode()],
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": payload,
            }
        )
