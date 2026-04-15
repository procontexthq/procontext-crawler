"""FastAPI application factory with lifespan management."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import anyio
import structlog
from fastapi import FastAPI

from proctx_crawler.api.errors import register_error_handlers
from proctx_crawler.api.middleware import AuthMiddleware
from proctx_crawler.api.routes import router
from proctx_crawler.config import Settings, load_settings
from proctx_crawler.core.browser_pool import BrowserPool
from proctx_crawler.infrastructure.content_storage import ContentStorage
from proctx_crawler.infrastructure.sqlite_repository import SQLiteRepository

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.types import ASGIApp

log: structlog.stdlib.BoundLogger = structlog.get_logger()


def _build_lifespan(settings: Settings):  # type: ignore[no-untyped-def]
    """Return a lifespan callable bound to the supplied settings instance."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Manage application-wide resources: repo, storage, browser pool, task group."""
        repo = SQLiteRepository(settings.db_path)
        await repo.initialise()
        storage = ContentStorage(settings.output_dir)
        browser_pool = BrowserPool(headless=settings.playwright_headless)

        app.state.repo = repo
        app.state.storage = storage
        app.state.browser_pool = browser_pool
        app.state.settings = settings

        log.info(
            "app_started",
            host=settings.server_host,
            port=settings.server_port,
        )

        async with anyio.create_task_group() as tg:
            app.state.task_group = tg
            yield

        await browser_pool.stop()
        await repo.close()
        log.info("app_stopped")

    return lifespan


def create_app(settings: Settings | None = None) -> ASGIApp:
    """Build and return the configured FastAPI application.

    Args:
        settings: Optional pre-built Settings instance. When ``None``,
            configuration is loaded via ``load_settings()`` (environment
            variables, ``proctx-crawler.yaml``, defaults).

    Returns:
        An ASGI application. When ``auth_api_key`` is configured the FastAPI
        app is wrapped in ``AuthMiddleware`` and the return type is the
        wrapped ASGI callable rather than the bare FastAPI instance.
    """
    resolved = settings if settings is not None else load_settings()

    app = FastAPI(title="ProContext Crawler", lifespan=_build_lifespan(resolved))
    app.include_router(router)
    register_error_handlers(app)
    app.state.settings = resolved

    if resolved.auth_api_key:
        return AuthMiddleware(app, api_key=resolved.auth_api_key)

    return app
