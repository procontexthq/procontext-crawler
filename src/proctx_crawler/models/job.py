"""Job lifecycle models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from proctx_crawler.models.input import CrawlConfig


class JobStatus(StrEnum):
    """Possible states of a crawl job."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERRORED = "errored"


class Job(BaseModel):
    """A crawl job tracking progress and configuration."""

    id: str
    status: JobStatus = JobStatus.QUEUED
    url: str
    config: CrawlConfig
    total: int = 0
    finished: int = 0
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
