"""Tests for the BFS crawl engine."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import anyio
import pytest

from proctx_crawler.core.engine import QueueEntry, _extract_title, run_crawl
from proctx_crawler.core.fetcher import FetchResult
from proctx_crawler.infrastructure.content_storage import ContentStorage
from proctx_crawler.infrastructure.sqlite_repository import SQLiteRepository
from proctx_crawler.models import (
    CrawlConfig,
    CrawlOptions,
    ErrorCode,
    FetchError,
    Job,
    JobStatus,
    UrlStatus,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from pytest_mock import MockerFixture


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

_BASE_URL = "https://example.com"


def _html(title: str, body: str = "", links: list[str] | None = None) -> str:
    """Build a minimal HTML page with optional links."""
    link_tags = ""
    if links:
        link_tags = "\n".join(f'<a href="{url}">{url}</a>' for url in links)
    return f"<html><head><title>{title}</title></head><body>{body}{link_tags}</body></html>"


# Map from URL to (status_code, html)
HTML_PAGES: dict[str, tuple[int, str]] = {
    "https://example.com": (
        200,
        _html(
            "Home",
            links=[
                "https://example.com/page1",
                "https://example.com/page2",
            ],
        ),
    ),
    "https://example.com/page1": (
        200,
        _html(
            "Page 1",
            links=["https://example.com/page2", "https://example.com/page3"],
        ),
    ),
    "https://example.com/page2": (
        200,
        _html("Page 2", links=["https://example.com"]),
    ),
    "https://example.com/page3": (
        200,
        _html("Page 3"),
    ),
}


def _make_fetch_result(url: str) -> FetchResult:
    """Return a FetchResult from the HTML_PAGES map."""
    status_code, html = HTML_PAGES[url]
    return FetchResult(url=url, status_code=status_code, html=html, headers={})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_job(
    job_id: str = "test-job",
    url: str = _BASE_URL,
    *,
    limit: int = 10,
    depth: int = 1000,
    source: str = "links",
    formats: list[str] | None = None,
    options: CrawlOptions | None = None,
) -> Job:
    now = datetime.now(UTC)
    config = CrawlConfig(
        url=url,
        limit=limit,
        depth=depth,
        source=source,  # type: ignore[arg-type]
        formats=formats or ["markdown"],
        options=options or CrawlOptions(),
    )
    return Job(id=job_id, url=url, config=config, created_at=now, updated_at=now)


@pytest.fixture()
async def repo(tmp_path: Path) -> AsyncIterator[SQLiteRepository]:
    """Fresh SQLiteRepository per test."""
    r = SQLiteRepository(tmp_path / "test.db")
    await r.initialise()
    yield r
    await r.close()


@pytest.fixture()
def storage(tmp_path: Path) -> ContentStorage:
    """Fresh ContentStorage per test."""
    return ContentStorage(tmp_path / "output")


def _patch_fetcher(mocker: MockerFixture, pages: dict[str, tuple[int, str]]) -> None:
    """Patch fetch_static to return pages from a lookup dict."""

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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExtractTitle:
    def test_title_tag(self) -> None:
        html = "<html><head><title>My Page</title></head><body></body></html>"
        assert _extract_title(html) == "My Page"

    def test_h1_fallback(self) -> None:
        html = "<html><body><h1>Heading One</h1></body></html>"
        assert _extract_title(html) == "Heading One"

    def test_no_title(self) -> None:
        html = "<html><body><p>Nothing here</p></body></html>"
        assert _extract_title(html) is None


class TestQueueEntry:
    def test_dataclass_fields(self) -> None:
        entry = QueueEntry(url="https://example.com", depth=2)
        assert entry.url == "https://example.com"
        assert entry.depth == 2


class TestBasicCrawl:
    """Start URL links to 2 other pages. All 3 should be crawled."""

    @pytest.mark.anyio
    async def test_three_linked_pages(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        pages = {
            "https://example.com": (
                200,
                _html("Home", links=["https://example.com/page1", "https://example.com/page2"]),
            ),
            "https://example.com/page1": (200, _html("Page 1")),
            "https://example.com/page2": (200, _html("Page 2")),
        }
        _patch_fetcher(mocker, pages)

        job = _make_job(limit=10, depth=1)
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        final_job = await repo.get_job(job.id)
        assert final_job is not None
        assert final_job.status == JobStatus.COMPLETED
        assert final_job.finished == 3

        # Verify content files exist
        for url in pages:
            content = await storage.read(job.id, url, "markdown")
            assert content is not None


class TestDepthLimit:
    """With depth=1, page2 (at depth 2) should NOT be crawled."""

    @pytest.mark.anyio
    async def test_depth_limit_respected(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        pages = {
            "https://example.com": (
                200,
                _html("Home", links=["https://example.com/page1"]),
            ),
            "https://example.com/page1": (
                200,
                _html("Page 1", links=["https://example.com/page2"]),
            ),
            "https://example.com/page2": (200, _html("Page 2")),
        }
        _patch_fetcher(mocker, pages)

        job = _make_job(limit=10, depth=1)
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        final_job = await repo.get_job(job.id)
        assert final_job is not None
        assert final_job.status == JobStatus.COMPLETED
        # Home (depth 0) + Page 1 (depth 1) = 2 completed; Page 2 at depth 2 is excluded.
        assert final_job.finished == 2


class TestPageLimit:
    """5 discoverable pages, limit=3. Only 3 should be crawled."""

    @pytest.mark.anyio
    async def test_page_limit_respected(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        pages = {
            "https://example.com": (
                200,
                _html(
                    "Home",
                    links=[
                        "https://example.com/p1",
                        "https://example.com/p2",
                        "https://example.com/p3",
                        "https://example.com/p4",
                    ],
                ),
            ),
            "https://example.com/p1": (200, _html("P1")),
            "https://example.com/p2": (200, _html("P2")),
            "https://example.com/p3": (200, _html("P3")),
            "https://example.com/p4": (200, _html("P4")),
        }
        _patch_fetcher(mocker, pages)

        job = _make_job(limit=3, depth=1)
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        final_job = await repo.get_job(job.id)
        assert final_job is not None
        assert final_job.status == JobStatus.COMPLETED

        # Count completed URL records
        records, _ = await repo.get_url_records(job.id, limit=100, status=UrlStatus.COMPLETED)
        assert len(records) == 3


class TestUrlPatternFiltering:
    """Include pattern **/docs/** — URLs not matching are skipped."""

    @pytest.mark.anyio
    async def test_include_pattern_filters(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        pages = {
            "https://example.com/docs/start": (
                200,
                _html(
                    "Docs Start",
                    links=[
                        "https://example.com/docs/page1",
                        "https://example.com/blog/post1",
                    ],
                ),
            ),
            "https://example.com/docs/page1": (200, _html("Docs Page 1")),
            "https://example.com/blog/post1": (200, _html("Blog Post")),
        }
        _patch_fetcher(mocker, pages)

        options = CrawlOptions(include_patterns=["**/docs/**"])
        job = _make_job(
            url="https://example.com/docs/start",
            limit=10,
            depth=1,
            options=options,
        )
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        records, _ = await repo.get_url_records(job.id, limit=100, status=UrlStatus.COMPLETED)
        crawled_urls = {r.url for r in records}
        assert "https://example.com/docs/start" in crawled_urls
        assert "https://example.com/docs/page1" in crawled_urls
        assert "https://example.com/blog/post1" not in crawled_urls


class TestDomainFiltering:
    """External links not followed by default (include_external_links=False)."""

    @pytest.mark.anyio
    async def test_external_links_not_followed(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        pages = {
            "https://example.com": (
                200,
                _html(
                    "Home",
                    links=[
                        "https://example.com/page1",
                        "https://external.com/page",
                    ],
                ),
            ),
            "https://example.com/page1": (200, _html("Page 1")),
            "https://external.com/page": (200, _html("External Page")),
        }
        _patch_fetcher(mocker, pages)

        job = _make_job(limit=10, depth=1)
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        records, _ = await repo.get_url_records(job.id, limit=100, status=UrlStatus.COMPLETED)
        crawled_urls = {r.url for r in records}
        assert "https://example.com" in crawled_urls
        assert "https://example.com/page1" in crawled_urls
        assert "https://external.com/page" not in crawled_urls


class TestCancellation:
    """After 1 page is crawled, mark job as cancelled. Crawl stops."""

    @pytest.mark.anyio
    async def test_cancellation_mid_crawl(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        pages = {
            "https://example.com": (
                200,
                _html(
                    "Home",
                    links=["https://example.com/page1", "https://example.com/page2"],
                ),
            ),
            "https://example.com/page1": (200, _html("Page 1")),
            "https://example.com/page2": (200, _html("Page 2")),
        }
        _patch_fetcher(mocker, pages)

        job = _make_job(limit=10, depth=1)
        await repo.create_job(job)

        call_count = 0
        original_is_cancelled = repo.is_job_cancelled

        async def _cancel_after_first(job_id: str) -> bool:
            """Return True (cancelled) after the first URL has been processed."""
            nonlocal call_count
            call_count += 1
            # The first check happens at the top of the BFS loop before processing.
            # After the first URL is processed, the loop checks again — cancel then.
            if call_count > 1:
                await repo.update_job_status(job_id, JobStatus.CANCELLED)
                return True
            return await original_is_cancelled(job_id)

        mocker.patch.object(repo, "is_job_cancelled", side_effect=_cancel_after_first)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        final_job = await repo.get_job(job.id)
        assert final_job is not None
        assert final_job.status == JobStatus.CANCELLED

        records, _ = await repo.get_url_records(job.id, limit=100, status=UrlStatus.COMPLETED)
        # Only the first page should be completed before cancellation.
        assert len(records) == 1


class TestErrorIsolation:
    """One URL returns an error. Other URLs still crawled. Failed URL marked as errored."""

    @pytest.mark.anyio
    async def test_error_does_not_stop_crawl(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        pages = {
            "https://example.com": (
                200,
                _html(
                    "Home",
                    links=["https://example.com/good", "https://example.com/bad"],
                ),
            ),
            "https://example.com/good": (200, _html("Good Page")),
            # "https://example.com/bad" intentionally missing — will raise FetchError
        }
        _patch_fetcher(mocker, pages)

        job = _make_job(limit=10, depth=1)
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        final_job = await repo.get_job(job.id)
        assert final_job is not None
        assert final_job.status == JobStatus.COMPLETED

        completed, _ = await repo.get_url_records(job.id, limit=100, status=UrlStatus.COMPLETED)
        errored, _ = await repo.get_url_records(job.id, limit=100, status=UrlStatus.ERRORED)

        completed_urls = {r.url for r in completed}
        errored_urls = {r.url for r in errored}

        assert "https://example.com" in completed_urls
        assert "https://example.com/good" in completed_urls
        assert "https://example.com/bad" in errored_urls


class TestLlmsTxtSource:
    """Starting URL is llms.txt. Parse for seed URLs. No per-page link discovery."""

    @pytest.mark.anyio
    async def test_llms_txt_seeds_only(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        llms_txt_content = (
            "# llms.txt\n- [Page A](https://example.com/a)\n- [Page B](https://example.com/b)\n"
        )
        pages = {
            "https://example.com/llms.txt": (200, llms_txt_content),
            "https://example.com/a": (
                200,
                _html("Page A", links=["https://example.com/should-not-follow"]),
            ),
            "https://example.com/b": (200, _html("Page B")),
            "https://example.com/should-not-follow": (200, _html("Hidden")),
        }
        _patch_fetcher(mocker, pages)

        job = _make_job(
            url="https://example.com/llms.txt",
            source="llms_txt",
            limit=10,
            depth=1000,
        )
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        final_job = await repo.get_job(job.id)
        assert final_job is not None
        assert final_job.status == JobStatus.COMPLETED

        completed, _ = await repo.get_url_records(job.id, limit=100, status=UrlStatus.COMPLETED)
        crawled_urls = {r.url for r in completed}

        assert "https://example.com/a" in crawled_urls
        assert "https://example.com/b" in crawled_urls
        # Per-page link discovery should NOT happen for llms_txt.
        assert "https://example.com/should-not-follow" not in crawled_urls


class TestVisitedSetDeduplication:
    """Two pages link to each other. Each is crawled only once."""

    @pytest.mark.anyio
    async def test_no_re_crawl(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        pages = {
            "https://example.com": (
                200,
                _html("Home", links=["https://example.com/page1"]),
            ),
            "https://example.com/page1": (
                200,
                _html("Page 1", links=["https://example.com"]),
            ),
        }
        _patch_fetcher(mocker, pages)

        job = _make_job(limit=10, depth=5)
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        records, _ = await repo.get_url_records(job.id, limit=100)
        assert len(records) == 2  # Each URL appears exactly once.


class TestEmptyQueue:
    """Start URL has no links. Crawl completes with 1 page."""

    @pytest.mark.anyio
    async def test_single_page_no_links(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        pages = {"https://example.com": (200, _html("Lonely Page"))}
        _patch_fetcher(mocker, pages)

        job = _make_job(limit=10, depth=1)
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        final_job = await repo.get_job(job.id)
        assert final_job is not None
        assert final_job.status == JobStatus.COMPLETED
        assert final_job.finished == 1


class TestManifestWritten:
    """After crawl, manifest.json exists in the job directory."""

    @pytest.mark.anyio
    async def test_manifest_exists(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        pages = {
            "https://example.com": (
                200,
                _html("Home", links=["https://example.com/page1"]),
            ),
            "https://example.com/page1": (200, _html("Page 1")),
        }
        _patch_fetcher(mocker, pages)

        job = _make_job(limit=10, depth=1)
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        manifest_path = storage.job_dir(job.id) / "manifest.json"
        assert manifest_path.exists()

        manifest = json.loads(manifest_path.read_text())
        assert manifest["job_id"] == job.id
        assert manifest["status"] == "completed"
        assert len(manifest["pages"]) == 2


class TestSeedError:
    """When seed fetching fails for llms_txt, job should be marked errored."""

    @pytest.mark.anyio
    async def test_llms_txt_seed_fetch_failure(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        # No pages — the llms.txt fetch during seeding will fail.
        _patch_fetcher(mocker, {})

        job = _make_job(
            url="https://example.com/llms.txt",
            source="llms_txt",
            limit=10,
            depth=1,
        )
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        final_job = await repo.get_job(job.id)
        assert final_job is not None
        assert final_job.status == JobStatus.ERRORED

    @pytest.mark.anyio
    async def test_all_urls_errored_still_completes(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        """When all URLs error during the BFS loop, job still finishes as COMPLETED."""
        _patch_fetcher(mocker, {})

        # Source is "links" so seeding succeeds (returns [job.url] without fetching),
        # but the actual fetch during BFS loop fails.
        job = _make_job(limit=10, depth=1)
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        final_job = await repo.get_job(job.id)
        assert final_job is not None
        assert final_job.status == JobStatus.COMPLETED

        errored, _ = await repo.get_url_records(job.id, limit=100, status=UrlStatus.ERRORED)
        assert len(errored) == 1
        assert errored[0].url == "https://example.com"


class TestUnexpectedSeedError:
    """A non-CrawlerError during seeding marks the job as errored."""

    @pytest.mark.anyio
    async def test_unexpected_error_during_seed(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        mocker.patch(
            "proctx_crawler.core.engine.fetch_static",
            side_effect=RuntimeError("kaboom"),
        )

        job = _make_job(
            url="https://example.com/llms.txt",
            source="llms_txt",
            limit=10,
            depth=1,
        )
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        final_job = await repo.get_job(job.id)
        assert final_job is not None
        assert final_job.status == JobStatus.ERRORED


class TestUnexpectedUrlError:
    """A non-CrawlerError during URL processing marks the URL as errored
    but does not crash the crawl."""

    @pytest.mark.anyio
    async def test_unexpected_error_marks_url_errored(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        call_count = 0

        async def _explode_on_second(url: str, **_kwargs: object) -> FetchResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call succeeds (the starting page)
                html = _html("Home", links=["https://example.com/boom"])
                return FetchResult(url=url, status_code=200, html=html, headers={})
            raise RuntimeError("totally unexpected")

        mocker.patch("proctx_crawler.core.engine.fetch_static", side_effect=_explode_on_second)

        job = _make_job(limit=10, depth=1)
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        final_job = await repo.get_job(job.id)
        assert final_job is not None
        assert final_job.status == JobStatus.COMPLETED

        errored, _ = await repo.get_url_records(job.id, limit=100, status=UrlStatus.ERRORED)
        assert len(errored) == 1
        assert errored[0].url == "https://example.com/boom"
        assert errored[0].error_message == "Unexpected error"


class TestRenderPathInEngine:
    """When render=True and a browser_pool is provided, the rendered path is used."""

    @pytest.mark.anyio
    async def test_render_calls_fetch_rendered(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        html = _html("Rendered Page")
        mock_result = FetchResult(url="https://example.com", status_code=200, html=html, headers={})
        mock_render = mocker.patch(
            "proctx_crawler.core.engine.fetch_rendered",
            return_value=mock_result,
        )

        from unittest.mock import AsyncMock

        mock_pool = AsyncMock()

        job = _make_job(limit=1, depth=0)
        # Override config to enable render
        job.config.render = True
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage, browser_pool=mock_pool)

        mock_render.assert_awaited_once()
        final_job = await repo.get_job(job.id)
        assert final_job is not None
        assert final_job.status == JobStatus.COMPLETED
