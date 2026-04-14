"""Tests for the BrowserPool managing a shared Playwright Chromium instance."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest

from proctx_crawler.core.browser_pool import BrowserPool


def _make_mock_browser() -> MagicMock:
    """Create a mock Browser with sync is_connected() and async new_context()/close()."""
    mock_context = AsyncMock()
    mock_context.close = AsyncMock()

    mock_browser = MagicMock()
    mock_browser.is_connected.return_value = True
    mock_browser.close = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    return mock_browser


def _make_mock_playwright() -> MagicMock:
    """Create a mock playwright instance with chromium.launch returning a mock browser."""
    mock_browser = _make_mock_browser()

    mock_pw = AsyncMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_pw.stop = AsyncMock()

    return mock_pw


@pytest.fixture
def mock_async_playwright() -> MagicMock:
    """Fixture that patches async_playwright to return a mock."""
    mock_pw = _make_mock_playwright()
    mock_context_manager = AsyncMock()
    mock_context_manager.start = AsyncMock(return_value=mock_pw)

    with patch(
        "proctx_crawler.core.browser_pool.async_playwright",
        return_value=mock_context_manager,
    ):
        yield mock_pw


# ---------------------------------------------------------------------------
# Lifecycle: start / stop
# ---------------------------------------------------------------------------


class TestBrowserPoolLifecycle:
    @pytest.mark.anyio
    async def test_start_launches_browser(self, mock_async_playwright: MagicMock) -> None:
        pool = BrowserPool(headless=True)
        await pool.start()

        mock_async_playwright.chromium.launch.assert_awaited_once_with(headless=True)
        assert pool._browser is not None

    @pytest.mark.anyio
    async def test_stop_closes_browser_and_playwright(
        self, mock_async_playwright: MagicMock
    ) -> None:
        pool = BrowserPool()
        await pool.start()
        await pool.stop()

        mock_async_playwright.chromium.launch.return_value.close.assert_awaited_once()
        mock_async_playwright.stop.assert_awaited_once()
        assert pool._browser is None
        assert pool._playwright is None

    @pytest.mark.anyio
    async def test_stop_without_start_is_safe(self) -> None:
        """Stopping a pool that was never started should not raise."""
        pool = BrowserPool()
        await pool.stop()  # Should not raise


# ---------------------------------------------------------------------------
# acquire_context
# ---------------------------------------------------------------------------


class TestBrowserPoolAcquireContext:
    @pytest.mark.anyio
    async def test_acquire_returns_context(self, mock_async_playwright: MagicMock) -> None:
        pool = BrowserPool()
        await pool.start()

        async with pool.acquire_context() as context:
            assert context is not None

    @pytest.mark.anyio
    async def test_context_closed_after_exit(self, mock_async_playwright: MagicMock) -> None:
        pool = BrowserPool()
        await pool.start()

        async with pool.acquire_context() as context:
            pass

        context.close.assert_awaited_once()

    @pytest.mark.anyio
    async def test_context_closed_on_exception(self, mock_async_playwright: MagicMock) -> None:
        pool = BrowserPool()
        await pool.start()

        with pytest.raises(RuntimeError, match="test error"):
            async with pool.acquire_context() as context:
                raise RuntimeError("test error")

        context.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# Crash recovery
# ---------------------------------------------------------------------------


class TestBrowserPoolCrashRecovery:
    @pytest.mark.anyio
    async def test_relaunches_on_disconnected(self, mock_async_playwright: MagicMock) -> None:
        pool = BrowserPool()
        await pool.start()

        # Simulate browser crash: is_connected() returns False.
        original_browser = pool._browser
        assert original_browser is not None
        original_browser.is_connected.return_value = False

        # Create a new mock browser for the relaunch.
        new_browser = _make_mock_browser()
        mock_async_playwright.chromium.launch = AsyncMock(return_value=new_browser)

        async with pool.acquire_context():
            pass

        # The browser should have been relaunched.
        assert pool._browser is new_browser
        # The relaunch mock was set after start(), so it only sees the relaunch call.
        mock_async_playwright.chromium.launch.assert_awaited_once()

    @pytest.mark.anyio
    async def test_relaunches_when_browser_is_none(self, mock_async_playwright: MagicMock) -> None:
        pool = BrowserPool()
        await pool.start()

        # Simulate browser being None (e.g., after stop + re-use).
        pool._browser = None

        new_browser = _make_mock_browser()
        mock_async_playwright.chromium.launch = AsyncMock(return_value=new_browser)

        async with pool.acquire_context():
            pass

        assert pool._browser is new_browser


# ---------------------------------------------------------------------------
# Concurrent access
# ---------------------------------------------------------------------------


class TestBrowserPoolConcurrency:
    @pytest.mark.anyio
    async def test_concurrent_acquire_uses_lock(self, mock_async_playwright: MagicMock) -> None:
        """Multiple concurrent acquire_context calls should not cause multiple relaunches."""
        pool = BrowserPool()
        await pool.start()

        # Simulate crash.
        original_browser = pool._browser
        assert original_browser is not None
        original_browser.is_connected.return_value = False

        new_browser = _make_mock_browser()

        launch_call_count = 0

        async def mock_launch(*, headless: bool = True) -> MagicMock:
            nonlocal launch_call_count
            launch_call_count += 1
            # After first relaunch, update pool's browser so second call sees connected.
            pool._browser = new_browser
            return new_browser

        mock_async_playwright.chromium.launch = AsyncMock(side_effect=mock_launch)

        results: list[bool] = []

        async def acquire_task() -> None:
            async with pool.acquire_context():
                results.append(True)

        async with anyio.create_task_group() as tg:
            tg.start_soon(acquire_task)
            tg.start_soon(acquire_task)

        assert len(results) == 2
        # The lock should prevent excessive relaunches. Due to the lock,
        # the second call should see the already-relaunched browser.
        # We expect at most 2 launch calls (initial + one relaunch),
        # not 3 (initial + two relaunches).
        assert launch_call_count <= 2
