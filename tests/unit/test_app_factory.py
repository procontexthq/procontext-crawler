"""Tests for the FastAPI application factory and lifespan."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from proctx_crawler.api.app import create_app, lifespan
from proctx_crawler.api.middleware import AuthMiddleware

# ---------------------------------------------------------------------------
# create_app() — no auth
# ---------------------------------------------------------------------------


class TestCreateAppNoAuth:
    def test_returns_fastapi_instance(self) -> None:
        """Without an API key, create_app returns a plain FastAPI app."""
        with patch("proctx_crawler.api.app.load_settings") as mock_settings:
            mock_settings.return_value = MagicMock(auth_api_key=None)
            app = create_app()

        assert isinstance(app, FastAPI)

    def test_includes_routes(self) -> None:
        """The app should have the router's routes."""
        with patch("proctx_crawler.api.app.load_settings") as mock_settings:
            mock_settings.return_value = MagicMock(auth_api_key=None)
            app = create_app()

        route_paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/crawl" in route_paths
        assert "/markdown" in route_paths
        assert "/content" in route_paths
        assert "/links" in route_paths


# ---------------------------------------------------------------------------
# create_app() — with auth
# ---------------------------------------------------------------------------


class TestCreateAppWithAuth:
    def test_returns_auth_middleware(self) -> None:
        """With an API key, create_app wraps the app in AuthMiddleware."""
        with patch("proctx_crawler.api.app.load_settings") as mock_settings:
            mock_settings.return_value = MagicMock(auth_api_key="secret-key")
            app = create_app()

        assert isinstance(app, AuthMiddleware)
        assert app._api_key == "secret-key"


# ---------------------------------------------------------------------------
# lifespan()
# ---------------------------------------------------------------------------


class TestLifespan:
    @pytest.mark.anyio
    async def test_lifespan_initialises_and_cleans_up(self) -> None:
        """The lifespan context manager should set up app state and clean up on exit."""
        mock_repo = AsyncMock()
        mock_pool = AsyncMock()
        mock_settings = MagicMock(
            db_path="/tmp/test.db",
            output_dir="/tmp/output",
            playwright_headless=True,
            server_host="127.0.0.1",
            server_port=8080,
        )

        with (
            patch("proctx_crawler.api.app.load_settings", return_value=mock_settings),
            patch("proctx_crawler.api.app.SQLiteRepository", return_value=mock_repo),
            patch("proctx_crawler.api.app.ContentStorage") as mock_storage_cls,
            patch("proctx_crawler.api.app.BrowserPool", return_value=mock_pool),
        ):
            app = FastAPI()
            async with lifespan(app):
                # During lifespan, state should be set
                assert app.state.repo is mock_repo
                assert app.state.storage is mock_storage_cls.return_value
                assert app.state.browser_pool is mock_pool
                assert app.state.settings is mock_settings
                assert hasattr(app.state, "task_group")

            # After lifespan, cleanup should have run
            mock_pool.stop.assert_awaited_once()
            mock_repo.close.assert_awaited_once()
            mock_repo.initialise.assert_awaited_once()
            mock_pool.start.assert_awaited_once()
