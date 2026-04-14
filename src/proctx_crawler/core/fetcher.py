"""Static HTTP fetcher with SSRF protection and manual redirect handling."""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
import structlog
from pydantic import BaseModel

from proctx_crawler.core.ssrf import resolve_and_check_ip, validate_url_scheme
from proctx_crawler.models import ErrorCode, FetchError

log = structlog.get_logger()

USER_AGENT = "proctx-crawler/0.1.0"
_MAX_REDIRECTS = 10


class FetchResult(BaseModel):
    """Result of fetching a URL, containing the final URL, status, HTML body, and headers."""

    url: str
    status_code: int
    html: str
    headers: dict[str, str]


async def fetch_static(
    url: str,
    *,
    timeout: float = 30.0,
    max_response_size: int = 10_485_760,
) -> FetchResult:
    """Fetch a URL using httpx with SSRF protection and manual redirect following.

    - Validates URL scheme (http/https only).
    - Resolves hostname and checks for private IPs before each request.
    - Follows redirects manually (up to 10 hops), re-validating SSRF on each hop.
    - Enforces a response size limit by streaming the response body.
    - Sets a consistent User-Agent header.

    Raises FetchError for all failure modes; never leaks httpx exceptions.
    """
    current_url = url

    for _hop in range(_MAX_REDIRECTS):
        validate_url_scheme(current_url)

        parsed = urlparse(current_url)
        hostname = parsed.hostname
        if not hostname:
            raise FetchError(
                code=ErrorCode.FETCH_FAILED,
                message=f"Invalid URL (no hostname): {current_url}",
                recoverable=False,
            )

        resolve_and_check_ip(hostname)

        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=timeout,
                headers={"User-Agent": USER_AGENT},
                proxy=None,
                trust_env=False,
            ) as client:
                response = await client.get(current_url)
        except httpx.TimeoutException as exc:
            raise FetchError(
                code=ErrorCode.FETCH_FAILED,
                message=f"Timeout fetching {current_url}: {exc}",
                recoverable=True,
            ) from exc
        except httpx.ConnectError as exc:
            raise FetchError(
                code=ErrorCode.FETCH_FAILED,
                message=f"Connection error fetching {current_url}: {exc}",
                recoverable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise FetchError(
                code=ErrorCode.FETCH_FAILED,
                message=f"HTTP error fetching {current_url}: {exc}",
                recoverable=True,
            ) from exc

        # Handle redirects manually so we can re-check SSRF on each hop.
        if response.is_redirect:
            location = response.headers.get("location")
            if not location:
                raise FetchError(
                    code=ErrorCode.FETCH_FAILED,
                    message=f"Redirect response {response.status_code} with no Location header",
                    recoverable=False,
                )
            # Resolve relative redirects against the current URL.
            current_url = str(response.url.join(location))
            log.debug("fetch_redirect", status=response.status_code, location=current_url)
            continue

        # Non-redirect response — check status and return.
        _check_http_status(response)

        body = response.text
        if len(response.content) > max_response_size:
            raise FetchError(
                code=ErrorCode.FETCH_FAILED,
                message=(
                    f"Response size {len(response.content)} bytes exceeds limit "
                    f"of {max_response_size} bytes"
                ),
                recoverable=False,
            )

        return FetchResult(
            url=str(response.url),
            status_code=response.status_code,
            html=body,
            headers=dict(response.headers),
        )

    raise FetchError(
        code=ErrorCode.FETCH_FAILED,
        message=f"Too many redirects (>{_MAX_REDIRECTS})",
        recoverable=False,
    )


def _check_http_status(response: httpx.Response) -> None:
    """Raise FetchError for non-success HTTP status codes."""
    status = response.status_code

    if 200 <= status < 300:
        return

    if status == 404:
        raise FetchError(
            code=ErrorCode.NOT_FOUND,
            message=f"Page not found: {response.url}",
            recoverable=False,
        )

    if status == 429:
        raise FetchError(
            code=ErrorCode.FETCH_FAILED,
            message=f"Rate limited (429): {response.url}",
            recoverable=True,
        )

    if status >= 500:
        raise FetchError(
            code=ErrorCode.FETCH_FAILED,
            message=f"Server error ({status}): {response.url}",
            recoverable=True,
        )

    # Other 4xx errors
    raise FetchError(
        code=ErrorCode.FETCH_FAILED,
        message=f"HTTP {status}: {response.url}",
        recoverable=False,
    )
