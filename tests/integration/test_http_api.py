"""Integration tests for the HTTP API.

These tests use httpx.AsyncClient with ASGI transport to exercise the
FastAPI routes end-to-end. The real app factory (create_app) is not used
to avoid the full lifespan; instead, a test app is built with real repo,
storage, and mocked fetcher, so the full request pipeline is exercised.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import anyio
import httpx
import pytest
from fastapi import FastAPI

from proctx_crawler.api.errors import register_error_handlers
from proctx_crawler.api.routes import router
from proctx_crawler.core.fetcher import FetchResult
from proctx_crawler.infrastructure.content_storage import ContentStorage
from proctx_crawler.infrastructure.sqlite_repository import SQLiteRepository
from proctx_crawler.models import ErrorCode, FetchError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from pytest_mock import MockerFixture


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def test_app(
    tmp_path: Path,
    mocker: MockerFixture,
    mock_pages: dict[str, tuple[int, str]],
) -> AsyncIterator[FastAPI]:
    """Create a test FastAPI app with real repo/storage but mocked HTTP fetcher."""
    app = FastAPI()
    app.include_router(router)
    register_error_handlers(app)

    repo = SQLiteRepository(tmp_path / "test.db")
    await repo.initialise()
    storage = ContentStorage(tmp_path / "output")
    browser_pool = MagicMock()

    app.state.repo = repo
    app.state.storage = storage
    app.state.browser_pool = browser_pool
    app.state.settings = MagicMock(auth_api_key=None, max_response_size=10_485_760)

    # Patch fetcher in routes and engine modules
    async def _mock_fetch(url: str, **_kwargs: object) -> FetchResult:
        if url not in mock_pages:
            raise FetchError(
                code=ErrorCode.NOT_FOUND,
                message=f"Page not found: {url}",
                recoverable=False,
            )
        status_code, html = mock_pages[url]
        return FetchResult(url=url, status_code=status_code, html=html, headers={})

    mocker.patch("proctx_crawler.core.page_service.fetch_static", side_effect=_mock_fetch)
    mocker.patch("proctx_crawler.core.engine.fetch_static", side_effect=_mock_fetch)

    async with anyio.create_task_group() as tg:
        app.state.task_group = tg
        yield app
        tg.cancel_scope.cancel()

    await repo.close()


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Create an httpx.AsyncClient connected to the test app via ASGI transport."""
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# POST /crawl -> GET /crawl lifecycle
# ---------------------------------------------------------------------------


class TestCrawlLifecycle:
    """Test the full POST -> GET crawl lifecycle."""

    @pytest.mark.anyio
    async def test_start_and_poll_crawl(self, client: httpx.AsyncClient) -> None:
        """POST /crawl starts a job; after a short wait, GET /crawl returns completed results."""
        # Start crawl
        resp = await client.post(
            "/crawl",
            json={
                "url": "https://docs.example.com",
                "limit": 2,
                "depth": 1,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        job_id = data["result"]
        uuid.UUID(job_id)  # validate it is a UUID

        # Poll until complete or timeout
        with anyio.fail_after(10):
            while True:
                poll = await client.get("/crawl", params={"id": job_id, "limit": 0})
                assert poll.status_code == 200
                poll_data = poll.json()["result"]
                if poll_data["status"] in ("completed", "errored", "cancelled"):
                    break
                await anyio.sleep(0.1)

        assert poll_data["status"] == "completed"
        assert poll_data["total"] >= 1

        # Fetch full results with records
        result_resp = await client.get("/crawl", params={"id": job_id})
        assert result_resp.status_code == 200
        result_data = result_resp.json()["result"]
        assert len(result_data["records"]) >= 1
        assert result_data["records"][0]["url"] is not None


# ---------------------------------------------------------------------------
# POST /crawl -> DELETE /crawl
# ---------------------------------------------------------------------------


class TestCrawlCancellation:
    """Test starting and cancelling a crawl."""

    @pytest.mark.anyio
    async def test_cancel_crawl(self, client: httpx.AsyncClient) -> None:
        """POST /crawl then DELETE /crawl should cancel the job."""
        resp = await client.post(
            "/crawl",
            json={
                "url": "https://docs.example.com",
                "limit": 100,
                "depth": 10,
            },
        )
        assert resp.status_code == 200
        job_id = resp.json()["result"]

        # Small delay to let job start
        await anyio.sleep(0.05)

        # Cancel the job
        cancel = await client.delete("/crawl", params={"id": job_id})
        assert cancel.status_code == 200
        assert cancel.json()["success"] is True
        assert cancel.json()["result"] == "cancelled"

        # Verify the job is in a terminal status
        with anyio.fail_after(10):
            while True:
                poll = await client.get("/crawl", params={"id": job_id, "limit": 0})
                status = poll.json()["result"]["status"]
                if status in ("completed", "cancelled", "errored"):
                    break
                await anyio.sleep(0.1)

        assert status in ("completed", "cancelled")


# ---------------------------------------------------------------------------
# GET /crawl with limit=0 (status-only)
# ---------------------------------------------------------------------------


class TestStatusOnly:
    """Test GET /crawl with limit=0 returns status only, no records."""

    @pytest.mark.anyio
    async def test_limit_zero_returns_status_only(self, client: httpx.AsyncClient) -> None:
        resp = await client.post(
            "/crawl",
            json={"url": "https://docs.example.com", "limit": 1},
        )
        job_id = resp.json()["result"]

        # Poll with limit=0
        with anyio.fail_after(10):
            while True:
                poll = await client.get("/crawl", params={"id": job_id, "limit": 0})
                data = poll.json()["result"]
                if data["status"] in ("completed", "errored", "cancelled"):
                    break
                await anyio.sleep(0.1)

        assert data["records"] == []
        assert data["cursor"] is None
        assert data["status"] == "completed"


# ---------------------------------------------------------------------------
# GET /crawl with pagination
# ---------------------------------------------------------------------------


class TestPagination:
    """Test GET /crawl pagination by using small limit values."""

    @pytest.mark.anyio
    async def test_paginate_through_results(self, client: httpx.AsyncClient) -> None:
        """Crawl several pages, then paginate through results."""
        resp = await client.post(
            "/crawl",
            json={"url": "https://docs.example.com", "limit": 3, "depth": 1},
        )
        job_id = resp.json()["result"]

        # Wait for completion
        with anyio.fail_after(10):
            while True:
                poll = await client.get("/crawl", params={"id": job_id, "limit": 0})
                if poll.json()["result"]["status"] == "completed":
                    break
                await anyio.sleep(0.1)

        # Paginate with limit=1
        all_records: list[dict[str, object]] = []
        cursor: str | None = None
        with anyio.fail_after(10):
            while True:
                params: dict[str, str | int] = {"id": job_id, "limit": 1}
                if cursor:
                    params["cursor"] = cursor
                page = await client.get("/crawl", params=params)
                page_data = page.json()["result"]
                all_records.extend(page_data["records"])
                cursor = page_data.get("cursor")
                if cursor is None:
                    break

        # We requested limit=3, so there should be exactly 3 completed
        total = poll.json()["result"]["total"]
        assert len(all_records) == total


# ---------------------------------------------------------------------------
# POST /markdown
# ---------------------------------------------------------------------------


class TestPostMarkdown:
    """Test POST /markdown endpoint."""

    @pytest.mark.anyio
    async def test_markdown_from_url(self, client: httpx.AsyncClient) -> None:
        resp = await client.post(
            "/markdown",
            json={"url": "https://docs.example.com"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "Docs Home" in data["result"]
        assert "Welcome to the docs" in data["result"]

    @pytest.mark.anyio
    async def test_markdown_from_html_body(self, client: httpx.AsyncClient) -> None:
        """Providing html directly should convert it to markdown without fetching."""
        resp = await client.post(
            "/markdown",
            json={"html": "<html><body><h1>Direct Title</h1><p>Direct body.</p></body></html>"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "Direct Title" in data["result"]
        assert "Direct body" in data["result"]


# ---------------------------------------------------------------------------
# POST /content
# ---------------------------------------------------------------------------


class TestPostContent:
    """Test POST /content endpoint."""

    @pytest.mark.anyio
    async def test_content_from_url(self, client: httpx.AsyncClient) -> None:
        resp = await client.post(
            "/content",
            json={"url": "https://docs.example.com"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "<html>" in data["result"]
        assert "Welcome to the docs" in data["result"]


# ---------------------------------------------------------------------------
# POST /links
# ---------------------------------------------------------------------------


class TestPostLinks:
    """Test POST /links endpoint."""

    @pytest.mark.anyio
    async def test_links_from_url(self, client: httpx.AsyncClient) -> None:
        resp = await client.post(
            "/links",
            json={"url": "https://docs.example.com"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        result = data["result"]
        assert isinstance(result, list)
        assert "https://docs.example.com/getting-started" in result
        assert "https://external.example.org/resource" in result

    @pytest.mark.anyio
    async def test_links_exclude_external(self, client: httpx.AsyncClient) -> None:
        resp = await client.post(
            "/links",
            json={
                "url": "https://docs.example.com",
                "exclude_external_links": True,
            },
        )
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert "https://docs.example.com/getting-started" in result
        assert "https://external.example.org/resource" not in result

    @pytest.mark.anyio
    async def test_links_rejects_html_only_input(self, client: httpx.AsyncClient) -> None:
        resp = await client.post(
            "/links",
            json={"html": "<a href='https://docs.example.com/getting-started'>Start</a>"},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# 404 for missing job
# ---------------------------------------------------------------------------


class TestMissingJob:
    """Test 404 responses for non-existent job IDs."""

    @pytest.mark.anyio
    async def test_get_missing_job(self, client: httpx.AsyncClient) -> None:
        resp = await client.get("/crawl", params={"id": "nonexistent-id"})
        assert resp.status_code == 404
        data = resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "JOB_NOT_FOUND"

    @pytest.mark.anyio
    async def test_delete_missing_job(self, client: httpx.AsyncClient) -> None:
        resp = await client.delete("/crawl", params={"id": "nonexistent-id"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Error envelope format
# ---------------------------------------------------------------------------


class TestErrorEnvelope:
    """Verify error responses follow the spec error envelope format."""

    @pytest.mark.anyio
    async def test_fetch_error_envelope(self, client: httpx.AsyncClient) -> None:
        """A FetchError from a non-existent URL should produce a proper error envelope."""
        resp = await client.post(
            "/markdown",
            json={"url": "https://docs.example.com/nonexistent"},
        )
        assert resp.status_code == 404
        data = resp.json()
        assert data["success"] is False
        assert "error" in data
        error = data["error"]
        assert "code" in error
        assert "message" in error
        assert "recoverable" in error
        assert isinstance(error["recoverable"], bool)

    @pytest.mark.anyio
    async def test_validation_error_envelope(self, client: httpx.AsyncClient) -> None:
        """Invalid input should produce the standard 400 error envelope."""
        resp = await client.post("/crawl", json={})
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_INPUT"
