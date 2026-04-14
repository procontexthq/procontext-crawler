"""BFS crawl engine — the core loop that drives multi-page crawls."""

from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
from bs4 import BeautifulSoup

from proctx_crawler.core.discovery import discover_page_links, discover_seed_urls
from proctx_crawler.core.fetcher import fetch_static
from proctx_crawler.core.renderer import fetch_rendered
from proctx_crawler.core.url_utils import normalise_url
from proctx_crawler.extractors import extract_html, html_to_markdown
from proctx_crawler.infrastructure.content_storage import ExtractedContent
from proctx_crawler.models import CrawlerError, JobStatus, UrlStatus

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


async def _seed_queue(
    job: Job,
    queue: deque[QueueEntry],
    visited: set[str],
    repo: Repository,
) -> None:
    """Populate the BFS queue with seed URLs based on the configured source strategy."""
    if job.config.source == "llms_txt":
        # Fetch the starting URL to get llms.txt content, then parse for seed URLs.
        page = await fetch_static(job.url)
        seed_urls = await discover_seed_urls(job.url, "llms_txt", page.html)
    else:
        seed_urls = await discover_seed_urls(job.url, job.config.source)

    for url in seed_urls:
        normalised = normalise_url(url)
        if normalised not in visited:
            queue.append(QueueEntry(url=url, depth=0))
            visited.add(normalised)
            await repo.enqueue_url(job.id, url, depth=0)


async def _fetch_page(
    url: str,
    job: Job,
    browser_pool: BrowserPool | None,
) -> tuple[str, int]:
    """Fetch a page via static or rendered path. Returns ``(html, status_code)``."""
    if job.config.render and browser_pool is not None:
        result = await fetch_rendered(
            url,
            browser_pool,
            goto_options=job.config.goto_options,
            wait_for_selector=job.config.wait_for_selector,
            reject_resource_types=job.config.reject_resource_types,
        )
    else:
        result = await fetch_static(url)
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


async def run_crawl(
    job: Job,
    repo: Repository,
    storage: ContentStorage,
    browser_pool: BrowserPool | None = None,
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

    # -- Phase 1: Seed the queue -----------------------------------------------
    try:
        await _seed_queue(job, queue, visited, repo)
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
    while queue and completed_count < job.config.limit:
        if await repo.is_job_cancelled(job.id):
            log.info("crawl_cancelled")
            break

        entry = queue.popleft()
        await repo.update_url_status(job.id, entry.url, UrlStatus.RUNNING)

        try:
            html, status_code = await _fetch_page(entry.url, job, browser_pool)

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

            # Discover new URLs (skip for llms_txt — only seed URLs are crawled).
            if job.config.source != "llms_txt":
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
                    normalised = normalise_url(new_url)
                    new_depth = entry.depth + 1
                    if normalised not in visited and new_depth <= job.config.depth:
                        queue.append(QueueEntry(url=new_url, depth=new_depth))
                        visited.add(normalised)
                        await repo.enqueue_url(job.id, new_url, depth=new_depth)

        except CrawlerError as exc:
            await repo.mark_url_errored(job.id, entry.url, exc.message)
            log.warning("url_fetch_failed", url=entry.url, error=exc.message, exc_info=True)
        except Exception:
            await repo.mark_url_errored(job.id, entry.url, "Unexpected error")
            log.error("url_unexpected_error", url=entry.url, exc_info=True)

        # Update job counts after each URL is processed.
        total, finished = await repo.get_job_counts(job.id)
        await repo.update_job_counts(job.id, total=total, finished=finished)

    # -- Phase 3: Finalise -----------------------------------------------------
    final_status = (
        JobStatus.CANCELLED if await repo.is_job_cancelled(job.id) else JobStatus.COMPLETED
    )
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
