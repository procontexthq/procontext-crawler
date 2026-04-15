"""Tests for the static HTTP fetcher with SSRF protection."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
import respx

from proctx_crawler.core.fetcher import USER_AGENT, FetchResult, fetch_static
from proctx_crawler.models import ErrorCode, FetchError


class _ExplodingAfterLimitStream(httpx.AsyncByteStream):
    """Async stream that would explode if the fetcher tried to read past the limit."""

    async def __aiter__(self):  # type: ignore[override]
        yield b"x" * 60
        yield b"y" * 60
        raise AssertionError("fetcher kept reading after size limit was exceeded")

    async def aclose(self) -> None:
        return None


def _mock_dns_public(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch resolve_and_check_ip to always succeed with a public IP."""
    monkeypatch.setattr(
        "proctx_crawler.core.fetcher.resolve_and_check_ip",
        lambda _hostname: "93.184.216.34",
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestFetchStaticSuccess:
    @pytest.mark.anyio
    @respx.mock
    async def test_200_returns_fetch_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_dns_public(monkeypatch)
        respx.get("http://example.com/page").mock(
            return_value=httpx.Response(200, html="<h1>Hello</h1>")
        )

        result = await fetch_static("http://example.com/page")

        assert isinstance(result, FetchResult)
        assert result.status_code == 200
        assert "<h1>Hello</h1>" in result.html
        assert result.url == "http://example.com/page"

    @pytest.mark.anyio
    @respx.mock
    async def test_user_agent_is_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_dns_public(monkeypatch)
        route = respx.get("http://example.com/").mock(return_value=httpx.Response(200, html="ok"))

        await fetch_static("http://example.com/")

        assert route.calls.last is not None
        assert route.calls.last.request.headers["user-agent"] == USER_AGENT


# ---------------------------------------------------------------------------
# HTTP error codes
# ---------------------------------------------------------------------------


class TestFetchStaticHttpErrors:
    @pytest.mark.anyio
    @respx.mock
    async def test_404_raises_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_dns_public(monkeypatch)
        respx.get("http://example.com/missing").mock(return_value=httpx.Response(404))

        with pytest.raises(FetchError) as exc_info:
            await fetch_static("http://example.com/missing")

        assert exc_info.value.code == ErrorCode.NOT_FOUND
        assert exc_info.value.recoverable is False

    @pytest.mark.anyio
    @respx.mock
    async def test_500_raises_fetch_failed_recoverable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_dns_public(monkeypatch)
        respx.get("http://example.com/error").mock(return_value=httpx.Response(500))

        with pytest.raises(FetchError) as exc_info:
            await fetch_static("http://example.com/error")

        assert exc_info.value.code == ErrorCode.FETCH_FAILED
        assert exc_info.value.recoverable is True

    @pytest.mark.anyio
    @respx.mock
    async def test_429_raises_fetch_failed_recoverable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_dns_public(monkeypatch)
        respx.get("http://example.com/rate-limited").mock(return_value=httpx.Response(429))

        with pytest.raises(FetchError) as exc_info:
            await fetch_static("http://example.com/rate-limited")

        assert exc_info.value.code == ErrorCode.FETCH_FAILED
        assert exc_info.value.recoverable is True

    @pytest.mark.anyio
    @respx.mock
    async def test_403_raises_not_recoverable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_dns_public(monkeypatch)
        respx.get("http://example.com/forbidden").mock(return_value=httpx.Response(403))

        with pytest.raises(FetchError) as exc_info:
            await fetch_static("http://example.com/forbidden")

        assert exc_info.value.code == ErrorCode.FETCH_FAILED
        assert exc_info.value.recoverable is False


# ---------------------------------------------------------------------------
# Redirects
# ---------------------------------------------------------------------------


class TestFetchStaticRedirects:
    @pytest.mark.anyio
    @respx.mock
    async def test_redirect_301_followed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_dns_public(monkeypatch)
        respx.get("http://example.com/old").mock(
            return_value=httpx.Response(301, headers={"location": "http://example.com/new"})
        )
        respx.get("http://example.com/new").mock(
            return_value=httpx.Response(200, html="<h1>New Page</h1>")
        )

        result = await fetch_static("http://example.com/old")

        assert result.status_code == 200
        assert result.url == "http://example.com/new"
        assert "New Page" in result.html

    @pytest.mark.anyio
    @respx.mock
    async def test_redirect_to_private_ip_blocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A redirect to a private IP should be blocked by SSRF checks."""
        call_count = 0

        def mock_resolve(hostname: str) -> str:
            nonlocal call_count
            call_count += 1
            if hostname == "evil.example.com":
                raise FetchError(
                    code=ErrorCode.FETCH_FAILED,
                    message=f"SSRF blocked: {hostname!r} resolves to private IP 127.0.0.1",
                    recoverable=False,
                )
            return "93.184.216.34"

        monkeypatch.setattr(
            "proctx_crawler.core.fetcher.resolve_and_check_ip",
            mock_resolve,
        )

        respx.get("http://example.com/redirect").mock(
            return_value=httpx.Response(
                301, headers={"location": "http://evil.example.com/internal"}
            )
        )

        with pytest.raises(FetchError, match="SSRF blocked"):
            await fetch_static("http://example.com/redirect")


# ---------------------------------------------------------------------------
# Response size limit
# ---------------------------------------------------------------------------


class TestFetchStaticResponseSize:
    @pytest.mark.anyio
    @respx.mock
    async def test_response_exceeding_limit_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_dns_public(monkeypatch)
        large_body = "x" * 1000
        respx.get("http://example.com/large").mock(
            return_value=httpx.Response(200, html=large_body)
        )

        with pytest.raises(FetchError, match="Response size"):
            await fetch_static("http://example.com/large", max_response_size=100)

    @pytest.mark.anyio
    @respx.mock
    async def test_response_limit_is_enforced_while_streaming(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_dns_public(monkeypatch)
        respx.get("http://example.com/streaming-large").mock(
            return_value=httpx.Response(200, stream=_ExplodingAfterLimitStream())
        )

        with pytest.raises(FetchError, match="Response size"):
            await fetch_static("http://example.com/streaming-large", max_response_size=100)


# ---------------------------------------------------------------------------
# Network errors
# ---------------------------------------------------------------------------


class TestFetchStaticNetworkErrors:
    @pytest.mark.anyio
    @respx.mock
    async def test_timeout_raises_recoverable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_dns_public(monkeypatch)
        respx.get("http://example.com/slow").mock(side_effect=httpx.ReadTimeout("Read timed out"))

        with pytest.raises(FetchError) as exc_info:
            await fetch_static("http://example.com/slow")

        assert exc_info.value.recoverable is True

    @pytest.mark.anyio
    @respx.mock
    async def test_connection_error_raises_recoverable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_dns_public(monkeypatch)
        respx.get("http://example.com/down").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        with pytest.raises(FetchError) as exc_info:
            await fetch_static("http://example.com/down")

        assert exc_info.value.recoverable is True


# ---------------------------------------------------------------------------
# SSRF via DNS
# ---------------------------------------------------------------------------


class TestFetchStaticSsrf:
    @pytest.mark.anyio
    async def test_private_ip_blocked_via_dns(self) -> None:
        """Fetching a URL that resolves to a private IP is blocked."""
        with patch("proctx_crawler.core.fetcher.resolve_and_check_ip") as mock_resolve:
            mock_resolve.side_effect = FetchError(
                code=ErrorCode.FETCH_FAILED,
                message="SSRF blocked: resolves to private IP 10.0.0.1",
                recoverable=False,
            )

            with pytest.raises(FetchError, match="SSRF blocked"):
                await fetch_static("http://internal.example.com/")

    @pytest.mark.anyio
    async def test_disallowed_scheme_blocked(self) -> None:
        with pytest.raises(Exception, match="Disallowed URL scheme"):
            await fetch_static("file:///etc/passwd")


# ---------------------------------------------------------------------------
# No-hostname URL
# ---------------------------------------------------------------------------


class TestFetchStaticNoHostname:
    @pytest.mark.anyio
    async def test_url_without_hostname_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A URL with no hostname (e.g. http://:8080/) should raise FetchError."""
        _mock_dns_public(monkeypatch)

        with pytest.raises(FetchError, match="no hostname"):
            await fetch_static("http://:8080/path")


# ---------------------------------------------------------------------------
# Generic httpx.HTTPError
# ---------------------------------------------------------------------------


class TestFetchStaticGenericHttpError:
    @pytest.mark.anyio
    @respx.mock
    async def test_generic_http_error_raises_recoverable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An httpx.HTTPError that is not a timeout or connect error is still caught."""
        _mock_dns_public(monkeypatch)
        respx.get("http://example.com/broken").mock(
            side_effect=httpx.DecodingError("Decoding failed")
        )

        with pytest.raises(FetchError) as exc_info:
            await fetch_static("http://example.com/broken")

        assert exc_info.value.code == ErrorCode.FETCH_FAILED
        assert exc_info.value.recoverable is True


# ---------------------------------------------------------------------------
# Redirect edge cases
# ---------------------------------------------------------------------------


class TestFetchStaticRedirectEdgeCases:
    @pytest.mark.anyio
    @respx.mock
    async def test_redirect_without_location_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A redirect response with no Location header should raise FetchError."""
        _mock_dns_public(monkeypatch)
        respx.get("http://example.com/no-location").mock(
            return_value=httpx.Response(301, headers={})
        )

        with pytest.raises(FetchError, match="no Location header"):
            await fetch_static("http://example.com/no-location")

    @pytest.mark.anyio
    @respx.mock
    async def test_too_many_redirects(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """More than 10 redirect hops should raise FetchError."""
        _mock_dns_public(monkeypatch)
        for i in range(11):
            respx.get(f"http://example.com/hop{i}").mock(
                return_value=httpx.Response(
                    301, headers={"location": f"http://example.com/hop{i + 1}"}
                )
            )

        with pytest.raises(FetchError, match="Too many redirects"):
            await fetch_static("http://example.com/hop0")
