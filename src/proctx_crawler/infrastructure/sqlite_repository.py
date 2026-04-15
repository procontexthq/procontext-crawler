"""SQLite-backed implementation of the Repository protocol."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import aiosqlite
import structlog

from proctx_crawler.core.url_utils import url_hash
from proctx_crawler.models import (
    CrawlConfig,
    CrawlerError,
    ErrorCode,
    Job,
    JobStatus,
    UrlRecord,
    UrlStatus,
)

if TYPE_CHECKING:
    from pathlib import Path

log: structlog.stdlib.BoundLogger = structlog.get_logger()

_SCHEMA_DDL = """\
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    status      TEXT NOT NULL DEFAULT 'queued',
    url         TEXT NOT NULL,
    config      TEXT NOT NULL,
    total       INTEGER NOT NULL DEFAULT 0,
    finished    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS url_records (
    id            TEXT PRIMARY KEY,
    job_id        TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    url           TEXT NOT NULL,
    url_hash      TEXT NOT NULL,
    depth         INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'queued',
    http_status   INTEGER,
    error_message TEXT,
    content_hash  TEXT,
    title         TEXT,
    created_at    TEXT NOT NULL,
    completed_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_url_records_job_id ON url_records(job_id);
CREATE INDEX IF NOT EXISTS idx_url_records_job_status ON url_records(job_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_url_records_job_url ON url_records(job_id, url);
"""

_TERMINAL_JOB_STATUSES = frozenset(
    {
        JobStatus.COMPLETED,
        JobStatus.CANCELLED,
        JobStatus.ERRORED,
    }
)

_TERMINAL_URL_STATUSES = frozenset(
    {
        UrlStatus.COMPLETED,
        UrlStatus.ERRORED,
        UrlStatus.SKIPPED,
        UrlStatus.CANCELLED,
    }
)


def _encode_cursor(last_rowid: int) -> str:
    """Encode the last seen insertion-order position into an opaque cursor string."""
    return base64.urlsafe_b64encode(json.dumps({"rowid": last_rowid}).encode()).decode()


def _decode_cursor(cursor: str) -> int:
    """Decode an opaque cursor string back to the last seen insertion-order position."""
    return int(json.loads(base64.urlsafe_b64decode(cursor))["rowid"])  # type: ignore[no-any-return]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _row_to_job(row: aiosqlite.Row) -> Job:
    return Job(
        id=row["id"],
        status=JobStatus(row["status"]),
        url=row["url"],
        config=CrawlConfig.model_validate_json(row["config"]),
        total=row["total"],
        finished=row["finished"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        started_at=_parse_dt(row["started_at"]),
        finished_at=_parse_dt(row["finished_at"]),
    )


def _row_to_url_record(row: aiosqlite.Row) -> UrlRecord:
    return UrlRecord(
        id=row["id"],
        job_id=row["job_id"],
        url=row["url"],
        url_hash=row["url_hash"],
        depth=row["depth"],
        status=UrlStatus(row["status"]),
        http_status=row["http_status"],
        error_message=row["error_message"],
        content_hash=row["content_hash"],
        title=row["title"],
        created_at=datetime.fromisoformat(row["created_at"]),
        completed_at=_parse_dt(row["completed_at"]),
    )


class SQLiteRepository:
    """SQLite implementation of the Repository protocol.

    Uses WAL journal mode for concurrent reads and writes.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    def _conn(self) -> aiosqlite.Connection:
        """Return the active database connection, raising if not initialised."""
        if self._db is None:
            raise CrawlerError(
                ErrorCode.FETCH_FAILED,
                "SQLiteRepository has not been initialised",
            )
        return self._db

    # -- Lifecycle ------------------------------------------------------------

    async def initialise(self) -> None:
        """Open the database, enable WAL mode and foreign keys, create tables."""
        try:
            # SQLite does not create parent directories; ensure the platformdirs
            # data dir exists on first run before attempting to connect.
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db = await aiosqlite.connect(self._db_path)
            self._db.row_factory = aiosqlite.Row
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA foreign_keys=ON")
            await self._db.executescript(_SCHEMA_DDL)
            await self._db.commit()
        except (aiosqlite.Error, OSError):
            log.error("sqlite_initialise_failed", db_path=str(self._db_path), exc_info=True)
            raise CrawlerError(
                ErrorCode.FETCH_FAILED,
                "Failed to initialise SQLite repository",
            ) from None

    async def close(self) -> None:
        """Close the database connection."""
        if self._db is not None:
            try:
                await self._db.close()
            except aiosqlite.Error:
                log.warning("sqlite_close_failed", exc_info=True)
            finally:
                self._db = None

    # -- Job operations -------------------------------------------------------

    async def create_job(self, job: Job) -> None:
        """Persist a new crawl job."""
        try:
            await self._conn().execute(
                """
                INSERT INTO jobs (id, status, url, config, total, finished,
                                  created_at, updated_at, started_at, finished_at)
                VALUES (:id, :status, :url, :config, :total, :finished,
                        :created_at, :updated_at, :started_at, :finished_at)
                """,
                {
                    "id": job.id,
                    "status": job.status.value,
                    "url": job.url,
                    "config": job.config.model_dump_json(),
                    "total": job.total,
                    "finished": job.finished,
                    "created_at": job.created_at.isoformat(),
                    "updated_at": job.updated_at.isoformat(),
                    "started_at": job.started_at.isoformat() if job.started_at else None,
                    "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                },
            )
            await self._conn().commit()
        except aiosqlite.Error:
            log.error("sqlite_create_job_failed", job_id=job.id, exc_info=True)
            raise CrawlerError(
                ErrorCode.FETCH_FAILED,
                f"Failed to create job {job.id}",
            ) from None

    async def get_job(self, job_id: str) -> Job | None:
        """Return the job with the given ID, or ``None`` if it does not exist."""
        try:
            cursor = await self._conn().execute("SELECT * FROM jobs WHERE id = :id", {"id": job_id})
            row = await cursor.fetchone()
            if row is None:
                return None
            return _row_to_job(row)
        except aiosqlite.Error:
            log.error("sqlite_get_job_failed", job_id=job_id, exc_info=True)
            raise CrawlerError(
                ErrorCode.FETCH_FAILED,
                f"Failed to get job {job_id}",
            ) from None

    async def update_job_status(self, job_id: str, status: JobStatus) -> None:
        """Transition a job to *status*, updating timestamps accordingly."""
        now = _now_iso()
        try:
            if status in _TERMINAL_JOB_STATUSES:
                await self._conn().execute(
                    """
                    UPDATE jobs SET status = :status, updated_at = :now, finished_at = :now
                    WHERE id = :id
                    """,
                    {"status": status.value, "now": now, "id": job_id},
                )
            else:
                await self._conn().execute(
                    "UPDATE jobs SET status = :status, updated_at = :now WHERE id = :id",
                    {"status": status.value, "now": now, "id": job_id},
                )
            await self._conn().commit()
        except aiosqlite.Error:
            log.error(
                "sqlite_update_job_status_failed",
                job_id=job_id,
                status=status,
                exc_info=True,
            )
            raise CrawlerError(
                ErrorCode.FETCH_FAILED,
                f"Failed to update job {job_id} status to {status}",
            ) from None

    async def update_job_counts(self, job_id: str, total: int, finished: int) -> None:
        """Set the *total* and *finished* counters on a job."""
        try:
            await self._conn().execute(
                """
                UPDATE jobs SET total = :total, finished = :finished, updated_at = :now
                WHERE id = :id
                """,
                {"total": total, "finished": finished, "now": _now_iso(), "id": job_id},
            )
            await self._conn().commit()
        except aiosqlite.Error:
            log.error("sqlite_update_job_counts_failed", job_id=job_id, exc_info=True)
            raise CrawlerError(
                ErrorCode.FETCH_FAILED,
                f"Failed to update job {job_id} counts",
            ) from None

    async def is_job_cancelled(self, job_id: str) -> bool:
        """Return ``True`` if the job has been cancelled."""
        try:
            cursor = await self._conn().execute(
                "SELECT status FROM jobs WHERE id = :id", {"id": job_id}
            )
            row = await cursor.fetchone()
            if row is None:
                return False
            return row["status"] == JobStatus.CANCELLED.value
        except aiosqlite.Error:
            log.error("sqlite_is_job_cancelled_failed", job_id=job_id, exc_info=True)
            raise CrawlerError(
                ErrorCode.FETCH_FAILED,
                f"Failed to check cancellation for job {job_id}",
            ) from None

    # -- URL record operations ------------------------------------------------

    async def enqueue_url(self, job_id: str, url: str, depth: int) -> None:
        """Insert a new URL record in *queued* state for the given job."""
        record_id = str(uuid.uuid4())
        try:
            await self._conn().execute(
                """
                INSERT INTO url_records (id, job_id, url, url_hash, depth, status, created_at)
                VALUES (:id, :job_id, :url, :url_hash, :depth, :status, :created_at)
                """,
                {
                    "id": record_id,
                    "job_id": job_id,
                    "url": url,
                    "url_hash": url_hash(url),
                    "depth": depth,
                    "status": UrlStatus.QUEUED.value,
                    "created_at": _now_iso(),
                },
            )
            await self._conn().commit()
        except aiosqlite.Error:
            log.error("sqlite_enqueue_url_failed", job_id=job_id, url=url, exc_info=True)
            raise CrawlerError(
                ErrorCode.FETCH_FAILED,
                f"Failed to enqueue URL {url} for job {job_id}",
            ) from None

    async def get_url_records(
        self,
        job_id: str,
        *,
        limit: int = 100,
        cursor: str | None = None,
        status: UrlStatus | None = None,
    ) -> tuple[list[UrlRecord], str | None]:
        """Return paginated URL records, optionally filtered by *status*."""
        try:
            conditions = ["job_id = :job_id"]
            params: dict[str, str | int] = {"job_id": job_id, "limit": limit}

            if cursor is not None:
                last_rowid = _decode_cursor(cursor)
                conditions.append("rowid > :cursor_rowid")
                params["cursor_rowid"] = last_rowid

            if status is not None:
                conditions.append("status = :status")
                params["status"] = status.value

            where_clause = " AND ".join(conditions)
            query = (
                "SELECT rowid AS _cursor_rowid, * "
                f"FROM url_records WHERE {where_clause} ORDER BY rowid LIMIT :limit"
            )

            db_cursor = await self._conn().execute(query, params)
            rows = list(await db_cursor.fetchall())

            records = [_row_to_url_record(row) for row in rows]

            next_cursor: str | None = None
            if len(records) == limit:
                next_cursor = _encode_cursor(rows[-1]["_cursor_rowid"])

            return records, next_cursor
        except aiosqlite.Error:
            log.error("sqlite_get_url_records_failed", job_id=job_id, exc_info=True)
            raise CrawlerError(
                ErrorCode.FETCH_FAILED,
                f"Failed to get URL records for job {job_id}",
            ) from None

    async def update_url_status(self, job_id: str, url: str, status: UrlStatus) -> None:
        """Update the status of a single URL record."""
        try:
            await self._conn().execute(
                "UPDATE url_records SET status = :status WHERE job_id = :job_id AND url = :url",
                {"status": status.value, "job_id": job_id, "url": url},
            )
            await self._conn().commit()
        except aiosqlite.Error:
            log.error(
                "sqlite_update_url_status_failed",
                job_id=job_id,
                url=url,
                status=status,
                exc_info=True,
            )
            raise CrawlerError(
                ErrorCode.FETCH_FAILED,
                f"Failed to update URL {url} status for job {job_id}",
            ) from None

    async def mark_url_completed(
        self,
        job_id: str,
        url: str,
        *,
        http_status: int,
        title: str | None = None,
        content_hash: str | None = None,
    ) -> None:
        """Mark a URL as completed with its result metadata."""
        now = _now_iso()
        try:
            await self._conn().execute(
                """
                UPDATE url_records
                SET status = :status, http_status = :http_status, title = :title,
                    content_hash = :content_hash, completed_at = :completed_at
                WHERE job_id = :job_id AND url = :url
                """,
                {
                    "status": UrlStatus.COMPLETED.value,
                    "http_status": http_status,
                    "title": title,
                    "content_hash": content_hash,
                    "completed_at": now,
                    "job_id": job_id,
                    "url": url,
                },
            )
            await self._conn().commit()
        except aiosqlite.Error:
            log.error(
                "sqlite_mark_url_completed_failed",
                job_id=job_id,
                url=url,
                exc_info=True,
            )
            raise CrawlerError(
                ErrorCode.FETCH_FAILED,
                f"Failed to mark URL {url} as completed for job {job_id}",
            ) from None

    async def mark_url_errored(self, job_id: str, url: str, error: str) -> None:
        """Mark a URL as errored with the error message."""
        now = _now_iso()
        try:
            await self._conn().execute(
                """
                UPDATE url_records
                SET status = :status, error_message = :error, completed_at = :completed_at
                WHERE job_id = :job_id AND url = :url
                """,
                {
                    "status": UrlStatus.ERRORED.value,
                    "error": error,
                    "completed_at": now,
                    "job_id": job_id,
                    "url": url,
                },
            )
            await self._conn().commit()
        except aiosqlite.Error:
            log.error(
                "sqlite_mark_url_errored_failed",
                job_id=job_id,
                url=url,
                exc_info=True,
            )
            raise CrawlerError(
                ErrorCode.FETCH_FAILED,
                f"Failed to mark URL {url} as errored for job {job_id}",
            ) from None

    async def cancel_queued_urls(self, job_id: str) -> int:
        """Cancel all queued URLs for a job.  Return the number of rows affected."""
        try:
            cursor = await self._conn().execute(
                """
                UPDATE url_records SET status = :cancelled
                WHERE job_id = :job_id AND status = :queued
                """,
                {
                    "cancelled": UrlStatus.CANCELLED.value,
                    "job_id": job_id,
                    "queued": UrlStatus.QUEUED.value,
                },
            )
            await self._conn().commit()
            return cursor.rowcount
        except aiosqlite.Error:
            log.error("sqlite_cancel_queued_urls_failed", job_id=job_id, exc_info=True)
            raise CrawlerError(
                ErrorCode.FETCH_FAILED,
                f"Failed to cancel queued URLs for job {job_id}",
            ) from None

    async def get_job_counts(self, job_id: str) -> tuple[int, int]:
        """Return ``(total, finished)`` counts for a job's URL records."""
        terminal_statuses = tuple(s.value for s in _TERMINAL_URL_STATUSES)
        placeholders = ", ".join(f":s{i}" for i in range(len(terminal_statuses)))
        try:
            # Total count
            total_cursor = await self._conn().execute(
                "SELECT COUNT(*) FROM url_records WHERE job_id = :job_id",
                {"job_id": job_id},
            )
            total_row = await total_cursor.fetchone()
            total = total_row[0] if total_row else 0

            # Finished count
            params: dict[str, str] = {"job_id": job_id}
            for i, s in enumerate(terminal_statuses):
                params[f"s{i}"] = s
            finished_cursor = await self._conn().execute(
                f"SELECT COUNT(*) FROM url_records "
                f"WHERE job_id = :job_id AND status IN ({placeholders})",
                params,
            )
            finished_row = await finished_cursor.fetchone()
            finished = finished_row[0] if finished_row else 0

            return total, finished
        except aiosqlite.Error:
            log.error("sqlite_get_job_counts_failed", job_id=job_id, exc_info=True)
            raise CrawlerError(
                ErrorCode.FETCH_FAILED,
                f"Failed to get job counts for job {job_id}",
            ) from None
