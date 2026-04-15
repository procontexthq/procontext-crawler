"""API output models for crawl results and success responses."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from proctx_crawler.models.job import JobStatus
from proctx_crawler.models.url_record import UrlStatus


class RecordMetadata(BaseModel):
    """Metadata for a single crawled page."""

    http_status: int
    title: str | None = None
    content_hash: str | None = None


class CrawlRecord(BaseModel):
    """A single page result within a crawl job response."""

    url: str
    status: UrlStatus
    markdown: str | None = None
    html: str | None = None
    metadata: RecordMetadata | None = None


class CrawlResult(BaseModel):
    """Aggregated crawl job result returned by GET /crawl."""

    id: str
    status: JobStatus
    total: int
    finished: int
    records: list[CrawlRecord]
    cursor: str | None = None


class SuccessResponse[T](BaseModel):
    """Generic envelope for successful API responses."""

    success: Literal[True] = True
    result: T
