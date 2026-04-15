"""Single-page fetch dispatch shared by the Python and HTTP APIs.

This module owns the "given a URL and a render flag, return the page HTML"
flow. Both the ``Crawler`` class and the HTTP route handlers delegate here
so the static-vs-rendered decision, and the browser-pool requirement for
rendered fetches, live in exactly one place.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from proctx_crawler.core.fetcher import fetch_static
from proctx_crawler.core.renderer import fetch_rendered

if TYPE_CHECKING:
    from proctx_crawler.core.browser_pool import BrowserPool
    from proctx_crawler.core.fetcher import FetchResult
    from proctx_crawler.models import GotoOptions


async def fetch_page_html(
    url: str,
    *,
    render: bool,
    browser_pool: BrowserPool | None,
    goto_options: GotoOptions | None = None,
    wait_for_selector: str | None = None,
    reject_resource_types: list[str] | None = None,
    max_response_size: int = 10_485_760,
) -> FetchResult:
    """Fetch a single page via the static or rendered path.

    Callers own the browser pool — this function does not start or stop it.
    When ``render`` is ``True`` a ``browser_pool`` must be supplied.
    """
    if render:
        if browser_pool is None:
            msg = "browser_pool is required when render=True"
            raise RuntimeError(msg)
        return await fetch_rendered(
            url,
            browser_pool,
            goto_options=goto_options,
            wait_for_selector=wait_for_selector,
            reject_resource_types=reject_resource_types,
        )
    return await fetch_static(url, max_response_size=max_response_size)
