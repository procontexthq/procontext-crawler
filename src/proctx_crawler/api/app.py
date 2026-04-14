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
from proctx_crawler.config import load_settings
from proctx_crawler.core.browser_pool import BrowserPool
from proctx_crawler.infrastructure.content_storage import ContentStorage
from proctx_crawler.infrastructure.sqlite_repository import SQLiteRepository

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

log: structlog.stdlib.BoundLogger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application-wide resources: repository, storage, browser pool, and task group."""
    settings = load_settings()
    repo = SQLiteRepository(settings.db_path)
    await repo.initialise()
    storage = ContentStorage(settings.output_dir)
    browser_pool = BrowserPool(headless=settings.playwright_headless)
    await browser_pool.start()

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


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    app = FastAPI(title="ProContext Crawler", lifespan=lifespan)
    app.include_router(router)
    register_error_handlers(app)

    # Auth middleware is applied at create_app time if settings provide an API key.
    # We load settings here just to check; the lifespan will also load them.
    settings = load_settings()
    if settings.auth_api_key:
        app = FastAPI(title="ProContext Crawler", lifespan=lifespan)
        app.include_router(router)
        register_error_handlers(app)
        app.state.auth_api_key = settings.auth_api_key
        # Wrap with ASGI middleware — must wrap the full app
        return AuthMiddleware(app, api_key=settings.auth_api_key)  # type: ignore[return-value]

    return app
