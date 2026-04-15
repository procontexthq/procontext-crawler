"""Crawl-job orchestration shared by the Python and HTTP APIs.

This module owns job construction, URL-record materialisation, and the
full-result collection loop. Both the ``Crawler`` class and the HTTP
route handlers delegate here; scheduling (blocking ``await`` vs
``task_group.start_soon``) stays with each caller.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from proctx_crawler.models import (
    CrawlRecord,
    CrawlResult,
    Job,
    JobStatus,
    RecordMetadata,
    UrlStatus,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from proctx_crawler.core.repository import Repository
    from proctx_crawler.infrastructure.content_storage import ContentStorage
    from proctx_crawler.models import CrawlConfig, UrlRecord


async def build_and_persist_job(url: str, config: CrawlConfig, repo: Repository) -> Job:
    """Construct a ``Job`` (new UUID, current timestamps) and persist it."""
    now = datetime.now(UTC)
    job = Job(
        id=str(uuid.uuid4()),
        url=url,
        config=config,
        created_at=now,
        updated_at=now,
    )
    await repo.create_job(job)
    return job


async def url_record_to_crawl_record(
    job_id: str,
    rec: UrlRecord,
    storage: ContentStorage,
    formats: Sequence[str],
) -> CrawlRecord:
    """Materialise a ``CrawlRecord`` by reading requested formats from storage."""
    md_content: str | None = None
    html_content: str | None = None
    metadata: RecordMetadata | None = None

    if rec.status == UrlStatus.COMPLETED:
        if "markdown" in formats:
            md_content = await storage.read(job_id, rec.url, "markdown")
        if "html" in formats:
            html_content = await storage.read(job_id, rec.url, "html")
        metadata = RecordMetadata(
            http_status=rec.http_status or 0,
            title=rec.title,
            content_hash=rec.content_hash,
        )

    return CrawlRecord(
        url=rec.url,
        status=rec.status,
        markdown=md_content,
        html=html_content,
        metadata=metadata,
    )


async def collect_crawl_result(
    job_id: str,
    repo: Repository,
    storage: ContentStorage,
    formats: Sequence[str],
) -> CrawlResult:
    """Paginate through all URL records and return a fully-materialised result."""
    final_job = await repo.get_job(job_id)
    status = final_job.status if final_job else JobStatus.ERRORED
    total = final_job.total if final_job else 0
    finished = final_job.finished if final_job else 0

    all_records: list[CrawlRecord] = []
    cursor: str | None = None
    while True:
        url_records, next_cursor = await repo.get_url_records(job_id, limit=100, cursor=cursor)
        if not url_records:
            break
        for rec in url_records:
            all_records.append(await url_record_to_crawl_record(job_id, rec, storage, formats))
        cursor = next_cursor
        if cursor is None:
            break

    return CrawlResult(
        id=job_id,
        status=status,
        total=total,
        finished=finished,
        records=all_records,
        cursor=None,
    )
