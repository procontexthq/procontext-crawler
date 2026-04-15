"""Playwright-based page renderer for JavaScript-heavy sites."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

import structlog

from proctx_crawler.core.fetcher import FetchResult
from proctx_crawler.models import ErrorCode, GotoOptions, RenderError

if TYPE_CHECKING:
    from collections.abc import Callable

    from playwright.async_api import Route

    from proctx_crawler.core.browser_pool import BrowserPool

log = structlog.get_logger()
_ALLOWED_SCHEMES = frozenset(("http", "https"))

# Playwright's accepted wait_until values.
type _PlaywrightWaitUntil = Literal["commit", "domcontentloaded", "load", "networkidle"]

# GotoOptions uses Puppeteer-style "networkidle0"/"networkidle2"; Playwright uses "networkidle".
_WAIT_UNTIL_MAP: dict[str, _PlaywrightWaitUntil] = {
    "load": "load",
    "domcontentloaded": "domcontentloaded",
    "networkidle0": "networkidle",
    "networkidle2": "networkidle",
}

_VISIBLE_LINKS_SCRIPT = """
() => {
  function isInvisible(el) {
    for (let cur = el; cur; cur = cur.parentElement) {
      if (cur.hidden) return true;
      if (cur.getAttribute("aria-hidden") === "true") return true;

      const style = window.getComputedStyle(cur);
      if (style.display === "none") return true;
      if (style.visibility === "hidden" || style.visibility === "collapse") return true;
    }

    const rects = el.getClientRects();
    if (rects.length === 0) return true;

    return false;
  }

  return Array.from(document.querySelectorAll("a[href]"))
    .filter((anchor) => !isInvisible(anchor))
    .map((anchor) => anchor.href);
}
"""


def _make_resource_blocker(reject_types: list[str]) -> Callable[[Route], object]:
    """Return a route handler that aborts requests matching the given resource types."""
    blocked = frozenset(reject_types)

    async def _handler(route: Route) -> None:
        if route.request.resource_type in blocked:
            await route.abort()
        else:
            await route.continue_()

    return _handler


async def fetch_rendered(
    url: str,
    pool: BrowserPool,
    *,
    goto_options: GotoOptions | None = None,
    wait_for_selector: str | None = None,
    reject_resource_types: list[str] | None = None,
) -> FetchResult:
    """Fetch a URL using Playwright for full JavaScript rendering.

    Acquires a fresh BrowserContext from the pool, navigates to the URL,
    optionally waits for a selector, and returns the rendered HTML.

    Wraps all Playwright exceptions as RenderError at the module boundary.
    """
    raw_wait_until = goto_options.wait_until if goto_options else "load"
    pw_wait_until = _WAIT_UNTIL_MAP.get(raw_wait_until, "load")
    timeout = goto_options.timeout if goto_options else 30000

    try:
        async with pool.acquire_context() as context:
            page = await context.new_page()

            if reject_resource_types:
                await page.route("**/*", _make_resource_blocker(reject_resource_types))

            response = await page.goto(url, wait_until=pw_wait_until, timeout=timeout)

            if wait_for_selector:
                await page.wait_for_selector(wait_for_selector, timeout=timeout)

            html = await page.content()

            return FetchResult(
                url=page.url,
                status_code=response.status if response else 0,
                html=html,
                headers={},
            )
    except RenderError:
        raise
    except Exception as exc:
        raise RenderError(
            code=ErrorCode.RENDER_FAILED,
            message=f"Playwright rendering failed for {url}: {exc}",
            recoverable=True,
        ) from exc


async def extract_visible_links_rendered(
    url: str,
    pool: BrowserPool,
    *,
    goto_options: GotoOptions | None = None,
    wait_for_selector: str | None = None,
    reject_resource_types: list[str] | None = None,
) -> list[str]:
    """Return render-time links, excluding anchors that are clearly invisible.

    This is intentionally conservative: links are treated as visible unless they
    are explicitly hidden (for example via ``display:none``/``visibility:hidden``,
    ``hidden``, ``aria-hidden=true``, or no client rects at all).
    """
    raw_wait_until = goto_options.wait_until if goto_options else "load"
    pw_wait_until = _WAIT_UNTIL_MAP.get(raw_wait_until, "load")
    timeout = goto_options.timeout if goto_options else 30000

    try:
        async with pool.acquire_context() as context:
            page = await context.new_page()

            if reject_resource_types:
                await page.route("**/*", _make_resource_blocker(reject_resource_types))

            await page.goto(url, wait_until=pw_wait_until, timeout=timeout)

            if wait_for_selector:
                await page.wait_for_selector(wait_for_selector, timeout=timeout)

            raw_links = await page.evaluate(_VISIBLE_LINKS_SCRIPT)
            return _clean_extracted_links(raw_links)
    except RenderError:
        raise
    except Exception as exc:
        raise RenderError(
            code=ErrorCode.RENDER_FAILED,
            message=f"Playwright rendering failed for {url}: {exc}",
            recoverable=True,
        ) from exc


def _clean_extracted_links(raw_links: object) -> list[str]:
    """Validate, fragment-strip, and deduplicate extracted absolute URLs."""
    if not isinstance(raw_links, list):
        return []

    links: list[str] = []
    seen: set[str] = set()
    for raw in raw_links:
        if not isinstance(raw, str):
            continue

        parsed = urlparse(raw)
        if parsed.scheme not in _ALLOWED_SCHEMES:
            continue

        clean = parsed._replace(fragment="").geturl()
        if clean not in seen:
            seen.add(clean)
            links.append(clean)

    return links
