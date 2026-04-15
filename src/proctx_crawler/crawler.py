"""Public Python API: the Crawler async context manager."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

import structlog

from proctx_crawler.config import Settings, load_settings
from proctx_crawler.core.browser_pool import BrowserPool
from proctx_crawler.core.crawl_service import (
    build_and_persist_job,
    collect_crawl_result,
)
from proctx_crawler.core.engine import run_crawl
from proctx_crawler.core.page_service import fetch_page_html
from proctx_crawler.core.renderer import extract_visible_links_rendered
from proctx_crawler.core.url_utils import is_same_domain
from proctx_crawler.extractors import extract_html, extract_links, html_to_markdown
from proctx_crawler.infrastructure.content_storage import ContentStorage
from proctx_crawler.infrastructure.sqlite_repository import SQLiteRepository
from proctx_crawler.models import (
    CrawlConfig,
    CrawlOptions,
    CrawlResult,
    GotoOptions,
)

if TYPE_CHECKING:
    from pathlib import Path
    from types import TracebackType

    from proctx_crawler.core.fetcher import FetchResult

log: structlog.stdlib.BoundLogger = structlog.get_logger()


class Crawler:
    """Async context manager wrapping the crawl engine, repository, and storage.

    Configuration precedence (highest to lowest):

    1. Explicit keyword overrides (``output_dir``, ``db_path``,
       ``playwright_headless``).
    2. An injected ``Settings`` instance passed via ``settings=``.
    3. ``load_settings()`` — environment variables (``PROCTX_CRAWLER__*``),
       ``proctx-crawler.yaml`` in the working directory, and built-in defaults.

    Usage::

        async with Crawler(output_dir=Path("./out")) as crawler:
            result = await crawler.crawl("https://example.com", limit=5)
            md = await crawler.markdown("https://example.com")
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        output_dir: Path | None = None,
        db_path: Path | None = None,
        playwright_headless: bool | None = None,
    ) -> None:
        resolved = settings if settings is not None else load_settings()
        self._output_dir = output_dir if output_dir is not None else resolved.output_dir
        self._db_path = db_path if db_path is not None else resolved.db_path
        self._playwright_headless = (
            playwright_headless if playwright_headless is not None else resolved.playwright_headless
        )
        self._max_response_size = resolved.max_response_size
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
        config = CrawlConfig(
            url=url,
            limit=limit,
            depth=depth,
            source=source,
            formats=resolved_formats,
            render=render,
            goto_options=_build_goto_options(goto_options),
            wait_for_selector=wait_for_selector,
            reject_resource_types=reject_resource_types,
            options=CrawlOptions(**options) if options else CrawlOptions(),
        )
        job = await build_and_persist_job(url, config, repo)

        pool = await self._ensure_browser_pool() if render else None
        await run_crawl(job, repo, storage, pool, max_response_size=self._max_response_size)

        return await collect_crawl_result(job.id, repo, storage, resolved_formats)

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
        visible_links_only: bool = False,
        exclude_external_links: bool = False,
        goto_options: dict[str, Any] | None = None,
        wait_for_selector: str | None = None,
        reject_resource_types: list[str] | None = None,
    ) -> list[str]:
        """Fetch a single page and return all links found on it."""
        if render and visible_links_only:
            pool = await self._ensure_browser_pool()
            all_links = await extract_visible_links_rendered(
                url,
                pool,
                goto_options=_build_goto_options(goto_options),
                wait_for_selector=wait_for_selector,
                reject_resource_types=reject_resource_types,
            )
        else:
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
            self._browser_pool = BrowserPool(headless=self._playwright_headless)
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
        """Python-API adapter: lazy-init the pool then delegate to page_service."""
        pool = await self._ensure_browser_pool() if render else None
        return await fetch_page_html(
            url,
            render=render,
            browser_pool=pool,
            goto_options=_build_goto_options(goto_options),
            wait_for_selector=wait_for_selector,
            reject_resource_types=reject_resource_types,
            max_response_size=self._max_response_size,
        )


def _build_goto_options(raw: dict[str, Any] | None) -> GotoOptions | None:
    """Convert a plain dict to a GotoOptions model, or return None."""
    if raw is None:
        return None
    return GotoOptions(**raw)
