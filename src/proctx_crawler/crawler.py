"""Public Python API: the Crawler async context manager."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import platformdirs
import structlog

from proctx_crawler.core.browser_pool import BrowserPool
from proctx_crawler.core.engine import run_crawl
from proctx_crawler.core.fetcher import FetchResult, fetch_static
from proctx_crawler.core.renderer import fetch_rendered
from proctx_crawler.core.url_utils import is_same_domain
from proctx_crawler.extractors import extract_html, extract_links, html_to_markdown
from proctx_crawler.infrastructure.content_storage import ContentStorage
from proctx_crawler.infrastructure.sqlite_repository import SQLiteRepository
from proctx_crawler.models import (
    CrawlConfig,
    CrawlOptions,
    CrawlRecord,
    CrawlResult,
    GotoOptions,
    Job,
    JobStatus,
    RecordMetadata,
    UrlRecord,
    UrlStatus,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import TracebackType

log: structlog.stdlib.BoundLogger = structlog.get_logger()


def _default_output_dir() -> Path:
    return Path(platformdirs.user_data_dir("proctx-crawler")) / "jobs"


def _default_db_path() -> Path:
    return Path(platformdirs.user_data_dir("proctx-crawler")) / "crawler.db"


class Crawler:
    """Async context manager wrapping the crawl engine, repository, and storage.

    Usage::

        async with Crawler(output_dir=Path("./out")) as crawler:
            result = await crawler.crawl("https://example.com", limit=5)
            md = await crawler.markdown("https://example.com")
    """

    def __init__(
        self,
        *,
        output_dir: Path | None = None,
        db_path: Path | None = None,
    ) -> None:
        self._output_dir = output_dir or _default_output_dir()
        self._db_path = db_path or _default_db_path()
        self._repo: SQLiteRepository | None = None
        self._storage: ContentStorage | None = None
        self._browser_pool: BrowserPool | None = None

    # -- Context manager ------------------------------------------------------

    async def __aenter__(self) -> Crawler:
        self._repo = SQLiteRepository(self._db_path)
        await self._repo.initialise()
        self._storage = ContentStorage(self._output_dir)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._browser_pool is not None:
            await self._browser_pool.stop()
            self._browser_pool = None
        if self._repo is not None:
            await self._repo.close()
            self._repo = None
        self._storage = None

    # -- Public methods -------------------------------------------------------

    async def crawl(
        self,
        url: str,
        *,
        limit: int = 10,
        depth: int = 1000,
        source: Literal["links", "llms_txt", "sitemaps", "all"] = "links",
        formats: list[Literal["markdown", "html"]] | None = None,
        render: bool = False,
        goto_options: dict[str, Any] | None = None,
        wait_for_selector: str | None = None,
        reject_resource_types: list[str] | None = None,
        options: dict[str, Any] | None = None,
    ) -> CrawlResult:
        """Run a multi-page crawl and return all results when complete."""
        repo = self._get_repo()
        storage = self._get_storage()

        resolved_formats: list[Literal["markdown", "html"]] = formats if formats else ["markdown"]
        goto = _build_goto_options(goto_options)
        crawl_options = CrawlOptions(**options) if options else CrawlOptions()

        now = datetime.now(UTC)
        job_id = str(uuid.uuid4())
        config = CrawlConfig(
            url=url,
            limit=limit,
            depth=depth,
            source=source,
            formats=resolved_formats,
            render=render,
            goto_options=goto,
            wait_for_selector=wait_for_selector,
            reject_resource_types=reject_resource_types,
            options=crawl_options,
        )
        job = Job(id=job_id, url=url, config=config, created_at=now, updated_at=now)
        await repo.create_job(job)

        browser_pool: BrowserPool | None = None
        if render:
            browser_pool = await self._ensure_browser_pool()

        await run_crawl(job, repo, storage, browser_pool)

        return await _collect_crawl_result(job_id, repo, storage, resolved_formats)

    async def markdown(
        self,
        url: str,
        *,
        render: bool = False,
        goto_options: dict[str, Any] | None = None,
        wait_for_selector: str | None = None,
        reject_resource_types: list[str] | None = None,
    ) -> str:
        """Fetch a single page and return its content as Markdown."""
        result = await self._fetch_page(
            url,
            render=render,
            goto_options=goto_options,
            wait_for_selector=wait_for_selector,
            reject_resource_types=reject_resource_types,
        )
        return html_to_markdown(result.html)

    async def content(
        self,
        url: str,
        *,
        render: bool = False,
        goto_options: dict[str, Any] | None = None,
        wait_for_selector: str | None = None,
        reject_resource_types: list[str] | None = None,
    ) -> str:
        """Fetch a single page and return its HTML."""
        result = await self._fetch_page(
            url,
            render=render,
            goto_options=goto_options,
            wait_for_selector=wait_for_selector,
            reject_resource_types=reject_resource_types,
        )
        return extract_html(result.html)

    async def links(
        self,
        url: str,
        *,
        render: bool = False,
        visible_links_only: bool = False,  # noqa: ARG002
        exclude_external_links: bool = False,
        goto_options: dict[str, Any] | None = None,
        wait_for_selector: str | None = None,
        reject_resource_types: list[str] | None = None,
    ) -> list[str]:
        """Fetch a single page and return all links found on it."""
        result = await self._fetch_page(
            url,
            render=render,
            goto_options=goto_options,
            wait_for_selector=wait_for_selector,
            reject_resource_types=reject_resource_types,
        )
        all_links = extract_links(result.html, result.url)
        if exclude_external_links:
            return [link for link in all_links if is_same_domain(link, url)]
        return all_links

    # -- Internal helpers -----------------------------------------------------

    def _get_repo(self) -> SQLiteRepository:
        """Return the active repository, raising if the context manager was not entered."""
        if self._repo is None:
            msg = "Crawler must be used as an async context manager"
            raise RuntimeError(msg)
        return self._repo

    def _get_storage(self) -> ContentStorage:
        """Return the active storage, raising if the context manager was not entered."""
        if self._storage is None:
            msg = "Crawler must be used as an async context manager"
            raise RuntimeError(msg)
        return self._storage

    async def _ensure_browser_pool(self) -> BrowserPool:
        """Lazily create and start the browser pool on first render request."""
        if self._browser_pool is None:
            self._browser_pool = BrowserPool()
            await self._browser_pool.start()
        return self._browser_pool

    async def _fetch_page(
        self,
        url: str,
        *,
        render: bool,
        goto_options: dict[str, Any] | None,
        wait_for_selector: str | None,
        reject_resource_types: list[str] | None,
    ) -> FetchResult:
        """Common fetch logic for single-page methods (static vs rendered)."""
        goto = _build_goto_options(goto_options)
        if render:
            pool = await self._ensure_browser_pool()
            return await fetch_rendered(
                url,
                pool,
                goto_options=goto,
                wait_for_selector=wait_for_selector,
                reject_resource_types=reject_resource_types,
            )
        return await fetch_static(url)


def _build_goto_options(raw: dict[str, Any] | None) -> GotoOptions | None:
    """Convert a plain dict to a GotoOptions model, or return None."""
    if raw is None:
        return None
    return GotoOptions(**raw)


async def _collect_crawl_result(
    job_id: str,
    repo: SQLiteRepository,
    storage: ContentStorage,
    formats: Sequence[str],
) -> CrawlResult:
    """Fetch the final job state and all URL records, populating content fields."""
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
            crawl_record = await _url_record_to_crawl_record(job_id, rec, storage, formats)
            all_records.append(crawl_record)
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


async def _url_record_to_crawl_record(
    job_id: str,
    rec: UrlRecord,
    storage: ContentStorage,
    formats: Sequence[str],
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
