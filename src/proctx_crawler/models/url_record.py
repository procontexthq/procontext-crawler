"""URL record models for tracking individual page crawl status."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class UrlStatus(StrEnum):
    """Possible states of a URL within a crawl job."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    ERRORED = "errored"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    DISALLOWED = "disallowed"


class UrlRecord(BaseModel):
    """A single URL entry within a crawl job."""

    id: str
    job_id: str
    url: str
    url_hash: str
    depth: int
    status: UrlStatus = UrlStatus.QUEUED
    http_status: int | None = None
    error_message: str | None = None
    content_hash: str | None = None
    title: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
