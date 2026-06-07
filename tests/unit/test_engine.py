"""Tests for the BFS crawl engine."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

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
    from collections.abc import AsyncIterator, Callable
    from pathlib import Path

    from pytest_mock import MockerFixture


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

_BASE_URL = "https://example.com"
PageFixture = tuple[int, str] | tuple[int, str, dict[str, str]]


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


def _page_fixture_parts(page: PageFixture) -> tuple[int, str, dict[str, str]]:
    """Return status, body, and headers from a page fixture."""
    if len(page) == 2:
        status_code, html = page
        return status_code, html, {}
    status_code, html, headers = page
    return status_code, html, headers


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


def _patch_fetcher(mocker: MockerFixture, pages: dict[str, PageFixture]) -> None:
    """Patch fetch_static to return pages from a lookup dict."""

    async def _mock_fetch(url: str, **_kwargs: object) -> FetchResult:
        if url not in pages:
            raise FetchError(
                code=ErrorCode.NOT_FOUND,
                message=f"Page not found: {url}",
                recoverable=False,
            )
        status_code, html, headers = _page_fixture_parts(pages[url])
        return FetchResult(url=url, status_code=status_code, html=html, headers=headers)

    mocker.patch("proctx_crawler.core.engine.fetch_static", side_effect=_mock_fetch)


def _monotonic_values(values: list[float]) -> Callable[[], float]:
    remaining = values.copy()

    def _next() -> float:
        if len(remaining) > 1:
            return remaining.pop(0)
        return remaining[0]

    return _next


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
        assert entry.discover_children is True
        assert entry.prefetched_response is None


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

    @pytest.mark.anyio
    async def test_page_limit_does_not_leave_queued_records(
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
                    ],
                ),
            ),
            "https://example.com/p1": (200, _html("P1")),
            "https://example.com/p2": (200, _html("P2")),
            "https://example.com/p3": (200, _html("P3")),
        }
        _patch_fetcher(mocker, pages)

        job = _make_job(limit=2, depth=1)
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        all_records, _ = await repo.get_url_records(job.id, limit=100)
        queued, _ = await repo.get_url_records(job.id, limit=100, status=UrlStatus.QUEUED)
        assert len(all_records) == 2
        assert queued == []

        final_job = await repo.get_job(job.id)
        assert final_job is not None
        assert final_job.total == 2
        assert final_job.finished == 2

    @pytest.mark.anyio
    async def test_errored_urls_count_toward_page_limit(
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
                        "https://example.com/missing",
                        "https://example.com/should-not-schedule",
                    ],
                ),
            ),
        }
        _patch_fetcher(mocker, pages)

        job = _make_job(limit=2, depth=1)
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        all_records, _ = await repo.get_url_records(job.id, limit=100)
        errored, _ = await repo.get_url_records(job.id, limit=100, status=UrlStatus.ERRORED)

        assert [record.url for record in all_records] == [
            "https://example.com",
            "https://example.com/missing",
        ]
        assert len(errored) == 1

        final_job = await repo.get_job(job.id)
        assert final_job is not None
        assert final_job.total == 2
        assert final_job.finished == 2

    @pytest.mark.anyio
    async def test_all_errored_url_attempts_respect_limit(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        pages = {
            "https://example.com/llms.txt": (
                200,
                "\n".join(
                    [
                        "- [A](https://example.com/a)",
                        "- [B](https://example.com/b)",
                        "- [C](https://example.com/c)",
                    ]
                ),
            ),
        }
        _patch_fetcher(mocker, pages)

        job = _make_job(url="https://example.com/llms.txt", source="llms_txt", limit=2)
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        all_records, _ = await repo.get_url_records(job.id, limit=100)
        errored, _ = await repo.get_url_records(job.id, limit=100, status=UrlStatus.ERRORED)
        assert len(all_records) == 2
        assert len(errored) == 2

        final_job = await repo.get_job(job.id)
        assert final_job is not None
        assert final_job.total == 2
        assert final_job.finished == 2


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


class TestJobTimeout:
    """Cooperative job timeout cancels queued URLs and finalises the job."""

    @pytest.mark.anyio
    async def test_timeout_before_first_url_cancels_queued_url(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        pages = {"https://example.com": (200, _html("Home"))}
        _patch_fetcher(mocker, pages)
        fetch_static = mocker.patch("proctx_crawler.core.engine.fetch_static")
        mocker.patch(
            "proctx_crawler.core.engine.monotonic",
            side_effect=_monotonic_values([0.0, 2.0]),
        )

        job = _make_job(limit=1, depth=0)
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage, job_timeout=1)

        fetch_static.assert_not_awaited()
        final_job = await repo.get_job(job.id)
        assert final_job is not None
        assert final_job.status == JobStatus.CANCELLED
        assert final_job.total == 1
        assert final_job.finished == 1

        records, _ = await repo.get_url_records(job.id, limit=100)
        assert len(records) == 1
        assert records[0].status == UrlStatus.CANCELLED

        manifest = json.loads((storage.job_dir(job.id) / "manifest.json").read_text())
        assert manifest["status"] == "cancelled"
        assert manifest["total"] == 1
        assert manifest["finished"] == 1
        assert manifest["pages"] == {}

    @pytest.mark.anyio
    async def test_timeout_after_url_cancels_discovered_queue(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        pages = {
            "https://example.com": (
                200,
                _html("Home", links=["https://example.com/a", "https://example.com/b"]),
            ),
            "https://example.com/a": (200, _html("A")),
            "https://example.com/b": (200, _html("B")),
        }
        _patch_fetcher(mocker, pages)
        mocker.patch(
            "proctx_crawler.core.engine.monotonic",
            side_effect=_monotonic_values([0.0, 0.0, 2.0]),
        )

        job = _make_job(limit=10, depth=1)
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage, job_timeout=1)

        final_job = await repo.get_job(job.id)
        assert final_job is not None
        assert final_job.status == JobStatus.CANCELLED
        assert final_job.total == 3
        assert final_job.finished == 3

        completed, _ = await repo.get_url_records(job.id, limit=100, status=UrlStatus.COMPLETED)
        cancelled, _ = await repo.get_url_records(job.id, limit=100, status=UrlStatus.CANCELLED)
        assert [record.url for record in completed] == ["https://example.com"]
        assert {record.url for record in cancelled} == {
            "https://example.com/a",
            "https://example.com/b",
        }

        manifest = json.loads((storage.job_dir(job.id) / "manifest.json").read_text())
        assert manifest["status"] == "cancelled"
        assert manifest["total"] == 3
        assert manifest["finished"] == 3
        assert len(manifest["pages"]) == 1


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

    @pytest.mark.anyio
    async def test_llms_txt_seeding_respects_page_limit(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        llms_txt_content = (
            "# llms.txt\n"
            "- [Page A](https://example.com/a)\n"
            "- [Page B](https://example.com/b)\n"
            "- [Page C](https://example.com/c)\n"
        )
        pages = {
            "https://example.com/llms.txt": (200, llms_txt_content),
            "https://example.com/a": (200, _html("Page A")),
            "https://example.com/b": (200, _html("Page B")),
            "https://example.com/c": (200, _html("Page C")),
        }
        _patch_fetcher(mocker, pages)

        job = _make_job(url="https://example.com/llms.txt", source="llms_txt", limit=2)
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        records, _ = await repo.get_url_records(job.id, limit=100)
        assert [record.url for record in records] == [
            "https://example.com/a",
            "https://example.com/b",
        ]


class TestAutoSource:
    """Auto source classifies the start URL before choosing discovery behavior."""

    @pytest.mark.anyio
    async def test_auto_llms_txt_parses_listed_urls(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        llms_txt_content = (
            "# llms.txt\n- [Page A](https://example.com/a)\n- [Page B](https://example.com/b)\n"
        )
        pages: dict[str, PageFixture] = {
            "https://example.com/llms.txt": (200, llms_txt_content),
            "https://example.com/a": (
                200,
                _html("Page A", links=["https://example.com/should-not-follow"]),
            ),
            "https://example.com/b": (200, _html("Page B")),
            "https://example.com/should-not-follow": (200, _html("Hidden")),
        }
        _patch_fetcher(mocker, pages)

        job = _make_job(url="https://example.com/llms.txt", source="auto", limit=10)
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        completed, _ = await repo.get_url_records(job.id, limit=100, status=UrlStatus.COMPLETED)
        completed_urls = {record.url for record in completed}
        assert completed_urls == {"https://example.com/a", "https://example.com/b"}

    @pytest.mark.anyio
    async def test_auto_text_content_type_parses_urls(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        text_index = "- [Relative](./a)\nhttps://example.com/b#section\n"
        pages: dict[str, PageFixture] = {
            "https://example.com/index": (
                200,
                text_index,
                {"content-type": "text/markdown; charset=utf-8"},
            ),
            "https://example.com/a": (200, _html("A")),
            "https://example.com/b": (200, _html("B")),
        }
        _patch_fetcher(mocker, pages)

        job = _make_job(url="https://example.com/index", source="auto", limit=10)
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        records, _ = await repo.get_url_records(job.id, limit=100)
        assert [record.url for record in records] == [
            "https://example.com/a",
            "https://example.com/b",
        ]

    @pytest.mark.anyio
    async def test_auto_unknown_non_html_body_is_treated_as_text(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        pages: dict[str, PageFixture] = {
            "https://example.com/index": (200, "Docs: https://example.com/a\n"),
            "https://example.com/a": (200, _html("A")),
        }
        _patch_fetcher(mocker, pages)

        job = _make_job(url="https://example.com/index", source="auto", limit=10)
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        records, _ = await repo.get_url_records(job.id, limit=100)
        assert [record.url for record in records] == ["https://example.com/a"]

    @pytest.mark.anyio
    async def test_auto_html_uses_anchor_discovery_not_visible_text_urls(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        pages: dict[str, PageFixture] = {
            "https://example.com": (
                200,
                _html(
                    "Home",
                    body="<p>Visible URL: https://example.com/not-linked</p>",
                    links=["https://example.com/linked"],
                ),
                {"content-type": "text/html"},
            ),
            "https://example.com/linked": (200, _html("Linked")),
            "https://example.com/not-linked": (200, _html("Not Linked")),
        }
        _patch_fetcher(mocker, pages)

        job = _make_job(source="auto", limit=10, depth=1)
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        completed, _ = await repo.get_url_records(job.id, limit=100, status=UrlStatus.COMPLETED)
        completed_urls = {record.url for record in completed}
        assert "https://example.com" in completed_urls
        assert "https://example.com/linked" in completed_urls
        assert "https://example.com/not-linked" not in completed_urls

    @pytest.mark.anyio
    async def test_explicit_links_with_llms_txt_crawls_original_only(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        pages: dict[str, PageFixture] = {
            "https://example.com/llms.txt": (
                200,
                "- [Page A](https://example.com/a)\nhttps://example.com/b\n",
                {"content-type": "text/plain"},
            ),
            "https://example.com/a": (200, _html("A")),
            "https://example.com/b": (200, _html("B")),
        }
        _patch_fetcher(mocker, pages)

        job = _make_job(url="https://example.com/llms.txt", source="links", limit=10)
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        completed, _ = await repo.get_url_records(job.id, limit=100, status=UrlStatus.COMPLETED)
        assert [record.url for record in completed] == ["https://example.com/llms.txt"]

    @pytest.mark.anyio
    async def test_auto_text_page_without_urls_crawls_original(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        pages: dict[str, PageFixture] = {
            "https://example.com/readme.txt": (
                200,
                "This text file has no crawlable links.",
                {"content-type": "text/plain"},
            )
        }
        _patch_fetcher(mocker, pages)

        job = _make_job(url="https://example.com/readme.txt", source="auto", limit=10)
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        completed, _ = await repo.get_url_records(job.id, limit=100, status=UrlStatus.COMPLETED)
        assert [record.url for record in completed] == ["https://example.com/readme.txt"]

    @pytest.mark.anyio
    async def test_auto_text_page_with_render_reuses_static_prefetch(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        pages: dict[str, PageFixture] = {
            "https://example.com/readme.txt": (
                200,
                "This text file has no crawlable links.",
                {"content-type": "text/plain"},
            )
        }
        _patch_fetcher(mocker, pages)
        fetch_rendered = mocker.patch("proctx_crawler.core.engine.fetch_rendered")

        job = _make_job(url="https://example.com/readme.txt", source="auto", limit=10)
        job.config.render = True
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage, browser_pool=None)

        fetch_rendered.assert_not_awaited()
        completed, _ = await repo.get_url_records(job.id, limit=100, status=UrlStatus.COMPLETED)
        assert [record.url for record in completed] == ["https://example.com/readme.txt"]

    @pytest.mark.anyio
    async def test_auto_classification_fetch_error_uses_url_level_error_path(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        async def _raise_fetch_error(url: str, **_kwargs: object) -> FetchResult:
            raise FetchError(
                code=ErrorCode.FETCH_FAILED,
                message=f"Connection error fetching {url}",
                recoverable=True,
            )

        fetch_static = mocker.patch(
            "proctx_crawler.core.engine.fetch_static",
            side_effect=_raise_fetch_error,
        )

        job = _make_job(source="auto", limit=10)
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage)

        final_job = await repo.get_job(job.id)
        assert final_job is not None
        assert final_job.status == JobStatus.COMPLETED
        assert fetch_static.await_count == 2

        errored, _ = await repo.get_url_records(job.id, limit=100, status=UrlStatus.ERRORED)
        assert [record.url for record in errored] == ["https://example.com"]

    @pytest.mark.anyio
    async def test_auto_html_render_does_not_reuse_static_prefetch(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        static_result = FetchResult(
            url="https://example.com",
            status_code=200,
            html=_html("Static", body="<h1>Static</h1>"),
            headers={"content-type": "text/html"},
        )
        rendered_result = FetchResult(
            url="https://example.com",
            status_code=200,
            html=_html("Rendered", body="<h1>Rendered</h1>"),
            headers={"content-type": "text/html"},
        )
        fetch_static = mocker.patch(
            "proctx_crawler.core.engine.fetch_static",
            return_value=static_result,
        )
        fetch_rendered = mocker.patch(
            "proctx_crawler.core.engine.fetch_rendered",
            return_value=rendered_result,
        )

        job = _make_job(source="auto", limit=1, depth=0)
        job.config.render = True
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage, browser_pool=AsyncMock())

        fetch_static.assert_awaited_once()
        fetch_rendered.assert_awaited_once()
        content = await storage.read(job.id, "https://example.com", "markdown")
        assert content is not None
        assert "Rendered" in content
        assert "Static" not in content


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

    @pytest.mark.anyio
    async def test_render_without_browser_pool_marks_url_errored_and_skips_static(
        self,
        repo: SQLiteRepository,
        storage: ContentStorage,
        mocker: MockerFixture,
    ) -> None:
        mock_static = mocker.patch("proctx_crawler.core.engine.fetch_static")
        mock_render = mocker.patch("proctx_crawler.core.engine.fetch_rendered")

        job = _make_job(limit=1, depth=0)
        job.config.render = True
        await repo.create_job(job)

        with anyio.fail_after(5):
            await run_crawl(job, repo, storage, browser_pool=None)

        mock_static.assert_not_awaited()
        mock_render.assert_not_awaited()

        errored, _ = await repo.get_url_records(job.id, limit=100, status=UrlStatus.ERRORED)
        assert len(errored) == 1
        assert "browser_pool is required" in (errored[0].error_message or "")
