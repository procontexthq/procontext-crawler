"""HTTP route handlers for the crawler API."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, NoReturn

import structlog
from fastapi import APIRouter, Query, Request

from proctx_crawler.core.engine import run_crawl
from proctx_crawler.core.fetcher import fetch_static
from proctx_crawler.core.renderer import fetch_rendered
from proctx_crawler.core.url_utils import is_same_domain
from proctx_crawler.extractors import extract_html, extract_links, html_to_markdown
from proctx_crawler.models import (
    CrawlConfig,
    CrawlRecord,
    CrawlResult,
    ErrorCode,
    Job,
    JobNotFoundError,
    JobStatus,
    LinksInput,
    RecordMetadata,
    SinglePageInput,
    SuccessResponse,
    UrlRecord,
    UrlStatus,
)

if TYPE_CHECKING:
    from proctx_crawler.core.browser_pool import BrowserPool
    from proctx_crawler.infrastructure.content_storage import ContentStorage
    from proctx_crawler.infrastructure.sqlite_repository import SQLiteRepository

log: structlog.stdlib.BoundLogger = structlog.get_logger()

router = APIRouter()

_TERMINAL_STATUSES = frozenset({JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.ERRORED})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _repo(request: Request) -> SQLiteRepository:
    return request.app.state.repo  # type: ignore[no-any-return]


def _storage(request: Request) -> ContentStorage:
    return request.app.state.storage  # type: ignore[no-any-return]


def _browser_pool(request: Request) -> BrowserPool:
    return request.app.state.browser_pool  # type: ignore[no-any-return]


def _raise_job_not_found(job_id: str) -> NoReturn:
    raise JobNotFoundError(
        code=ErrorCode.JOB_NOT_FOUND,
        message=f"Job {job_id} not found",
        recoverable=False,
    )


async def _url_record_to_crawl_record(
    job_id: str,
    rec: UrlRecord,
    storage: ContentStorage,
    formats: list[str],
) -> CrawlRecord:
    """Convert a UrlRecord into a CrawlRecord, reading content from storage."""
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


# ---------------------------------------------------------------------------
# POST /crawl — Start crawl job
# ---------------------------------------------------------------------------


@router.post("/crawl")
async def start_crawl(config: CrawlConfig, request: Request) -> SuccessResponse[str]:
    """Create a new crawl job and start it in the background."""
    repo = _repo(request)
    storage = _storage(request)
    browser_pool = _browser_pool(request)

    now = datetime.now(UTC)
    job_id = str(uuid.uuid4())
    job = Job(
        id=job_id,
        url=config.url,
        config=config,
        created_at=now,
        updated_at=now,
    )
    await repo.create_job(job)

    pool = browser_pool if config.render else None
    request.app.state.task_group.start_soon(run_crawl, job, repo, storage, pool)

    log.info("crawl_job_created", job_id=job_id, url=config.url)
    return SuccessResponse(result=job_id)


# ---------------------------------------------------------------------------
# GET /crawl — Poll status / retrieve results
# ---------------------------------------------------------------------------


@router.get("/crawl")
async def get_crawl(
    request: Request,
    id: Annotated[str, Query()],  # noqa: A002
    limit: Annotated[int, Query(ge=0)] = 100,
    cursor: Annotated[str | None, Query()] = None,
    status: Annotated[UrlStatus | None, Query()] = None,
) -> SuccessResponse[CrawlResult]:
    """Return the current status and paginated records for a crawl job."""
    repo = _repo(request)
    storage = _storage(request)

    job = await repo.get_job(id)
    if job is None:
        _raise_job_not_found(id)

    if limit == 0:
        return SuccessResponse(
            result=CrawlResult(
                id=id,
                status=job.status,
                total=job.total,
                finished=job.finished,
                records=[],
                cursor=None,
            )
        )

    url_records, next_cursor = await repo.get_url_records(
        id, limit=limit, cursor=cursor, status=status
    )

    formats = [f for f in job.config.formats]
    records = [await _url_record_to_crawl_record(id, rec, storage, formats) for rec in url_records]

    return SuccessResponse(
        result=CrawlResult(
            id=id,
            status=job.status,
            total=job.total,
            finished=job.finished,
            records=records,
            cursor=next_cursor,
        )
    )


# ---------------------------------------------------------------------------
# DELETE /crawl — Cancel job
# ---------------------------------------------------------------------------


@router.delete("/crawl")
async def cancel_crawl(
    request: Request,
    id: Annotated[str, Query()],  # noqa: A002
) -> SuccessResponse[str]:
    """Cancel a running crawl job (idempotent for terminal jobs)."""
    repo = _repo(request)

    job = await repo.get_job(id)
    if job is None:
        _raise_job_not_found(id)

    if job.status in _TERMINAL_STATUSES:
        return SuccessResponse(result="cancelled")

    await repo.cancel_queued_urls(id)
    await repo.update_job_status(id, JobStatus.CANCELLED)
    log.info("crawl_job_cancelled", job_id=id)
    return SuccessResponse(result="cancelled")


# ---------------------------------------------------------------------------
# POST /markdown — Single-page Markdown
# ---------------------------------------------------------------------------


@router.post("/markdown")
async def get_markdown(body: SinglePageInput, request: Request) -> SuccessResponse[str]:
    """Fetch a single page and convert to Markdown, or convert provided HTML directly."""
    if body.html is not None:
        md = html_to_markdown(body.html)
        return SuccessResponse(result=md)

    assert body.url is not None  # guaranteed by model validator
    result = await _fetch_single_page(body, request)
    md = html_to_markdown(result)
    return SuccessResponse(result=md)


# ---------------------------------------------------------------------------
# POST /content — Single-page HTML
# ---------------------------------------------------------------------------


@router.post("/content")
async def get_content(body: SinglePageInput, request: Request) -> SuccessResponse[str]:
    """Fetch a single page and return its HTML."""
    if body.html is not None:
        return SuccessResponse(result=extract_html(body.html))

    assert body.url is not None  # guaranteed by model validator
    html = await _fetch_single_page(body, request)
    return SuccessResponse(result=extract_html(html))


# ---------------------------------------------------------------------------
# POST /links — Extract links
# ---------------------------------------------------------------------------


@router.post("/links")
async def get_links(body: LinksInput, request: Request) -> SuccessResponse[list[str]]:
    """Fetch a page and extract all links."""
    assert body.url is not None  # LinksInput requires url (no html-only mode for links)
    html = await _fetch_single_page(body, request)
    all_links = extract_links(html, body.url)
    if body.exclude_external_links:
        all_links = [link for link in all_links if is_same_domain(link, body.url)]
    return SuccessResponse(result=all_links)


# ---------------------------------------------------------------------------
# Internal fetch helper
# ---------------------------------------------------------------------------


async def _fetch_single_page(body: SinglePageInput, request: Request) -> str:
    """Fetch a page via static or rendered path, returning the HTML string."""
    assert body.url is not None
    if body.render:
        pool = _browser_pool(request)
        result = await fetch_rendered(
            body.url,
            pool,
            goto_options=body.goto_options,
            wait_for_selector=body.wait_for_selector,
            reject_resource_types=body.reject_resource_types,
        )
    else:
        result = await fetch_static(body.url)
    return result.html
