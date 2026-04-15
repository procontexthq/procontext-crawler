"""HTTP route handlers for the crawler API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, NoReturn

import structlog
from fastapi import APIRouter, Query, Request

from proctx_crawler.core.crawl_service import (
    build_and_persist_job,
    url_record_to_crawl_record,
)
from proctx_crawler.core.engine import run_crawl
from proctx_crawler.core.page_service import fetch_page_html
from proctx_crawler.core.renderer import extract_visible_links_rendered
from proctx_crawler.core.url_utils import is_same_domain
from proctx_crawler.extractors import extract_html, extract_links, html_to_markdown
from proctx_crawler.models import (
    CrawlConfig,
    CrawlResult,
    ErrorCode,
    JobNotFoundError,
    JobStatus,
    LinksInput,
    SinglePageInput,
    SuccessResponse,
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
# app.state accessors
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


# ---------------------------------------------------------------------------
# POST /crawl — Start crawl job
# ---------------------------------------------------------------------------


@router.post("/crawl")
async def start_crawl(config: CrawlConfig, request: Request) -> SuccessResponse[str]:
    """Create a new crawl job and start it in the background."""
    repo = _repo(request)
    storage = _storage(request)
    pool = _browser_pool(request) if config.render else None
    max_response_size = request.app.state.settings.max_response_size

    job = await build_and_persist_job(config.url, config, repo)
    request.app.state.task_group.start_soon(
        run_crawl,
        job,
        repo,
        storage,
        pool,
        max_response_size,
    )

    log.info("crawl_job_created", job_id=job.id, url=config.url)
    return SuccessResponse(result=job.id)


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

    formats = list(job.config.formats)
    records = [await url_record_to_crawl_record(id, rec, storage, formats) for rec in url_records]

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
        return SuccessResponse(result=html_to_markdown(body.html))

    html = await _fetch_single_page_html(body, request)
    return SuccessResponse(result=html_to_markdown(html))


# ---------------------------------------------------------------------------
# POST /content — Single-page HTML
# ---------------------------------------------------------------------------


@router.post("/content")
async def get_content(body: SinglePageInput, request: Request) -> SuccessResponse[str]:
    """Fetch a single page and return its HTML."""
    if body.html is not None:
        return SuccessResponse(result=extract_html(body.html))

    html = await _fetch_single_page_html(body, request)
    return SuccessResponse(result=extract_html(html))


# ---------------------------------------------------------------------------
# POST /links — Extract links
# ---------------------------------------------------------------------------


@router.post("/links")
async def get_links(body: LinksInput, request: Request) -> SuccessResponse[list[str]]:
    """Fetch a page and extract all links."""
    assert body.url is not None
    if body.render and body.visible_links_only:
        all_links = await extract_visible_links_rendered(
            body.url,
            _browser_pool(request),
            goto_options=body.goto_options,
            wait_for_selector=body.wait_for_selector,
            reject_resource_types=body.reject_resource_types,
        )
    else:
        html = await _fetch_single_page_html(body, request)
        all_links = extract_links(html, body.url)

    if body.exclude_external_links:
        all_links = [link for link in all_links if is_same_domain(link, body.url)]
    return SuccessResponse(result=all_links)


# ---------------------------------------------------------------------------
# HTTP-to-service adapter
# ---------------------------------------------------------------------------


async def _fetch_single_page_html(body: SinglePageInput | LinksInput, request: Request) -> str:
    """Adapt a validated request body to the shared page_service and return HTML."""
    assert body.url is not None
    pool = _browser_pool(request) if body.render else None
    max_response_size = request.app.state.settings.max_response_size
    result = await fetch_page_html(
        body.url,
        render=body.render,
        browser_pool=pool,
        goto_options=body.goto_options,
        wait_for_selector=body.wait_for_selector,
        reject_resource_types=body.reject_resource_types,
        max_response_size=max_response_size,
    )
    return result.html
