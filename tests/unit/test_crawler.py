"""Tests for the Crawler public Python API."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import anyio
import pytest

from proctx_crawler.core.fetcher import FetchResult
from proctx_crawler.crawler import Crawler
from proctx_crawler.models import (
    ErrorCode,
    FetchError,
    JobStatus,
    RenderError,
    UrlStatus,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _html(title: str, body: str = "", links: list[str] | None = None) -> str:
    """Build a minimal HTML page with optional links."""
    link_tags = ""
    if links:
        link_tags = "\n".join(f'<a href="{url}">{url}</a>' for url in links)
    return f"<html><head><title>{title}</title></head><body>{body}{link_tags}</body></html>"


def _patch_fetcher(mocker: MockerFixture, pages: dict[str, tuple[int, str]]) -> None:
    """Patch fetch_static used by the engine and by the Crawler single-page methods."""

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


# ---------------------------------------------------------------------------
# Context manager lifecycle
# ---------------------------------------------------------------------------


class TestContextManager:
    """__aenter__ initialises repo and storage; __aexit__ closes them."""

    @pytest.mark.anyio
    async def test_enter_creates_repo_and_storage(self, tmp_path: Path) -> None:
        crawler = Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db")
        async with crawler:
            assert crawler._repo is not None
            assert crawler._storage is not None

    @pytest.mark.anyio
    async def test_exit_cleans_up(self, tmp_path: Path) -> None:
        crawler = Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db")
        async with crawler:
            pass
        assert crawler._repo is None
        assert crawler._storage is None

    @pytest.mark.anyio
    async def test_exit_stops_browser_pool_if_started(self, tmp_path: Path) -> None:
        crawler = Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db")
        async with crawler:
            # Simulate a started browser pool
            mock_pool = AsyncMock()
            crawler._browser_pool = mock_pool
        mock_pool.stop.assert_awaited_once()
        assert crawler._browser_pool is None

    @pytest.mark.anyio
    async def test_exit_without_browser_pool(self, tmp_path: Path) -> None:
        """Exiting without a browser pool should not raise."""
        crawler = Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db")
        async with crawler:
            assert crawler._browser_pool is None
        # No error is the assertion here

    @pytest.mark.anyio
    async def test_methods_require_context_manager(self, tmp_path: Path) -> None:
        """Calling methods without entering the context manager raises RuntimeError."""
        crawler = Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db")
        with pytest.raises(RuntimeError, match="async context manager"):
            await crawler.crawl("https://example.com")


# ---------------------------------------------------------------------------
# crawl() method
# ---------------------------------------------------------------------------


class TestCrawl:
    """crawl() creates a job, runs the engine, and returns CrawlResult."""

    @pytest.mark.anyio
    async def test_basic_crawl_returns_result(self, tmp_path: Path, mocker: MockerFixture) -> None:
        pages = {
            "https://example.com": (
                200,
                _html("Home", links=["https://example.com/page1"]),
            ),
            "https://example.com/page1": (200, _html("Page 1")),
        }
        _patch_fetcher(mocker, pages)

        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with anyio.fail_after(10):
                result = await crawler.crawl("https://example.com", limit=10, depth=1)

        assert result.status == JobStatus.COMPLETED
        assert result.finished == 2
        assert len(result.records) == 2
        assert result.cursor is None

        # At least one record should have markdown content
        completed = [r for r in result.records if r.status == UrlStatus.COMPLETED]
        assert len(completed) == 2
        for rec in completed:
            assert rec.markdown is not None
            assert rec.metadata is not None
            assert rec.metadata.http_status == 200

    @pytest.mark.anyio
    async def test_crawl_with_options(self, tmp_path: Path, mocker: MockerFixture) -> None:
        pages = {
            "https://example.com/docs/start": (
                200,
                _html(
                    "Docs",
                    links=["https://example.com/docs/page1", "https://example.com/blog/post"],
                ),
            ),
            "https://example.com/docs/page1": (200, _html("Doc Page 1")),
            "https://example.com/blog/post": (200, _html("Blog Post")),
        }
        _patch_fetcher(mocker, pages)

        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with anyio.fail_after(10):
                result = await crawler.crawl(
                    "https://example.com/docs/start",
                    limit=10,
                    depth=1,
                    options={"include_patterns": ["**/docs/**"]},
                )

        completed = [r for r in result.records if r.status == UrlStatus.COMPLETED]
        completed_urls = {r.url for r in completed}
        assert "https://example.com/docs/start" in completed_urls
        assert "https://example.com/docs/page1" in completed_urls
        assert "https://example.com/blog/post" not in completed_urls

    @pytest.mark.anyio
    async def test_crawl_html_format(self, tmp_path: Path, mocker: MockerFixture) -> None:
        pages = {
            "https://example.com": (200, _html("Home")),
        }
        _patch_fetcher(mocker, pages)

        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with anyio.fail_after(10):
                result = await crawler.crawl(
                    "https://example.com",
                    limit=1,
                    formats=["html"],
                )

        completed = [r for r in result.records if r.status == UrlStatus.COMPLETED]
        assert len(completed) == 1
        assert completed[0].html is not None
        assert completed[0].markdown is None

    @pytest.mark.anyio
    async def test_crawl_defaults_to_markdown_format(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        pages = {"https://example.com": (200, _html("Home"))}
        _patch_fetcher(mocker, pages)

        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with anyio.fail_after(10):
                result = await crawler.crawl("https://example.com", limit=1)

        completed = [r for r in result.records if r.status == UrlStatus.COMPLETED]
        assert len(completed) == 1
        assert completed[0].markdown is not None
        assert completed[0].html is None


# ---------------------------------------------------------------------------
# markdown() method
# ---------------------------------------------------------------------------


class TestMarkdown:
    @pytest.mark.anyio
    async def test_markdown_returns_string(self, tmp_path: Path, mocker: MockerFixture) -> None:
        html = _html("My Page", body="<p>Hello world</p>")
        _patch_fetcher(mocker, {"https://example.com": (200, html)})

        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with anyio.fail_after(5):
                md = await crawler.markdown("https://example.com")

        assert isinstance(md, str)
        assert "Hello world" in md

    @pytest.mark.anyio
    async def test_markdown_with_fetch_error(self, tmp_path: Path, mocker: MockerFixture) -> None:
        _patch_fetcher(mocker, {})

        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with pytest.raises(FetchError):
                await crawler.markdown("https://example.com/missing")


# ---------------------------------------------------------------------------
# content() method
# ---------------------------------------------------------------------------


class TestContent:
    @pytest.mark.anyio
    async def test_content_returns_html(self, tmp_path: Path, mocker: MockerFixture) -> None:
        html = _html("My Page", body="<p>Hello</p>")
        _patch_fetcher(mocker, {"https://example.com": (200, html)})

        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with anyio.fail_after(5):
                result = await crawler.content("https://example.com")

        assert isinstance(result, str)
        assert "<html>" in result
        assert "<p>Hello</p>" in result


# ---------------------------------------------------------------------------
# links() method
# ---------------------------------------------------------------------------


class TestLinks:
    @pytest.mark.anyio
    async def test_links_returns_urls(self, tmp_path: Path, mocker: MockerFixture) -> None:
        html = _html(
            "Home",
            links=[
                "https://example.com/page1",
                "https://example.com/page2",
                "https://external.com/page",
            ],
        )
        _patch_fetcher(mocker, {"https://example.com": (200, html)})

        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with anyio.fail_after(5):
                urls = await crawler.links("https://example.com")

        assert "https://example.com/page1" in urls
        assert "https://example.com/page2" in urls
        assert "https://external.com/page" in urls

    @pytest.mark.anyio
    async def test_links_exclude_external(self, tmp_path: Path, mocker: MockerFixture) -> None:
        html = _html(
            "Home",
            links=[
                "https://example.com/page1",
                "https://external.com/page",
                "https://another.org/page",
            ],
        )
        _patch_fetcher(mocker, {"https://example.com": (200, html)})

        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with anyio.fail_after(5):
                urls = await crawler.links("https://example.com", exclude_external_links=True)

        assert "https://example.com/page1" in urls
        assert "https://external.com/page" not in urls
        assert "https://another.org/page" not in urls

    @pytest.mark.anyio
    async def test_links_with_fetch_error(self, tmp_path: Path, mocker: MockerFixture) -> None:
        _patch_fetcher(mocker, {})

        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with pytest.raises(FetchError):
                await crawler.links("https://example.com/missing")


# ---------------------------------------------------------------------------
# Browser pool (render=True)
# ---------------------------------------------------------------------------


class TestBrowserPool:
    @pytest.mark.anyio
    async def test_render_triggers_browser_pool(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        """render=True should cause the browser pool to be lazily created."""
        html = _html("Rendered", body="<p>JS content</p>")
        mock_result = FetchResult(url="https://example.com", status_code=200, html=html, headers={})

        mock_pool_instance = AsyncMock()
        mock_pool_cls = mocker.patch(
            "proctx_crawler.crawler.BrowserPool", return_value=mock_pool_instance
        )
        mocker.patch("proctx_crawler.crawler.fetch_rendered", return_value=mock_result)

        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with anyio.fail_after(5):
                md = await crawler.markdown("https://example.com", render=True)

        mock_pool_cls.assert_called_once()
        mock_pool_instance.start.assert_awaited_once()
        assert "JS content" in md

    @pytest.mark.anyio
    async def test_browser_pool_reuse(self, tmp_path: Path, mocker: MockerFixture) -> None:
        """Second render call should reuse the same browser pool."""
        html = _html("Page", body="<p>Content</p>")
        mock_result = FetchResult(url="https://example.com", status_code=200, html=html, headers={})

        mock_pool_instance = AsyncMock()
        mock_pool_cls = mocker.patch(
            "proctx_crawler.crawler.BrowserPool", return_value=mock_pool_instance
        )
        mocker.patch("proctx_crawler.crawler.fetch_rendered", return_value=mock_result)

        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with anyio.fail_after(5):
                await crawler.markdown("https://example.com", render=True)
                await crawler.content("https://example.com", render=True)

        # Pool constructor called once, start called once
        mock_pool_cls.assert_called_once()
        mock_pool_instance.start.assert_awaited_once()

    @pytest.mark.anyio
    async def test_no_browser_pool_without_render(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        """When render=False, no browser pool is created."""
        html = _html("Static Page")
        _patch_fetcher(mocker, {"https://example.com": (200, html)})

        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with anyio.fail_after(5):
                await crawler.markdown("https://example.com")
            assert crawler._browser_pool is None


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    @pytest.mark.anyio
    async def test_fetch_error_propagates(self, tmp_path: Path, mocker: MockerFixture) -> None:
        _patch_fetcher(mocker, {})

        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with pytest.raises(FetchError) as exc_info:
                await crawler.markdown("https://example.com/missing")
            assert exc_info.value.code == ErrorCode.NOT_FOUND

    @pytest.mark.anyio
    async def test_render_error_propagates(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mock_pool_instance = AsyncMock()
        mocker.patch("proctx_crawler.crawler.BrowserPool", return_value=mock_pool_instance)
        mocker.patch(
            "proctx_crawler.crawler.fetch_rendered",
            side_effect=RenderError(
                code=ErrorCode.RENDER_FAILED,
                message="Playwright crashed",
                recoverable=True,
            ),
        )

        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with pytest.raises(RenderError) as exc_info:
                await crawler.content("https://example.com", render=True)
            assert exc_info.value.code == ErrorCode.RENDER_FAILED


# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_default_output_dir_uses_platformdirs(self) -> None:
        crawler = Crawler()
        assert "proctx-crawler" in str(crawler._output_dir)
        assert str(crawler._output_dir).endswith("jobs")

    def test_default_db_path_uses_platformdirs(self) -> None:
        crawler = Crawler()
        assert "proctx-crawler" in str(crawler._db_path)
        assert str(crawler._db_path).endswith("crawler.db")

    def test_custom_paths(self, tmp_path: Path) -> None:
        crawler = Crawler(output_dir=tmp_path / "custom", db_path=tmp_path / "custom.db")
        assert crawler._output_dir == tmp_path / "custom"
        assert crawler._db_path == tmp_path / "custom.db"


# ---------------------------------------------------------------------------
# _build_goto_options
# ---------------------------------------------------------------------------


class TestBuildGotoOptions:
    def test_none_returns_none(self) -> None:
        from proctx_crawler.crawler import _build_goto_options

        assert _build_goto_options(None) is None

    def test_dict_returns_goto_options(self) -> None:
        from proctx_crawler.crawler import _build_goto_options

        result = _build_goto_options({"wait_until": "domcontentloaded", "timeout": 5000})
        assert result is not None
        assert result.wait_until == "domcontentloaded"
        assert result.timeout == 5000


# ---------------------------------------------------------------------------
# Re-export from __init__
# ---------------------------------------------------------------------------


class TestGetStorageGuard:
    """_get_storage() raises RuntimeError if the context manager was not entered."""

    @pytest.mark.anyio
    async def test_get_storage_without_context(self, tmp_path: Path) -> None:
        crawler = Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db")
        with pytest.raises(RuntimeError, match="async context manager"):
            # crawl() calls _get_repo() first which triggers the guard
            await crawler.crawl("https://example.com")


class TestCrawlWithRender:
    """crawl() with render=True lazily creates and passes the browser pool to the engine."""

    @pytest.mark.anyio
    async def test_crawl_render_creates_browser_pool(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        mock_pool_instance = AsyncMock()
        mocker.patch("proctx_crawler.crawler.BrowserPool", return_value=mock_pool_instance)
        mock_run_crawl = mocker.patch("proctx_crawler.crawler.run_crawl")

        async def _fake_run_crawl(job, repo, storage, browser_pool=None):  # type: ignore[no-untyped-def]
            await repo.enqueue_url(job.id, job.url, depth=0)
            await repo.mark_url_completed(job.id, job.url, http_status=200, title="Home")
            await repo.update_job_status(job.id, JobStatus.COMPLETED)
            await repo.update_job_counts(job.id, total=1, finished=1)
            await storage.write(
                job.id,
                job.url,
                type("Content", (), {"markdown": "# Home", "html": None})(),
            )

        mock_run_crawl.side_effect = _fake_run_crawl

        async with Crawler(output_dir=tmp_path / "out", db_path=tmp_path / "test.db") as crawler:
            with anyio.fail_after(10):
                await crawler.crawl("https://example.com", limit=1, render=True)

        mock_pool_instance.start.assert_awaited_once()
        # run_crawl should have been called with the browser pool
        call_kwargs = mock_run_crawl.call_args
        assert call_kwargs[1].get("browser_pool") is mock_pool_instance or (
            len(call_kwargs[0]) >= 4 and call_kwargs[0][3] is mock_pool_instance
        )


class TestReExport:
    def test_crawler_importable_from_package(self) -> None:
        from proctx_crawler import Crawler as ImportedCrawler

        assert ImportedCrawler is Crawler
