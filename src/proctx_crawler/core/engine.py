"""BFS crawl engine — the core loop that drives multi-page crawls."""

from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

import structlog
from bs4 import BeautifulSoup

from proctx_crawler.core.discovery import discover_page_links, extract_text_urls
from proctx_crawler.core.fetcher import FetchResult, fetch_static
from proctx_crawler.core.renderer import fetch_rendered
from proctx_crawler.core.url_utils import normalise_url
from proctx_crawler.extractors import extract_html, html_to_markdown
from proctx_crawler.infrastructure.content_storage import ExtractedContent
from proctx_crawler.models import CrawlerError, ErrorCode, JobStatus, RenderError, UrlStatus

if TYPE_CHECKING:
    from collections.abc import Sequence

    from proctx_crawler.core.browser_pool import BrowserPool
    from proctx_crawler.core.repository import Repository
    from proctx_crawler.infrastructure.content_storage import ContentStorage
    from proctx_crawler.models import Job

log: structlog.stdlib.BoundLogger = structlog.get_logger()


@dataclass
class QueueEntry:
    """A single entry in the BFS crawl queue."""

    url: str
    depth: int
    discover_children: bool = True
    prefetched_response: FetchResult | None = None


AutoSourceKind = Literal["html", "text"]

_TEXT_PATH_SUFFIXES = ("llms.txt", ".txt", ".md", ".markdown", ".rst")
_TEXT_MEDIA_TYPES = frozenset(
    {
        "text/plain",
        "text/markdown",
        "text/x-markdown",
        "application/markdown",
    }
)
_HTML_MEDIA_TYPES = frozenset({"text/html", "application/xhtml+xml"})


def _extract_title(html: str) -> str | None:
    """Extract the page title from the ``<title>`` tag or the first ``<h1>``."""
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        return title_tag.string.strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return None


def _response_media_type(headers: dict[str, str]) -> str | None:
    """Return the lower-case media type from Content-Type headers."""
    for key, value in headers.items():
        if key.lower() == "content-type":
            return value.split(";", maxsplit=1)[0].strip().lower()
    return None


def _path_looks_like_text_index(url: str) -> bool:
    """Return True when the final URL path is text/Markdown-like."""
    path = urlparse(url).path.lower()
    return path.endswith(_TEXT_PATH_SUFFIXES)


def _body_looks_like_html(body: str) -> bool:
    """Conservatively identify HTML bodies when Content-Type is absent."""
    sample = body.lstrip()[:4096].lower()
    return (
        sample.startswith("<!doctype html")
        or sample.startswith("<html")
        or "<head" in sample
        or "<body" in sample
        or "<a " in sample
    )


def _classify_auto_response(page: FetchResult) -> AutoSourceKind:
    """Classify a prefetched start URL as an HTML page or text URL index."""
    if _path_looks_like_text_index(page.url):
        return "text"

    media_type = _response_media_type(page.headers)
    if media_type in _TEXT_MEDIA_TYPES:
        return "text"
    if media_type in _HTML_MEDIA_TYPES:
        return "html"
    if _body_looks_like_html(page.html):
        return "html"
    return "text"


async def _enqueue_url(
    job: Job,
    queue: deque[QueueEntry],
    visited: set[str],
    repo: Repository,
    *,
    url: str,
    depth: int,
    discover_children: bool,
    prefetched_response: FetchResult | None = None,
) -> bool:
    """Add a URL to the crawl queue if it is inside the limit and not visited."""
    if len(visited) >= job.config.limit:
        return False

    normalised = normalise_url(url)
    if normalised in visited:
        return False

    queue.append(
        QueueEntry(
            url=url,
            depth=depth,
            discover_children=discover_children,
            prefetched_response=prefetched_response,
        )
    )
    visited.add(normalised)
    await repo.enqueue_url(job.id, url, depth=depth)
    return True


async def _seed_text_index_urls(
    job: Job,
    queue: deque[QueueEntry],
    visited: set[str],
    repo: Repository,
    *,
    text: str,
    base_url: str,
) -> int:
    """Seed URLs parsed from a text/Markdown index without child discovery."""
    enqueued = 0
    for url in extract_text_urls(text, base_url=base_url):
        did_enqueue = await _enqueue_url(
            job,
            queue,
            visited,
            repo,
            url=url,
            depth=0,
            discover_children=False,
        )
        if did_enqueue:
            enqueued += 1
    return enqueued


async def _seed_auto_queue(
    job: Job,
    queue: deque[QueueEntry],
    visited: set[str],
    repo: Repository,
    *,
    max_response_size: int,
) -> None:
    """Prefetch and classify the start URL for automatic discovery."""
    try:
        page = await fetch_static(job.url, max_response_size=max_response_size)
    except CrawlerError:
        log.warning("auto_source_detection_failed", exc_info=True)
        await _enqueue_url(
            job,
            queue,
            visited,
            repo,
            url=job.url,
            depth=0,
            discover_children=True,
        )
        return

    if _classify_auto_response(page) == "text":
        enqueued = await _seed_text_index_urls(
            job,
            queue,
            visited,
            repo,
            text=page.html,
            base_url=page.url,
        )
        if enqueued == 0:
            await _enqueue_url(
                job,
                queue,
                visited,
                repo,
                url=job.url,
                depth=0,
                discover_children=False,
                prefetched_response=page,
            )
        return

    await _enqueue_url(
        job,
        queue,
        visited,
        repo,
        url=job.url,
        depth=0,
        discover_children=True,
        prefetched_response=None if job.config.render else page,
    )


async def _seed_queue(
    job: Job,
    queue: deque[QueueEntry],
    visited: set[str],
    repo: Repository,
    *,
    max_response_size: int,
) -> None:
    """Populate the BFS queue with seed URLs based on the configured source strategy."""
    if job.config.source == "auto":
        await _seed_auto_queue(
            job,
            queue,
            visited,
            repo,
            max_response_size=max_response_size,
        )
        return

    if job.config.source == "llms_txt":
        page = await fetch_static(job.url, max_response_size=max_response_size)
        await _seed_text_index_urls(
            job,
            queue,
            visited,
            repo,
            text=page.html,
            base_url=page.url,
        )
        return

    if job.config.source == "links":
        await _enqueue_url(
            job,
            queue,
            visited,
            repo,
            url=job.url,
            depth=0,
            discover_children=True,
        )
        return

    msg = f"Unsupported discovery source: {job.config.source}"
    raise ValueError(msg)


async def _fetch_page(
    entry: QueueEntry,
    job: Job,
    browser_pool: BrowserPool | None,
    *,
    max_response_size: int,
) -> tuple[str, int]:
    """Fetch a page via static or rendered path. Returns ``(html, status_code)``."""
    if entry.prefetched_response is not None and (
        not job.config.render or not entry.discover_children
    ):
        return entry.prefetched_response.html, entry.prefetched_response.status_code

    if job.config.render:
        if browser_pool is None:
            raise RenderError(
                code=ErrorCode.RENDER_FAILED,
                message="browser_pool is required when render=True",
                recoverable=False,
            )
        result = await fetch_rendered(
            entry.url,
            browser_pool,
            goto_options=job.config.goto_options,
            wait_for_selector=job.config.wait_for_selector,
            reject_resource_types=job.config.reject_resource_types,
        )
    else:
        result = await fetch_static(entry.url, max_response_size=max_response_size)
    return result.html, result.status_code


def _extract_content(html: str, formats: Sequence[str]) -> ExtractedContent:
    """Extract content in the requested formats."""
    content = ExtractedContent()
    if "markdown" in formats:
        content.markdown = html_to_markdown(html)
    if "html" in formats:
        content.html = extract_html(html)
    return content


def _content_hash(content: ExtractedContent) -> str:
    """Compute a SHA-256 hash of the primary content for deduplication."""
    text = content.markdown or content.html or ""
    return hashlib.sha256(text.encode()).hexdigest()


def _deadline_expired(deadline: float | None) -> bool:
    """Return True when a cooperative crawl timeout deadline has passed."""
    return deadline is not None and monotonic() >= deadline


async def run_crawl(
    job: Job,
    repo: Repository,
    storage: ContentStorage,
    browser_pool: BrowserPool | None = None,
    max_response_size: int = 10_485_760,
    job_timeout: int | None = None,
) -> None:
    """Execute a BFS crawl for the given job.

    This is the core crawl loop. It:
    1. Seeds the queue (based on source strategy)
    2. Processes URLs in FIFO order (BFS)
    3. Fetches pages (static or Playwright)
    4. Extracts content in requested formats
    5. Writes content to storage
    6. Discovers new URLs and enqueues them
    7. Respects limits (page limit, depth limit)
    8. Handles cancellation
    9. Writes manifest on completion
    """
    structlog.contextvars.bind_contextvars(job_id=job.id)

    queue: deque[QueueEntry] = deque()
    visited: set[str] = set()
    deadline = monotonic() + job_timeout if job_timeout is not None else None
    timed_out = False

    # -- Phase 1: Seed the queue -----------------------------------------------
    try:
        await _seed_queue(job, queue, visited, repo, max_response_size=max_response_size)
    except CrawlerError as exc:
        log.error("seed_failed", error=exc.message, exc_info=True)
        await repo.update_job_status(job.id, JobStatus.ERRORED)
        structlog.contextvars.unbind_contextvars("job_id")
        return
    except Exception:
        log.error("seed_unexpected_error", exc_info=True)
        await repo.update_job_status(job.id, JobStatus.ERRORED)
        structlog.contextvars.unbind_contextvars("job_id")
        return

    await repo.update_job_status(job.id, JobStatus.RUNNING)
    log.info("crawl_started", url=job.url, source=job.config.source, queue_size=len(queue))

    # -- Phase 2: BFS loop -----------------------------------------------------
    completed_count = 0
    while queue:
        if _deadline_expired(deadline):
            timed_out = True
            log.warning("crawl_timed_out", timeout_seconds=job_timeout)
            break

        if await repo.is_job_cancelled(job.id):
            log.info("crawl_cancelled")
            break

        entry = queue.popleft()
        await repo.update_url_status(job.id, entry.url, UrlStatus.RUNNING)

        try:
            html, status_code = await _fetch_page(
                entry,
                job,
                browser_pool,
                max_response_size=max_response_size,
            )

            content = _extract_content(html, job.config.formats)
            await storage.write(job.id, entry.url, content)

            title = _extract_title(html)
            chash = _content_hash(content)

            await repo.mark_url_completed(
                job.id,
                entry.url,
                http_status=status_code,
                title=title,
                content_hash=chash,
            )
            completed_count += 1

            if entry.discover_children:
                new_urls = discover_page_links(
                    html,
                    entry.url,
                    include_patterns=job.config.options.include_patterns,
                    exclude_patterns=job.config.options.exclude_patterns,
                    include_subdomains=job.config.options.include_subdomains,
                    include_external_links=job.config.options.include_external_links,
                    start_url=job.url,
                )
                for new_url in new_urls:
                    if len(visited) >= job.config.limit:
                        break
                    normalised = normalise_url(new_url)
                    new_depth = entry.depth + 1
                    if normalised not in visited and new_depth <= job.config.depth:
                        await _enqueue_url(
                            job,
                            queue,
                            visited,
                            repo,
                            url=new_url,
                            depth=new_depth,
                            discover_children=True,
                        )

        except CrawlerError as exc:
            await repo.mark_url_errored(job.id, entry.url, exc.message)
            log.warning("url_fetch_failed", url=entry.url, error=exc.message, exc_info=True)
        except Exception:
            await repo.mark_url_errored(job.id, entry.url, "Unexpected error")
            log.error("url_unexpected_error", url=entry.url, exc_info=True)

        # Update job counts after each URL is processed.
        total, finished = await repo.get_job_counts(job.id)
        await repo.update_job_counts(job.id, total=total, finished=finished)

        if _deadline_expired(deadline):
            timed_out = True
            log.warning("crawl_timed_out", timeout_seconds=job_timeout)
            break

    # -- Phase 3: Finalise -----------------------------------------------------
    is_cancelled = timed_out or await repo.is_job_cancelled(job.id)
    if is_cancelled:
        await repo.cancel_queued_urls(job.id)

    total, finished = await repo.get_job_counts(job.id)
    await repo.update_job_counts(job.id, total=total, finished=finished)

    final_status = JobStatus.CANCELLED if is_cancelled else JobStatus.COMPLETED
    await repo.update_job_status(job.id, final_status)

    job_data = await repo.get_job(job.id)
    records, _ = await repo.get_url_records(job.id, limit=100_000)

    await storage.write_manifest(
        job_id=job.id,
        url=job.url,
        config_data=job.config.model_dump(),
        total=job_data.total if job_data else 0,
        finished=job_data.finished if job_data else 0,
        status=final_status.value,
        created_at=job.created_at.isoformat(),
        finished_at=job_data.finished_at.isoformat() if job_data and job_data.finished_at else None,
        records=[
            {
                "url": r.url,
                "status": r.status.value,
                "http_status": r.http_status,
                "title": r.title,
                "content_hash": r.content_hash,
            }
            for r in records
        ],
    )

    log.info("crawl_finished", status=final_status.value, completed=completed_count)
    structlog.contextvars.unbind_contextvars("job_id")
