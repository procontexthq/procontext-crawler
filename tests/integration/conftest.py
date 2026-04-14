"""Shared fixtures for integration tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from proctx_crawler.core.fetcher import FetchResult
from proctx_crawler.crawler import Crawler
from proctx_crawler.models import ErrorCode, FetchError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pytest_mock import MockerFixture


def _build_html(
    title: str,
    body: str = "",
    links: list[str] | None = None,
) -> str:
    """Generate a minimal HTML page with optional links."""
    link_tags = ""
    if links:
        link_tags = "\n".join(f'<a href="{url}">{url}</a>' for url in links)
    return (
        f"<html><head><title>{title}</title></head>"
        f"<body><h1>{title}</h1>{body}{link_tags}</body></html>"
    )


@pytest.fixture
def sample_html() -> Callable[..., str]:
    """Return a helper function to generate HTML pages with titles, body content, and links."""
    return _build_html


@pytest.fixture
def mock_pages() -> dict[str, tuple[int, str]]:
    """A dict of URL -> (status_code, html_content) for use with mock fetcher.

    Provides a small site with interconnected pages for integration testing.
    """
    return {
        "https://docs.example.com": (
            200,
            _build_html(
                "Docs Home",
                body="<p>Welcome to the docs.</p>",
                links=[
                    "https://docs.example.com/getting-started",
                    "https://docs.example.com/api-reference",
                    "https://docs.example.com/guides",
                    "https://external.example.org/resource",
                ],
            ),
        ),
        "https://docs.example.com/getting-started": (
            200,
            _build_html(
                "Getting Started",
                body="<p>How to get started with our library.</p>",
                links=[
                    "https://docs.example.com",
                    "https://docs.example.com/api-reference",
                ],
            ),
        ),
        "https://docs.example.com/api-reference": (
            200,
            _build_html(
                "API Reference",
                body="<p>Full API documentation here.</p>",
                links=[
                    "https://docs.example.com",
                    "https://docs.example.com/getting-started",
                    "https://docs.example.com/guides",
                ],
            ),
        ),
        "https://docs.example.com/guides": (
            200,
            _build_html(
                "Guides",
                body="<p>In-depth guides for advanced usage.</p>",
                links=[
                    "https://docs.example.com",
                    "https://docs.example.com/guides/tutorial",
                ],
            ),
        ),
        "https://docs.example.com/guides/tutorial": (
            200,
            _build_html(
                "Tutorial",
                body="<p>Step by step tutorial.</p>",
            ),
        ),
        "https://external.example.org/resource": (
            200,
            _build_html("External Resource", body="<p>External content.</p>"),
        ),
    }


@pytest.fixture
def patch_fetcher(
    mocker: MockerFixture,
    mock_pages: dict[str, tuple[int, str]],
) -> dict[str, tuple[int, str]]:
    """Patch fetch_static across all modules that use it (engine, crawler, routes).

    Returns the mock_pages dict so tests can inspect or extend it.
    """

    async def _mock_fetch(url: str, **_kwargs: object) -> FetchResult:
        if url not in mock_pages:
            raise FetchError(
                code=ErrorCode.NOT_FOUND,
                message=f"Page not found: {url}",
                recoverable=False,
            )
        status_code, html = mock_pages[url]
        return FetchResult(url=url, status_code=status_code, html=html, headers={})

    mocker.patch("proctx_crawler.core.engine.fetch_static", side_effect=_mock_fetch)
    mocker.patch("proctx_crawler.crawler.fetch_static", side_effect=_mock_fetch)
    mocker.patch("proctx_crawler.api.routes.fetch_static", side_effect=_mock_fetch)

    return mock_pages


@pytest.fixture
async def tmp_crawler(tmp_path: Path) -> Crawler:
    """Return a Crawler instance configured with tmp_path for output_dir and db_path."""
    crawler = Crawler(
        output_dir=tmp_path / "output",
        db_path=tmp_path / "test.db",
    )
    return crawler
