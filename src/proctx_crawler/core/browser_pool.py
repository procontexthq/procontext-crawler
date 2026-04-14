"""Browser pool for managing a shared Playwright Chromium instance."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import anyio
import structlog
from playwright.async_api import async_playwright

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from playwright.async_api import Browser, BrowserContext, Playwright

log = structlog.get_logger()


class BrowserPool:
    """Manages a single long-lived Chromium browser shared across all fetches.

    Each fetch acquires a fresh BrowserContext (cheap, ~10ms) for complete isolation.
    The browser is relaunched automatically if it crashes.
    """

    def __init__(self, *, headless: bool = True) -> None:
        self._headless = headless
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._lock: anyio.Lock | None = None

    def _get_lock(self) -> anyio.Lock:
        """Lazily create the anyio.Lock (must be created inside an async context)."""
        if self._lock is None:
            self._lock = anyio.Lock()
        return self._lock

    async def start(self) -> None:
        """Launch Playwright and the Chromium browser.

        Called once during application startup.
        """
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)
        log.info("browser_pool_started", headless=self._headless)

    async def stop(self) -> None:
        """Close the browser and Playwright.

        Called during application shutdown.
        """
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._browser = None
        self._playwright = None
        log.info("browser_pool_stopped")

    async def _ensure_browser(self) -> Browser:
        """Return the current browser, relaunching it if it has crashed.

        Uses a lock to prevent concurrent relaunches.
        """
        lock = self._get_lock()
        async with lock:
            if self._browser is None or not self._browser.is_connected():
                log.warning("browser_relaunching")
                if self._playwright is None:
                    self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(headless=self._headless)
                log.info("browser_relaunched")
            return self._browser

    @asynccontextmanager
    async def acquire_context(self) -> AsyncIterator[BrowserContext]:
        """Acquire a fresh BrowserContext. Automatically closed on exit."""
        browser = await self._ensure_browser()
        context = await browser.new_context()
        try:
            yield context
        finally:
            await context.close()
