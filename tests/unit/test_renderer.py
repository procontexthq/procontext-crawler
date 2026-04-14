"""Tests for the Playwright-based page renderer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from proctx_crawler.core.fetcher import FetchResult
from proctx_crawler.core.renderer import fetch_rendered
from proctx_crawler.models import ErrorCode, GotoOptions, RenderError


def _make_mock_pool(
    *,
    html: str = "<html><body>rendered</body></html>",
    page_url: str = "http://example.com/page",
    status: int = 200,
) -> MagicMock:
    """Create a mock BrowserPool that returns a mock page with the given content."""
    mock_response = MagicMock()
    mock_response.status = status

    mock_page = AsyncMock()
    mock_page.goto = AsyncMock(return_value=mock_response)
    mock_page.content = AsyncMock(return_value=html)
    mock_page.url = page_url
    mock_page.route = AsyncMock()
    mock_page.wait_for_selector = AsyncMock()

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.close = AsyncMock()

    mock_pool = MagicMock()

    # Make acquire_context an async context manager.
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_context)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    mock_pool.acquire_context = MagicMock(return_value=mock_cm)

    return mock_pool


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestFetchRenderedSuccess:
    @pytest.mark.anyio
    async def test_returns_fetch_result(self) -> None:
        pool = _make_mock_pool()

        result = await fetch_rendered("http://example.com/page", pool)

        assert isinstance(result, FetchResult)
        assert result.html == "<html><body>rendered</body></html>"
        assert result.url == "http://example.com/page"
        assert result.status_code == 200

    @pytest.mark.anyio
    async def test_status_from_response(self) -> None:
        pool = _make_mock_pool(status=301)

        result = await fetch_rendered("http://example.com/redirect", pool)

        assert result.status_code == 301


# ---------------------------------------------------------------------------
# Resource blocking
# ---------------------------------------------------------------------------


class TestFetchRenderedResourceBlocking:
    @pytest.mark.anyio
    async def test_route_set_when_reject_types_provided(self) -> None:
        pool = _make_mock_pool()

        await fetch_rendered(
            "http://example.com/page",
            pool,
            reject_resource_types=["image", "font"],
        )

        # Get the mock page through the context.
        mock_cm = pool.acquire_context()
        mock_context = await mock_cm.__aenter__()
        mock_page = await mock_context.new_page()
        mock_page.route.assert_awaited()

    @pytest.mark.anyio
    async def test_no_route_when_no_reject_types(self) -> None:
        """When reject_resource_types is not provided, page.route should not be called."""
        mock_response = MagicMock()
        mock_response.status = 200

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock(return_value=mock_response)
        mock_page.content = AsyncMock(return_value="<html></html>")
        mock_page.url = "http://example.com/page"
        mock_page.route = AsyncMock()

        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_context.close = AsyncMock()

        mock_pool = MagicMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_context)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_pool.acquire_context = MagicMock(return_value=mock_cm)

        await fetch_rendered("http://example.com/page", mock_pool)

        mock_page.route.assert_not_awaited()

    @pytest.mark.anyio
    async def test_resource_blocker_blocks_matching_types(self) -> None:
        """Test the _make_resource_blocker function directly."""
        from proctx_crawler.core.renderer import _make_resource_blocker

        blocker = _make_resource_blocker(["image", "font"])

        mock_route = AsyncMock()
        mock_route.request.resource_type = "image"
        await blocker(mock_route)
        mock_route.abort.assert_awaited_once()

    @pytest.mark.anyio
    async def test_resource_blocker_allows_non_matching_types(self) -> None:
        from proctx_crawler.core.renderer import _make_resource_blocker

        blocker = _make_resource_blocker(["image", "font"])

        mock_route = AsyncMock()
        mock_route.request.resource_type = "document"
        await blocker(mock_route)
        mock_route.continue_.assert_awaited_once()


# ---------------------------------------------------------------------------
# wait_for_selector
# ---------------------------------------------------------------------------


class TestFetchRenderedWaitForSelector:
    @pytest.mark.anyio
    async def test_wait_for_selector_called(self) -> None:
        pool = _make_mock_pool()

        await fetch_rendered(
            "http://example.com/page",
            pool,
            wait_for_selector="#content",
        )

        mock_cm = pool.acquire_context()
        mock_context = await mock_cm.__aenter__()
        mock_page = await mock_context.new_page()
        mock_page.wait_for_selector.assert_awaited()


# ---------------------------------------------------------------------------
# goto_options
# ---------------------------------------------------------------------------


class TestFetchRenderedGotoOptions:
    @pytest.mark.anyio
    async def test_custom_goto_options_passed(self) -> None:
        pool = _make_mock_pool()
        opts = GotoOptions(wait_until="domcontentloaded", timeout=60000)

        await fetch_rendered(
            "http://example.com/page",
            pool,
            goto_options=opts,
        )

        mock_cm = pool.acquire_context()
        mock_context = await mock_cm.__aenter__()
        mock_page = await mock_context.new_page()
        mock_page.goto.assert_awaited()
        # Check the arguments passed to goto.
        call_kwargs = mock_page.goto.call_args
        assert call_kwargs.kwargs.get("wait_until") == "domcontentloaded" or (
            call_kwargs.args[1:] and "domcontentloaded" in call_kwargs.args
        )

    @pytest.mark.anyio
    async def test_default_goto_options(self) -> None:
        pool = _make_mock_pool()

        await fetch_rendered("http://example.com/page", pool)

        mock_cm = pool.acquire_context()
        mock_context = await mock_cm.__aenter__()
        mock_page = await mock_context.new_page()
        call_kwargs = mock_page.goto.call_args
        assert call_kwargs.kwargs.get("wait_until") == "load"
        assert call_kwargs.kwargs.get("timeout") == 30000


# ---------------------------------------------------------------------------
# Error wrapping
# ---------------------------------------------------------------------------


class TestFetchRenderedErrors:
    @pytest.mark.anyio
    async def test_playwright_error_wrapped_as_render_error(self) -> None:
        pool = _make_mock_pool()

        # Make page.goto raise a generic exception (simulating a Playwright error).
        mock_cm = pool.acquire_context()
        mock_context = await mock_cm.__aenter__()
        mock_page = await mock_context.new_page()
        mock_page.goto = AsyncMock(side_effect=Exception("Navigation timeout exceeded"))

        with pytest.raises(RenderError) as exc_info:
            await fetch_rendered("http://example.com/page", pool)

        assert exc_info.value.code == ErrorCode.RENDER_FAILED
        assert "Navigation timeout exceeded" in exc_info.value.message
        assert exc_info.value.recoverable is True

    @pytest.mark.anyio
    async def test_render_error_not_double_wrapped(self) -> None:
        """If a RenderError is raised internally, it should not be wrapped again."""
        pool = _make_mock_pool()

        original_error = RenderError(
            code=ErrorCode.RENDER_FAILED,
            message="Original error",
            recoverable=False,
        )

        mock_cm = pool.acquire_context()
        mock_context = await mock_cm.__aenter__()
        mock_page = await mock_context.new_page()
        mock_page.goto = AsyncMock(side_effect=original_error)

        with pytest.raises(RenderError) as exc_info:
            await fetch_rendered("http://example.com/page", pool)

        assert exc_info.value is original_error
        assert exc_info.value.message == "Original error"
