"""Tests for the SQLite repository implementation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest

from proctx_crawler.core.url_utils import url_hash
from proctx_crawler.infrastructure.sqlite_repository import SQLiteRepository
from proctx_crawler.models import (
    CrawlConfig,
    CrawlerError,
    Job,
    JobStatus,
    UrlStatus,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(job_id: str = "job-1", url: str = "https://example.com") -> Job:
    now = datetime.now(UTC)
    return Job(
        id=job_id,
        url=url,
        config=CrawlConfig(url=url),
        created_at=now,
        updated_at=now,
    )


@pytest.fixture()
async def repo(tmp_path: Path) -> AsyncIterator[SQLiteRepository]:
    """Create and initialise a fresh SQLiteRepository per test."""
    r = SQLiteRepository(tmp_path / "test.db")
    await r.initialise()
    yield r
    await r.close()


# ---------------------------------------------------------------------------
# Job operations
# ---------------------------------------------------------------------------


class TestCreateAndGetJob:
    @pytest.mark.anyio()
    async def test_round_trip(self, repo: SQLiteRepository) -> None:
        job = _make_job()
        await repo.create_job(job)

        retrieved = await repo.get_job(job.id)
        assert retrieved is not None
        assert retrieved.id == job.id
        assert retrieved.status == JobStatus.QUEUED
        assert retrieved.url == job.url
        assert retrieved.config == job.config
        assert retrieved.total == 0
        assert retrieved.finished == 0
        assert retrieved.created_at == job.created_at
        assert retrieved.updated_at == job.updated_at
        assert retrieved.started_at is None
        assert retrieved.finished_at is None

    @pytest.mark.anyio()
    async def test_get_job_returns_none_for_missing(self, repo: SQLiteRepository) -> None:
        result = await repo.get_job("nonexistent-id")
        assert result is None


class TestUpdateJobStatus:
    @pytest.mark.anyio()
    async def test_update_to_running(self, repo: SQLiteRepository) -> None:
        job = _make_job()
        await repo.create_job(job)

        await repo.update_job_status(job.id, JobStatus.RUNNING)

        updated = await repo.get_job(job.id)
        assert updated is not None
        assert updated.status == JobStatus.RUNNING
        assert updated.updated_at > job.updated_at
        assert updated.finished_at is None

    @pytest.mark.anyio()
    async def test_update_to_completed_sets_finished_at(self, repo: SQLiteRepository) -> None:
        job = _make_job()
        await repo.create_job(job)

        await repo.update_job_status(job.id, JobStatus.COMPLETED)

        updated = await repo.get_job(job.id)
        assert updated is not None
        assert updated.status == JobStatus.COMPLETED
        assert updated.finished_at is not None

    @pytest.mark.anyio()
    async def test_update_to_cancelled_sets_finished_at(self, repo: SQLiteRepository) -> None:
        job = _make_job()
        await repo.create_job(job)

        await repo.update_job_status(job.id, JobStatus.CANCELLED)

        updated = await repo.get_job(job.id)
        assert updated is not None
        assert updated.status == JobStatus.CANCELLED
        assert updated.finished_at is not None

    @pytest.mark.anyio()
    async def test_update_to_errored_sets_finished_at(self, repo: SQLiteRepository) -> None:
        job = _make_job()
        await repo.create_job(job)

        await repo.update_job_status(job.id, JobStatus.ERRORED)

        updated = await repo.get_job(job.id)
        assert updated is not None
        assert updated.status == JobStatus.ERRORED
        assert updated.finished_at is not None


class TestUpdateJobCounts:
    @pytest.mark.anyio()
    async def test_update_total_and_finished(self, repo: SQLiteRepository) -> None:
        job = _make_job()
        await repo.create_job(job)

        await repo.update_job_counts(job.id, total=10, finished=5)

        updated = await repo.get_job(job.id)
        assert updated is not None
        assert updated.total == 10
        assert updated.finished == 5


class TestIsJobCancelled:
    @pytest.mark.anyio()
    async def test_false_initially(self, repo: SQLiteRepository) -> None:
        job = _make_job()
        await repo.create_job(job)

        assert await repo.is_job_cancelled(job.id) is False

    @pytest.mark.anyio()
    async def test_true_after_cancellation(self, repo: SQLiteRepository) -> None:
        job = _make_job()
        await repo.create_job(job)

        await repo.update_job_status(job.id, JobStatus.CANCELLED)

        assert await repo.is_job_cancelled(job.id) is True

    @pytest.mark.anyio()
    async def test_false_for_nonexistent_job(self, repo: SQLiteRepository) -> None:
        assert await repo.is_job_cancelled("no-such-job") is False


# ---------------------------------------------------------------------------
# URL record operations
# ---------------------------------------------------------------------------


class TestEnqueueUrl:
    @pytest.mark.anyio()
    async def test_enqueue_and_retrieve(self, repo: SQLiteRepository) -> None:
        job = _make_job()
        await repo.create_job(job)

        test_url = "https://example.com/page1"
        await repo.enqueue_url(job.id, test_url, depth=1)

        records, cursor = await repo.get_url_records(job.id)
        assert len(records) == 1
        assert records[0].url == test_url
        assert records[0].url_hash == url_hash(test_url)
        assert records[0].depth == 1
        assert records[0].status == UrlStatus.QUEUED
        assert records[0].job_id == job.id
        assert cursor is None

    @pytest.mark.anyio()
    async def test_duplicate_url_raises(self, repo: SQLiteRepository) -> None:
        job = _make_job()
        await repo.create_job(job)

        test_url = "https://example.com/page1"
        await repo.enqueue_url(job.id, test_url, depth=0)

        with pytest.raises(CrawlerError):
            await repo.enqueue_url(job.id, test_url, depth=0)

    @pytest.mark.anyio()
    async def test_same_url_different_jobs(self, repo: SQLiteRepository) -> None:
        job1 = _make_job("job-1")
        job2 = _make_job("job-2")
        await repo.create_job(job1)
        await repo.create_job(job2)

        test_url = "https://example.com/page1"
        await repo.enqueue_url(job1.id, test_url, depth=0)
        await repo.enqueue_url(job2.id, test_url, depth=0)

        records1, _ = await repo.get_url_records(job1.id)
        records2, _ = await repo.get_url_records(job2.id)
        assert len(records1) == 1
        assert len(records2) == 1


class TestGetUrlRecords:
    @pytest.mark.anyio()
    async def test_basic_retrieval(self, repo: SQLiteRepository) -> None:
        job = _make_job()
        await repo.create_job(job)

        urls = [
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/c",
        ]
        for u in urls:
            await repo.enqueue_url(job.id, u, depth=0)

        records, cursor = await repo.get_url_records(job.id)
        assert len(records) == 3
        assert cursor is None
        retrieved_urls = {r.url for r in records}
        assert retrieved_urls == set(urls)

    @pytest.mark.anyio()
    async def test_cursor_pagination(self, repo: SQLiteRepository) -> None:
        job = _make_job()
        await repo.create_job(job)

        for i in range(5):
            await repo.enqueue_url(job.id, f"https://example.com/page{i}", depth=0)

        # First page
        page1, cursor1 = await repo.get_url_records(job.id, limit=2)
        assert len(page1) == 2
        assert cursor1 is not None

        # Second page
        page2, cursor2 = await repo.get_url_records(job.id, limit=2, cursor=cursor1)
        assert len(page2) == 2
        assert cursor2 is not None

        # Third page
        page3, cursor3 = await repo.get_url_records(job.id, limit=2, cursor=cursor2)
        assert len(page3) == 1
        assert cursor3 is None

        # Verify all 5 records retrieved
        all_urls = {r.url for r in page1 + page2 + page3}
        assert len(all_urls) == 5

    @pytest.mark.anyio()
    async def test_cursor_pagination_with_live_inserts(self, repo: SQLiteRepository) -> None:
        job = _make_job()
        await repo.create_job(job)

        await repo.enqueue_url(job.id, "https://example.com/page0", depth=0)
        await repo.enqueue_url(job.id, "https://example.com/page1", depth=0)

        page1, cursor1 = await repo.get_url_records(job.id, limit=1)
        assert [record.url for record in page1] == ["https://example.com/page0"]
        assert cursor1 is not None

        await repo.enqueue_url(job.id, "https://example.com/page2", depth=0)
        await repo.enqueue_url(job.id, "https://example.com/page3", depth=0)

        page2, cursor2 = await repo.get_url_records(job.id, limit=2, cursor=cursor1)
        assert [record.url for record in page2] == [
            "https://example.com/page1",
            "https://example.com/page2",
        ]
        assert cursor2 is not None

        page3, cursor3 = await repo.get_url_records(job.id, limit=2, cursor=cursor2)
        assert [record.url for record in page3] == ["https://example.com/page3"]
        assert cursor3 is None

    @pytest.mark.anyio()
    async def test_status_filter(self, repo: SQLiteRepository) -> None:
        job = _make_job()
        await repo.create_job(job)

        await repo.enqueue_url(job.id, "https://example.com/a", depth=0)
        await repo.enqueue_url(job.id, "https://example.com/b", depth=0)
        await repo.enqueue_url(job.id, "https://example.com/c", depth=0)

        await repo.mark_url_completed(job.id, "https://example.com/a", http_status=200, title="A")

        completed, _ = await repo.get_url_records(job.id, status=UrlStatus.COMPLETED)
        assert len(completed) == 1
        assert completed[0].url == "https://example.com/a"

        queued, _ = await repo.get_url_records(job.id, status=UrlStatus.QUEUED)
        assert len(queued) == 2

    @pytest.mark.anyio()
    async def test_empty_returns_empty_list_and_none(self, repo: SQLiteRepository) -> None:
        job = _make_job()
        await repo.create_job(job)

        records, cursor = await repo.get_url_records(job.id)
        assert records == []
        assert cursor is None


class TestUpdateUrlStatus:
    @pytest.mark.anyio()
    async def test_update_status(self, repo: SQLiteRepository) -> None:
        job = _make_job()
        await repo.create_job(job)
        await repo.enqueue_url(job.id, "https://example.com/a", depth=0)

        await repo.update_url_status(job.id, "https://example.com/a", UrlStatus.RUNNING)

        records, _ = await repo.get_url_records(job.id)
        assert records[0].status == UrlStatus.RUNNING


class TestMarkUrlCompleted:
    @pytest.mark.anyio()
    async def test_metadata_fields_set(self, repo: SQLiteRepository) -> None:
        job = _make_job()
        await repo.create_job(job)
        await repo.enqueue_url(job.id, "https://example.com/a", depth=0)

        await repo.mark_url_completed(
            job.id,
            "https://example.com/a",
            http_status=200,
            title="Page A",
            content_hash="sha256:abc123",
        )

        records, _ = await repo.get_url_records(job.id)
        rec = records[0]
        assert rec.status == UrlStatus.COMPLETED
        assert rec.http_status == 200
        assert rec.title == "Page A"
        assert rec.content_hash == "sha256:abc123"
        assert rec.completed_at is not None


class TestMarkUrlErrored:
    @pytest.mark.anyio()
    async def test_error_message_and_completed_at(self, repo: SQLiteRepository) -> None:
        job = _make_job()
        await repo.create_job(job)
        await repo.enqueue_url(job.id, "https://example.com/a", depth=0)

        await repo.mark_url_errored(job.id, "https://example.com/a", "connection timeout")

        records, _ = await repo.get_url_records(job.id)
        rec = records[0]
        assert rec.status == UrlStatus.ERRORED
        assert rec.error_message == "connection timeout"
        assert rec.completed_at is not None


class TestCancelQueuedUrls:
    @pytest.mark.anyio()
    async def test_cancels_only_queued(self, repo: SQLiteRepository) -> None:
        job = _make_job()
        await repo.create_job(job)

        await repo.enqueue_url(job.id, "https://example.com/a", depth=0)
        await repo.enqueue_url(job.id, "https://example.com/b", depth=0)
        await repo.enqueue_url(job.id, "https://example.com/c", depth=0)

        # Mark one as completed first
        await repo.mark_url_completed(job.id, "https://example.com/a", http_status=200)

        count = await repo.cancel_queued_urls(job.id)
        assert count == 2

        records, _ = await repo.get_url_records(job.id)
        statuses = {r.url: r.status for r in records}
        assert statuses["https://example.com/a"] == UrlStatus.COMPLETED
        assert statuses["https://example.com/b"] == UrlStatus.CANCELLED
        assert statuses["https://example.com/c"] == UrlStatus.CANCELLED


class TestGetJobCounts:
    @pytest.mark.anyio()
    async def test_counts_various_states(self, repo: SQLiteRepository) -> None:
        job = _make_job()
        await repo.create_job(job)

        await repo.enqueue_url(job.id, "https://example.com/a", depth=0)
        await repo.enqueue_url(job.id, "https://example.com/b", depth=0)
        await repo.enqueue_url(job.id, "https://example.com/c", depth=0)
        await repo.enqueue_url(job.id, "https://example.com/d", depth=0)

        # Mark various states
        await repo.mark_url_completed(job.id, "https://example.com/a", http_status=200)
        await repo.mark_url_errored(job.id, "https://example.com/b", "timeout")
        await repo.update_url_status(job.id, "https://example.com/c", UrlStatus.CANCELLED)
        # d stays queued

        total, finished = await repo.get_job_counts(job.id)
        assert total == 4
        # completed + errored + cancelled = 3
        assert finished == 3

    @pytest.mark.anyio()
    async def test_empty_job(self, repo: SQLiteRepository) -> None:
        job = _make_job()
        await repo.create_job(job)

        total, finished = await repo.get_job_counts(job.id)
        assert total == 0
        assert finished == 0


# ---------------------------------------------------------------------------
# Lifecycle and pragmas
# ---------------------------------------------------------------------------


class TestWalMode:
    @pytest.mark.anyio()
    async def test_journal_mode_is_wal(self, repo: SQLiteRepository) -> None:
        db = repo._conn()
        cursor = await db.execute("PRAGMA journal_mode")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "wal"


class TestForeignKeys:
    @pytest.mark.anyio()
    async def test_enqueue_url_with_nonexistent_job_raises(self, repo: SQLiteRepository) -> None:
        with pytest.raises(CrawlerError):
            await repo.enqueue_url("nonexistent-job", "https://example.com/page", depth=0)


# ---------------------------------------------------------------------------
# _conn() guard
# ---------------------------------------------------------------------------


class TestConnGuard:
    def test_conn_before_initialise_raises(self, tmp_path: Path) -> None:
        """Calling _conn() before initialise() raises CrawlerError."""
        r = SQLiteRepository(tmp_path / "uninitialised.db")
        with pytest.raises(CrawlerError, match="not been initialised"):
            r._conn()


# ---------------------------------------------------------------------------
# Lifecycle error handling
# ---------------------------------------------------------------------------


class TestInitialiseError:
    @pytest.mark.anyio()
    async def test_initialise_failure_raises_crawler_error(self, tmp_path: Path) -> None:
        """When aiosqlite.connect fails, initialise() wraps it in CrawlerError."""
        r = SQLiteRepository(tmp_path / "bad.db")
        with (
            patch("proctx_crawler.infrastructure.sqlite_repository.aiosqlite") as mock_sqlite,
            pytest.raises(CrawlerError, match="Failed to initialise"),
        ):
            mock_sqlite.connect.side_effect = Exception("disk full")
            mock_sqlite.Error = Exception
            await r.initialise()

    @pytest.mark.anyio()
    async def test_initialise_creates_missing_parent_directories(self, tmp_path: Path) -> None:
        """First-run with a nested db_path must create parent dirs, not fail."""
        nested = tmp_path / "does" / "not" / "exist" / "crawler.db"
        assert not nested.parent.exists()

        r = SQLiteRepository(nested)
        await r.initialise()
        try:
            assert nested.parent.exists()
            assert nested.exists()
        finally:
            await r.close()

    @pytest.mark.anyio()
    async def test_initialise_wraps_mkdir_oserror(self, tmp_path: Path) -> None:
        """When parent dir cannot be created, initialise() still raises CrawlerError."""
        # Create a file where the parent directory would need to be — mkdir then
        # raises NotADirectoryError (an OSError subclass).
        blocker = tmp_path / "blocker"
        blocker.write_text("not a dir")

        r = SQLiteRepository(blocker / "sub" / "crawler.db")
        with pytest.raises(CrawlerError, match="Failed to initialise"):
            await r.initialise()


class TestCloseError:
    @pytest.mark.anyio()
    async def test_close_swallows_error_and_resets(self, tmp_path: Path) -> None:
        """When _db.close() raises, close() logs it and still sets _db to None."""
        r = SQLiteRepository(tmp_path / "test.db")
        await r.initialise()

        # Capture the real close before patching so we can shut the worker
        # thread down cleanly after the assertion. Without this, aiosqlite's
        # background thread remains alive and can emit a spurious
        # "Event loop is closed" warning during session finalisation.
        real_close = r._db.close  # type: ignore[union-attr]
        r._db.close = AsyncMock(side_effect=aiosqlite.Error("close failed"))  # type: ignore[union-attr]

        await r.close()  # Should not raise
        assert r._db is None

        await real_close()


# ---------------------------------------------------------------------------
# CRUD error handling (mock _db to raise aiosqlite.Error)
#
# These tests assert that infrastructure errors from aiosqlite are wrapped in
# our domain CrawlerError. They do NOT use the ``repo`` fixture because it
# opens a real aiosqlite connection whose background worker thread can emit
# a spurious "Event loop is closed" warning during session finalisation when
# execute() is patched. Using an isolated repo with a fully-mocked ``_db``
# sidesteps the worker thread entirely.
# ---------------------------------------------------------------------------


def _errored_repo(tmp_path: Path, message: str) -> SQLiteRepository:
    """Build a repo whose ``_db.execute`` raises aiosqlite.Error.

    Avoids creating a real aiosqlite connection so no worker thread is spawned.
    """
    repo = SQLiteRepository(tmp_path / "test.db")
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=aiosqlite.Error(message))
    db.commit = AsyncMock()
    repo._db = db
    return repo


class TestCreateJobError:
    @pytest.mark.anyio()
    async def test_create_job_db_error(self, tmp_path: Path) -> None:
        """aiosqlite.Error during create_job is wrapped in CrawlerError."""
        repo = _errored_repo(tmp_path, "write failed")

        with pytest.raises(CrawlerError, match="Failed to create job"):
            await repo.create_job(_make_job())


class TestGetJobError:
    @pytest.mark.anyio()
    async def test_get_job_db_error(self, tmp_path: Path) -> None:
        repo = _errored_repo(tmp_path, "read failed")

        with pytest.raises(CrawlerError, match="Failed to get job"):
            await repo.get_job("job-1")


class TestUpdateJobStatusError:
    @pytest.mark.anyio()
    async def test_update_job_status_db_error(self, tmp_path: Path) -> None:
        repo = _errored_repo(tmp_path, "write failed")

        with pytest.raises(CrawlerError, match="Failed to update job"):
            await repo.update_job_status("job-1", JobStatus.RUNNING)


class TestUpdateJobCountsError:
    @pytest.mark.anyio()
    async def test_update_job_counts_db_error(self, tmp_path: Path) -> None:
        repo = _errored_repo(tmp_path, "write failed")

        with pytest.raises(CrawlerError, match="Failed to update job"):
            await repo.update_job_counts("job-1", total=5, finished=2)


class TestIsJobCancelledError:
    @pytest.mark.anyio()
    async def test_is_job_cancelled_db_error(self, tmp_path: Path) -> None:
        repo = _errored_repo(tmp_path, "read failed")

        with pytest.raises(CrawlerError, match="Failed to check cancellation"):
            await repo.is_job_cancelled("job-1")


class TestEnqueueUrlError:
    @pytest.mark.anyio()
    async def test_enqueue_url_db_error(self, tmp_path: Path) -> None:
        repo = _errored_repo(tmp_path, "write failed")

        with pytest.raises(CrawlerError, match="Failed to enqueue URL"):
            await repo.enqueue_url("job-1", "https://example.com/page", depth=0)


class TestGetUrlRecordsError:
    @pytest.mark.anyio()
    async def test_get_url_records_db_error(self, tmp_path: Path) -> None:
        repo = _errored_repo(tmp_path, "read failed")

        with pytest.raises(CrawlerError, match="Failed to get URL records"):
            await repo.get_url_records("job-1")


class TestUpdateUrlStatusError:
    @pytest.mark.anyio()
    async def test_update_url_status_db_error(self, tmp_path: Path) -> None:
        repo = _errored_repo(tmp_path, "write failed")

        with pytest.raises(CrawlerError, match="Failed to update URL"):
            await repo.update_url_status("job-1", "https://example.com/a", UrlStatus.RUNNING)


class TestMarkUrlCompletedError:
    @pytest.mark.anyio()
    async def test_mark_url_completed_db_error(self, tmp_path: Path) -> None:
        repo = _errored_repo(tmp_path, "write failed")

        with pytest.raises(CrawlerError, match="Failed to mark URL"):
            await repo.mark_url_completed("job-1", "https://example.com/a", http_status=200)


class TestMarkUrlErroredError:
    @pytest.mark.anyio()
    async def test_mark_url_errored_db_error(self, tmp_path: Path) -> None:
        repo = _errored_repo(tmp_path, "write failed")

        with pytest.raises(CrawlerError, match="Failed to mark URL"):
            await repo.mark_url_errored("job-1", "https://example.com/a", "timeout")


class TestCancelQueuedUrlsError:
    @pytest.mark.anyio()
    async def test_cancel_queued_urls_db_error(self, tmp_path: Path) -> None:
        repo = _errored_repo(tmp_path, "write failed")

        with pytest.raises(CrawlerError, match="Failed to cancel queued URLs"):
            await repo.cancel_queued_urls("job-1")


class TestGetJobCountsError:
    @pytest.mark.anyio()
    async def test_get_job_counts_db_error(self, tmp_path: Path) -> None:
        repo = _errored_repo(tmp_path, "read failed")

        with pytest.raises(CrawlerError, match="Failed to get job counts"):
            await repo.get_job_counts("job-1")
