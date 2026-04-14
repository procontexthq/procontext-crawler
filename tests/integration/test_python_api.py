"""Integration tests for the Crawler Python API.

These tests exercise the full Crawler -> engine -> fetcher pipeline with
mocked HTTP calls. They verify the public contracts defined in the specs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import anyio
import pytest

from proctx_crawler.crawler import Crawler
from proctx_crawler.models import FetchError, JobStatus, UrlStatus

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pytest_mock import MockerFixture


# ---------------------------------------------------------------------------
# Full crawl lifecycle
# ---------------------------------------------------------------------------


class TestFullCrawlLifecycle:
    """Verify the complete crawl workflow from start to finish."""

    @pytest.mark.anyio
    async def test_crawl_returns_completed_result(
        self, tmp_path: Path, patch_fetcher: dict[str, tuple[int, str]]
    ) -> None:
        """Crawl a small site and verify CrawlResult has correct status, records,
        and markdown content."""
        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with anyio.fail_after(10):
                result = await crawler.crawl(
                    "https://docs.example.com",
                    limit=10,
                    depth=2,
                )

        assert result.status == JobStatus.COMPLETED
        assert result.id is not None
        assert result.finished >= 1
        assert len(result.records) >= 1

        completed = [r for r in result.records if r.status == UrlStatus.COMPLETED]
        assert len(completed) >= 1

        for rec in completed:
            assert rec.markdown is not None
            assert rec.metadata is not None
            assert rec.metadata.http_status == 200

    @pytest.mark.anyio
    async def test_crawl_discovers_linked_pages(
        self, tmp_path: Path, patch_fetcher: dict[str, tuple[int, str]]
    ) -> None:
        """Crawl with sufficient depth and limit to discover multiple linked pages."""
        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with anyio.fail_after(10):
                result = await crawler.crawl(
                    "https://docs.example.com",
                    limit=10,
                    depth=1,
                )

        completed_urls = {r.url for r in result.records if r.status == UrlStatus.COMPLETED}
        # The starting page + at least some of the linked pages should be crawled
        assert "https://docs.example.com" in completed_urls
        assert len(completed_urls) >= 2


# ---------------------------------------------------------------------------
# Depth limit
# ---------------------------------------------------------------------------


class TestDepthLimit:
    """Verify depth limiting constrains the crawl."""

    @pytest.mark.anyio
    async def test_depth_zero_only_crawls_start_url(
        self, tmp_path: Path, patch_fetcher: dict[str, tuple[int, str]]
    ) -> None:
        """With depth=0, only the starting URL is crawled; no discovered links
        should be followed."""
        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with anyio.fail_after(10):
                result = await crawler.crawl(
                    "https://docs.example.com",
                    limit=100,
                    depth=0,
                )

        completed = [r for r in result.records if r.status == UrlStatus.COMPLETED]
        assert len(completed) == 1
        assert completed[0].url == "https://docs.example.com"


# ---------------------------------------------------------------------------
# Page limit
# ---------------------------------------------------------------------------


class TestPageLimit:
    """Verify page limit truncates the crawl."""

    @pytest.mark.anyio
    async def test_limit_restricts_pages_crawled(
        self, tmp_path: Path, patch_fetcher: dict[str, tuple[int, str]]
    ) -> None:
        """Setting limit=2 should crawl at most 2 pages even if more are discovered."""
        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with anyio.fail_after(10):
                result = await crawler.crawl(
                    "https://docs.example.com",
                    limit=2,
                    depth=10,
                )

        completed = [r for r in result.records if r.status == UrlStatus.COMPLETED]
        assert len(completed) == 2


# ---------------------------------------------------------------------------
# Include/Exclude patterns
# ---------------------------------------------------------------------------


class TestUrlPatterns:
    """Verify URL filtering with include/exclude patterns works."""

    @pytest.mark.anyio
    async def test_include_pattern_filters_urls(
        self, tmp_path: Path, patch_fetcher: dict[str, tuple[int, str]]
    ) -> None:
        """Only URLs matching include patterns should be discovered and crawled."""
        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with anyio.fail_after(10):
                result = await crawler.crawl(
                    "https://docs.example.com",
                    limit=10,
                    depth=2,
                    options={"include_patterns": ["**/guides/**"]},
                )

        completed_urls = {r.url for r in result.records if r.status == UrlStatus.COMPLETED}
        # The start URL is always crawled; discovered links must match the pattern.
        assert "https://docs.example.com" in completed_urls
        # Links not matching **/guides/** should not be crawled
        assert "https://docs.example.com/getting-started" not in completed_urls
        assert "https://docs.example.com/api-reference" not in completed_urls

    @pytest.mark.anyio
    async def test_exclude_pattern_filters_urls(
        self, tmp_path: Path, patch_fetcher: dict[str, tuple[int, str]]
    ) -> None:
        """URLs matching exclude patterns should not be crawled."""
        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with anyio.fail_after(10):
                result = await crawler.crawl(
                    "https://docs.example.com",
                    limit=10,
                    depth=2,
                    # Pattern **/getting-started matches URLs ending with /getting-started
                    options={"exclude_patterns": ["**/getting-started"]},
                )

        completed_urls = {r.url for r in result.records if r.status == UrlStatus.COMPLETED}
        assert "https://docs.example.com" in completed_urls
        # getting-started should be excluded by the pattern
        assert "https://docs.example.com/getting-started" not in completed_urls
        # Other pages should still be crawled
        assert "https://docs.example.com/api-reference" in completed_urls


# ---------------------------------------------------------------------------
# llms_txt source
# ---------------------------------------------------------------------------


class TestLlmsTxtSource:
    """Verify crawl with llms_txt source mode."""

    @pytest.mark.anyio
    async def test_llms_txt_crawls_listed_urls(
        self,
        tmp_path: Path,
        mocker: MockerFixture,
        sample_html: Callable[..., str],
    ) -> None:
        """When source=llms_txt, the starting URL content is parsed for URLs,
        and those URLs are crawled instead of discovered links."""
        from proctx_crawler.core.fetcher import FetchResult
        from proctx_crawler.models import ErrorCode, FetchError

        llms_txt_content = (
            "# Documentation\n\n"
            "- [Getting Started](https://docs.example.com/getting-started)\n"
            "- [API Ref](https://docs.example.com/api-reference)\n"
        )
        pages: dict[str, tuple[int, str]] = {
            "https://docs.example.com/llms.txt": (200, llms_txt_content),
            "https://docs.example.com/getting-started": (
                200,
                sample_html("Getting Started", body="<p>How to get started.</p>"),
            ),
            "https://docs.example.com/api-reference": (
                200,
                sample_html("API Ref", body="<p>Full API docs.</p>"),
            ),
        }

        async def _mock_fetch(url: str, **_kwargs: object) -> FetchResult:
            if url not in pages:
                raise FetchError(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Page not found: {url}",
                    recoverable=False,
                )
            status_code, html = pages[url]
            return FetchResult(url=url, status_code=status_code, html=html, headers={})

        mocker.patch("proctx_crawler.core.engine.fetch_static", side_effect=_mock_fetch)
        mocker.patch("proctx_crawler.crawler.fetch_static", side_effect=_mock_fetch)

        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with anyio.fail_after(10):
                result = await crawler.crawl(
                    "https://docs.example.com/llms.txt",
                    limit=10,
                    source="llms_txt",
                )

        assert result.status == JobStatus.COMPLETED
        completed_urls = {r.url for r in result.records if r.status == UrlStatus.COMPLETED}
        assert "https://docs.example.com/getting-started" in completed_urls
        assert "https://docs.example.com/api-reference" in completed_urls


# ---------------------------------------------------------------------------
# Single-page methods
# ---------------------------------------------------------------------------


class TestSinglePageMarkdown:
    """Verify Crawler.markdown() returns markdown string."""

    @pytest.mark.anyio
    async def test_markdown_extracts_content(
        self, tmp_path: Path, patch_fetcher: dict[str, tuple[int, str]]
    ) -> None:
        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with anyio.fail_after(5):
                md = await crawler.markdown("https://docs.example.com")

        assert isinstance(md, str)
        assert "Docs Home" in md
        assert "Welcome to the docs" in md


class TestSinglePageContent:
    """Verify Crawler.content() returns HTML string."""

    @pytest.mark.anyio
    async def test_content_returns_html(
        self, tmp_path: Path, patch_fetcher: dict[str, tuple[int, str]]
    ) -> None:
        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with anyio.fail_after(5):
                html = await crawler.content("https://docs.example.com")

        assert isinstance(html, str)
        assert "<html>" in html
        assert "Welcome to the docs" in html


class TestSinglePageLinks:
    """Verify Crawler.links() returns a list of URLs."""

    @pytest.mark.anyio
    async def test_links_returns_all_links(
        self, tmp_path: Path, patch_fetcher: dict[str, tuple[int, str]]
    ) -> None:
        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with anyio.fail_after(5):
                urls = await crawler.links("https://docs.example.com")

        assert isinstance(urls, list)
        assert "https://docs.example.com/getting-started" in urls
        assert "https://docs.example.com/api-reference" in urls
        assert "https://docs.example.com/guides" in urls
        # External link should also be present by default
        assert "https://external.example.org/resource" in urls

    @pytest.mark.anyio
    async def test_links_exclude_external(
        self, tmp_path: Path, patch_fetcher: dict[str, tuple[int, str]]
    ) -> None:
        """exclude_external_links=True should filter out external links."""
        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with anyio.fail_after(5):
                urls = await crawler.links(
                    "https://docs.example.com",
                    exclude_external_links=True,
                )

        assert "https://docs.example.com/getting-started" in urls
        assert "https://docs.example.com/api-reference" in urls
        # External link should be filtered out
        assert "https://external.example.org/resource" not in urls


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    """Verify FetchError propagates from single-page methods when the URL fails."""

    @pytest.mark.anyio
    async def test_markdown_propagates_fetch_error(
        self, tmp_path: Path, patch_fetcher: dict[str, tuple[int, str]]
    ) -> None:
        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with pytest.raises(FetchError, match="Page not found"):
                await crawler.markdown("https://docs.example.com/nonexistent")

    @pytest.mark.anyio
    async def test_content_propagates_fetch_error(
        self, tmp_path: Path, patch_fetcher: dict[str, tuple[int, str]]
    ) -> None:
        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with pytest.raises(FetchError, match="Page not found"):
                await crawler.content("https://docs.example.com/nonexistent")

    @pytest.mark.anyio
    async def test_links_propagates_fetch_error(
        self, tmp_path: Path, patch_fetcher: dict[str, tuple[int, str]]
    ) -> None:
        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with pytest.raises(FetchError, match="Page not found"):
                await crawler.links("https://docs.example.com/nonexistent")
