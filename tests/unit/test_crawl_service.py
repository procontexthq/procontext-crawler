"""Tests for shared crawl-job orchestration service."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from proctx_crawler.core.crawl_service import (
    build_and_persist_job,
    collect_crawl_result,
    url_record_to_crawl_record,
)
from proctx_crawler.models import (
    CrawlConfig,
    CrawlOptions,
    JobStatus,
    UrlRecord,
    UrlStatus,
)


def _make_config() -> CrawlConfig:
    return CrawlConfig(
        url="https://example.com",
        limit=10,
        depth=5,
        source="links",
        formats=["markdown"],
        render=False,
        options=CrawlOptions(),
    )


def _make_url_record(
    *,
    url: str = "https://example.com/page",
    status: UrlStatus = UrlStatus.COMPLETED,
    http_status: int | None = 200,
    title: str | None = "Page Title",
    content_hash: str | None = "abc123",
) -> UrlRecord:
    return UrlRecord(
        id="rec-1",
        job_id="job-1",
        url=url,
        url_hash="hash",
        depth=0,
        status=status,
        http_status=http_status,
        title=title,
        content_hash=content_hash,
        created_at=datetime.now(UTC),
    )


class TestBuildAndPersistJob:
    @pytest.mark.anyio
    async def test_builds_job_and_persists(self) -> None:
        repo = AsyncMock()
        config = _make_config()

        job = await build_and_persist_job("https://example.com", config, repo)

        assert job.url == "https://example.com"
        assert job.config is config
        assert job.id  # uuid
        assert job.created_at == job.updated_at
        repo.create_job.assert_awaited_once_with(job)

    @pytest.mark.anyio
    async def test_generates_unique_ids(self) -> None:
        repo = AsyncMock()
        config = _make_config()

        job_a = await build_and_persist_job("https://a.com", config, repo)
        job_b = await build_and_persist_job("https://b.com", config, repo)

        assert job_a.id != job_b.id


class TestUrlRecordToCrawlRecord:
    @pytest.mark.anyio
    async def test_completed_record_reads_requested_formats(self) -> None:
        storage = AsyncMock()
        storage.read.side_effect = ["# md content", "<html></html>"]

        rec = _make_url_record(status=UrlStatus.COMPLETED)
        out = await url_record_to_crawl_record("job-1", rec, storage, ["markdown", "html"])

        assert out.url == rec.url
        assert out.status == UrlStatus.COMPLETED
        assert out.markdown == "# md content"
        assert out.html == "<html></html>"
        assert out.metadata is not None
        assert out.metadata.http_status == 200
        assert out.metadata.title == "Page Title"
        assert out.metadata.content_hash == "abc123"

    @pytest.mark.anyio
    async def test_completed_record_markdown_only(self) -> None:
        storage = AsyncMock()
        storage.read.return_value = "# only md"

        rec = _make_url_record()
        out = await url_record_to_crawl_record("job-1", rec, storage, ["markdown"])

        assert out.markdown == "# only md"
        assert out.html is None
        storage.read.assert_awaited_once_with("job-1", rec.url, "markdown")

    @pytest.mark.anyio
    async def test_non_completed_record_skips_storage(self) -> None:
        storage = AsyncMock()
        rec = _make_url_record(status=UrlStatus.ERRORED)

        out = await url_record_to_crawl_record("job-1", rec, storage, ["markdown"])

        assert out.markdown is None
        assert out.html is None
        assert out.metadata is None
        storage.read.assert_not_called()

    @pytest.mark.anyio
    async def test_none_http_status_becomes_zero(self) -> None:
        storage = AsyncMock()
        storage.read.return_value = "md"
        rec = _make_url_record(http_status=None)

        out = await url_record_to_crawl_record("job-1", rec, storage, ["markdown"])

        assert out.metadata is not None
        assert out.metadata.http_status == 0


class TestCollectCrawlResult:
    @pytest.mark.anyio
    async def test_paginates_and_collects_all_records(self) -> None:
        repo = AsyncMock()
        storage = AsyncMock()
        storage.read.return_value = "md"

        mock_job = AsyncMock()
        mock_job.status = JobStatus.COMPLETED
        mock_job.total = 3
        mock_job.finished = 3
        repo.get_job.return_value = mock_job

        page1 = [_make_url_record(url="https://a"), _make_url_record(url="https://b")]
        page2 = [_make_url_record(url="https://c")]
        repo.get_url_records.side_effect = [(page1, "cursor-1"), (page2, None)]

        result = await collect_crawl_result("job-1", repo, storage, ["markdown"])

        assert result.id == "job-1"
        assert result.status == JobStatus.COMPLETED
        assert result.total == 3
        assert result.finished == 3
        assert [r.url for r in result.records] == ["https://a", "https://b", "https://c"]
        assert result.cursor is None
        assert repo.get_url_records.await_count == 2

    @pytest.mark.anyio
    async def test_empty_first_page_breaks_loop(self) -> None:
        repo = AsyncMock()
        storage = AsyncMock()
        mock_job = AsyncMock()
        mock_job.status = JobStatus.COMPLETED
        mock_job.total = 0
        mock_job.finished = 0
        repo.get_job.return_value = mock_job
        repo.get_url_records.return_value = ([], None)

        result = await collect_crawl_result("job-1", repo, storage, ["markdown"])

        assert result.records == []
        repo.get_url_records.assert_awaited_once()

    @pytest.mark.anyio
    async def test_missing_job_returns_errored_status(self) -> None:
        repo = AsyncMock()
        storage = AsyncMock()
        repo.get_job.return_value = None
        repo.get_url_records.return_value = ([], None)

        result = await collect_crawl_result("missing", repo, storage, ["markdown"])

        assert result.status == JobStatus.ERRORED
        assert result.total == 0
        assert result.finished == 0
        assert result.records == []
