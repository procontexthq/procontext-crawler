"""Tests for the shared single-page fetch service."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from proctx_crawler.core.fetcher import FetchResult
from proctx_crawler.core.page_service import fetch_page_html
from proctx_crawler.models import GotoOptions

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


class TestFetchPageHtml:
    """fetch_page_html dispatches to fetch_static or fetch_rendered."""

    @pytest.mark.anyio
    async def test_static_path_ignores_browser_pool(self, mocker: MockerFixture) -> None:
        mock_result = FetchResult(
            url="https://example.com", status_code=200, html="<html></html>", headers={}
        )
        mock_static = mocker.patch(
            "proctx_crawler.core.page_service.fetch_static", return_value=mock_result
        )
        mock_rendered = mocker.patch("proctx_crawler.core.page_service.fetch_rendered")

        result = await fetch_page_html("https://example.com", render=False, browser_pool=None)

        assert result is mock_result
        mock_static.assert_awaited_once_with("https://example.com", max_response_size=10_485_760)
        mock_rendered.assert_not_called()

    @pytest.mark.anyio
    async def test_static_path_passes_max_response_size(self, mocker: MockerFixture) -> None:
        mock_result = FetchResult(
            url="https://example.com", status_code=200, html="<html></html>", headers={}
        )
        mock_static = mocker.patch(
            "proctx_crawler.core.page_service.fetch_static", return_value=mock_result
        )

        await fetch_page_html(
            "https://example.com",
            render=False,
            browser_pool=None,
            max_response_size=2048,
        )

        mock_static.assert_awaited_once_with("https://example.com", max_response_size=2048)

    @pytest.mark.anyio
    async def test_rendered_path_passes_options_through(self, mocker: MockerFixture) -> None:
        mock_result = FetchResult(
            url="https://example.com", status_code=200, html="<html></html>", headers={}
        )
        mock_rendered = mocker.patch(
            "proctx_crawler.core.page_service.fetch_rendered", return_value=mock_result
        )
        mock_static = mocker.patch("proctx_crawler.core.page_service.fetch_static")
        pool = MagicMock()
        goto = GotoOptions(wait_until="load")

        result = await fetch_page_html(
            "https://example.com",
            render=True,
            browser_pool=pool,
            goto_options=goto,
            wait_for_selector="main",
            reject_resource_types=["image"],
        )

        assert result is mock_result
        mock_rendered.assert_awaited_once_with(
            "https://example.com",
            pool,
            goto_options=goto,
            wait_for_selector="main",
            reject_resource_types=["image"],
        )
        mock_static.assert_not_called()

    @pytest.mark.anyio
    async def test_rendered_without_pool_raises(self) -> None:
        with pytest.raises(RuntimeError, match="browser_pool is required"):
            await fetch_page_html("https://example.com", render=True, browser_pool=None)
