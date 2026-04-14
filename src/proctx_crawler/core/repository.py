"""Repository protocol defining the persistence contract for crawl jobs and URL records."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from proctx_crawler.models import Job, JobStatus, UrlRecord, UrlStatus


@runtime_checkable
class Repository(Protocol):
    """Persistence interface for crawl jobs and URL records.

    Business logic imports only this protocol — never a concrete implementation.
    """

    # -- Job operations -------------------------------------------------------

    async def create_job(self, job: Job) -> None:
        """Persist a new crawl job."""
        ...

    async def get_job(self, job_id: str) -> Job | None:
        """Return the job with the given ID, or ``None`` if it does not exist."""
        ...

    async def update_job_status(self, job_id: str, status: JobStatus) -> None:
        """Transition a job to *status*, updating timestamps accordingly."""
        ...

    async def update_job_counts(self, job_id: str, total: int, finished: int) -> None:
        """Set the *total* and *finished* counters on a job."""
        ...

    async def is_job_cancelled(self, job_id: str) -> bool:
        """Return ``True`` if the job has been cancelled."""
        ...

    # -- URL record operations ------------------------------------------------

    async def enqueue_url(self, job_id: str, url: str, depth: int) -> None:
        """Insert a new URL record in *queued* state for the given job."""
        ...

    async def get_url_records(
        self,
        job_id: str,
        *,
        limit: int = 100,
        cursor: str | None = None,
        status: UrlStatus | None = None,
    ) -> tuple[list[UrlRecord], str | None]:
        """Return paginated URL records, optionally filtered by *status*.

        Returns a ``(records, next_cursor)`` tuple.  *next_cursor* is ``None``
        when there are no more pages.
        """
        ...

    async def update_url_status(self, job_id: str, url: str, status: UrlStatus) -> None:
        """Update the status of a single URL record."""
        ...

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
        ...

    async def mark_url_errored(self, job_id: str, url: str, error: str) -> None:
        """Mark a URL as errored with the error message."""
        ...

    async def cancel_queued_urls(self, job_id: str) -> int:
        """Cancel all queued URLs for a job.  Return the number of rows affected."""
        ...

    async def get_job_counts(self, job_id: str) -> tuple[int, int]:
        """Return ``(total, finished)`` counts for a job's URL records.

        *total* is the total number of URL records.  *finished* counts records
        with a terminal status (completed, errored, skipped, or cancelled).
        """
        ...

    # -- Lifecycle ------------------------------------------------------------

    async def initialise(self) -> None:
        """Prepare the repository (create tables, open connections, etc.)."""
        ...

    async def close(self) -> None:
        """Release all resources held by the repository."""
        ...
