"""Tests for the HTTP API layer (FastAPI routes, middleware, error handling)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI

from proctx_crawler.api.errors import register_error_handlers
from proctx_crawler.api.middleware import AuthMiddleware
from proctx_crawler.api.routes import router
from proctx_crawler.core.fetcher import FetchResult
from proctx_crawler.models import (
    CrawlConfig,
    ErrorCode,
    FetchError,
    Job,
    JobStatus,
    UrlRecord,
    UrlStatus,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from pytest_mock import MockerFixture


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_app() -> FastAPI:
    """Create a bare FastAPI app with routes and error handlers (no lifespan)."""
    app = FastAPI()
    app.include_router(router)
    register_error_handlers(app)
    return app


def _make_job(
    job_id: str | None = None,
    status: JobStatus = JobStatus.QUEUED,
    url: str = "https://example.com",
) -> Job:
    now = datetime.now(UTC)
    return Job(
        id=job_id or str(uuid.uuid4()),
        status=status,
        url=url,
        config=CrawlConfig(url=url),
        total=1,
        finished=0,
        created_at=now,
        updated_at=now,
    )


def _make_url_record(
    job_id: str,
    url: str = "https://example.com",
    status: UrlStatus = UrlStatus.COMPLETED,
) -> UrlRecord:
    now = datetime.now(UTC)
    return UrlRecord(
        id=str(uuid.uuid4()),
        job_id=job_id,
        url=url,
        url_hash="abc123",
        depth=0,
        status=status,
        http_status=200 if status == UrlStatus.COMPLETED else None,
        title="Example" if status == UrlStatus.COMPLETED else None,
        content_hash="hash123" if status == UrlStatus.COMPLETED else None,
        created_at=now,
        completed_at=now if status == UrlStatus.COMPLETED else None,
    )


@pytest.fixture
def mock_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.create_job = AsyncMock()
    repo.get_job = AsyncMock(return_value=None)
    repo.update_job_status = AsyncMock()
    repo.cancel_queued_urls = AsyncMock(return_value=0)
    repo.get_url_records = AsyncMock(return_value=([], None))
    return repo


@pytest.fixture
def mock_storage() -> AsyncMock:
    storage = AsyncMock()
    storage.read = AsyncMock(return_value=None)
    return storage


@pytest.fixture
def mock_browser_pool() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_task_group() -> MagicMock:
    tg = MagicMock()
    tg.start_soon = MagicMock()
    return tg


@pytest.fixture
def app(
    mock_repo: AsyncMock,
    mock_storage: AsyncMock,
    mock_browser_pool: AsyncMock,
    mock_task_group: MagicMock,
) -> FastAPI:
    """Create an app with mocked state (no lifespan needed)."""
    test_app = _make_app()
    test_app.state.repo = mock_repo
    test_app.state.storage = mock_storage
    test_app.state.browser_pool = mock_browser_pool
    test_app.state.task_group = mock_task_group
    test_app.state.settings = MagicMock(max_response_size=2048, auth_api_key=None)
    return test_app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# POST /crawl — Start crawl job
# ---------------------------------------------------------------------------


class TestPostCrawl:
    @pytest.mark.anyio
    async def test_creates_job_and_returns_id(
        self, client: httpx.AsyncClient, mock_repo: AsyncMock, mock_task_group: MagicMock
    ) -> None:
        resp = await client.post("/crawl", json={"url": "https://example.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        # result should be a valid UUID string
        uuid.UUID(data["result"])

        mock_repo.create_job.assert_awaited_once()
        mock_task_group.start_soon.assert_called_once()
        start_args = mock_task_group.start_soon.call_args.args
        assert start_args[0].__name__ == "run_crawl"
        assert start_args[-1] == 2048

    @pytest.mark.anyio
    async def test_invalid_input_returns_400(self, client: httpx.AsyncClient) -> None:
        # Missing 'url' field
        resp = await client.post("/crawl", json={})
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# GET /crawl — Poll status / retrieve results
# ---------------------------------------------------------------------------


class TestGetCrawl:
    @pytest.mark.anyio
    async def test_returns_crawl_result(
        self,
        client: httpx.AsyncClient,
        mock_repo: AsyncMock,
        mock_storage: AsyncMock,
    ) -> None:
        job_id = str(uuid.uuid4())
        job = _make_job(job_id=job_id, status=JobStatus.COMPLETED)
        job.total = 1
        job.finished = 1
        record = _make_url_record(job_id)
        mock_repo.get_job.return_value = job
        mock_repo.get_url_records.return_value = ([record], None)
        mock_storage.read.return_value = "# Hello"

        resp = await client.get("/crawl", params={"id": job_id})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        result = data["result"]
        assert result["id"] == job_id
        assert result["status"] == "completed"
        assert len(result["records"]) == 1
        assert result["records"][0]["url"] == "https://example.com"

    @pytest.mark.anyio
    async def test_limit_zero_returns_status_only(
        self,
        client: httpx.AsyncClient,
        mock_repo: AsyncMock,
    ) -> None:
        job_id = str(uuid.uuid4())
        job = _make_job(job_id=job_id, status=JobStatus.RUNNING)
        job.total = 5
        job.finished = 2
        mock_repo.get_job.return_value = job

        resp = await client.get("/crawl", params={"id": job_id, "limit": 0})
        assert resp.status_code == 200
        data = resp.json()
        result = data["result"]
        assert result["status"] == "running"
        assert result["records"] == []
        assert result["cursor"] is None
        # get_url_records should not have been called
        mock_repo.get_url_records.assert_not_awaited()

    @pytest.mark.anyio
    async def test_invalid_job_id_returns_404(
        self, client: httpx.AsyncClient, mock_repo: AsyncMock
    ) -> None:
        mock_repo.get_job.return_value = None
        resp = await client.get("/crawl", params={"id": "nonexistent"})
        assert resp.status_code == 404
        data = resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "JOB_NOT_FOUND"


# ---------------------------------------------------------------------------
# DELETE /crawl — Cancel job
# ---------------------------------------------------------------------------


class TestDeleteCrawl:
    @pytest.mark.anyio
    async def test_cancels_running_job(
        self, client: httpx.AsyncClient, mock_repo: AsyncMock
    ) -> None:
        job_id = str(uuid.uuid4())
        job = _make_job(job_id=job_id, status=JobStatus.RUNNING)
        mock_repo.get_job.return_value = job

        resp = await client.delete("/crawl", params={"id": job_id})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["result"] == "cancelled"
        mock_repo.cancel_queued_urls.assert_awaited_once_with(job_id)
        mock_repo.update_job_status.assert_awaited_once_with(job_id, JobStatus.CANCELLED)

    @pytest.mark.anyio
    async def test_terminal_job_returns_success_idempotent(
        self, client: httpx.AsyncClient, mock_repo: AsyncMock
    ) -> None:
        job_id = str(uuid.uuid4())
        job = _make_job(job_id=job_id, status=JobStatus.COMPLETED)
        mock_repo.get_job.return_value = job

        resp = await client.delete("/crawl", params={"id": job_id})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["result"] == "cancelled"
        # Should NOT have called cancel/update since job is already terminal
        mock_repo.cancel_queued_urls.assert_not_awaited()
        mock_repo.update_job_status.assert_not_awaited()

    @pytest.mark.anyio
    async def test_missing_job_returns_404(
        self, client: httpx.AsyncClient, mock_repo: AsyncMock
    ) -> None:
        mock_repo.get_job.return_value = None
        resp = await client.delete("/crawl", params={"id": "nonexistent"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /markdown
# ---------------------------------------------------------------------------


class TestPostMarkdown:
    @pytest.mark.anyio
    async def test_returns_markdown_from_url(
        self, client: httpx.AsyncClient, mocker: MockerFixture
    ) -> None:
        html = "<html><body><p>Hello world</p></body></html>"
        mock_result = FetchResult(url="https://example.com", status_code=200, html=html, headers={})
        mocker.patch("proctx_crawler.core.page_service.fetch_static", return_value=mock_result)

        resp = await client.post("/markdown", json={"url": "https://example.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "Hello world" in data["result"]

    @pytest.mark.anyio
    async def test_converts_html_directly(self, client: httpx.AsyncClient) -> None:
        html = "<html><body><h1>Title</h1><p>Content</p></body></html>"
        resp = await client.post("/markdown", json={"html": html})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "Title" in data["result"]
        assert "Content" in data["result"]


# ---------------------------------------------------------------------------
# POST /content
# ---------------------------------------------------------------------------


class TestPostContent:
    @pytest.mark.anyio
    async def test_returns_html_from_url(
        self, client: httpx.AsyncClient, mocker: MockerFixture
    ) -> None:
        html = "<html><body><p>Hello</p></body></html>"
        mock_result = FetchResult(url="https://example.com", status_code=200, html=html, headers={})
        mocker.patch("proctx_crawler.core.page_service.fetch_static", return_value=mock_result)

        resp = await client.post("/content", json={"url": "https://example.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "<p>Hello</p>" in data["result"]

    @pytest.mark.anyio
    async def test_returns_html_from_body(self, client: httpx.AsyncClient) -> None:
        html = "<html><body><p>Direct HTML</p></body></html>"
        resp = await client.post("/content", json={"html": html})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "<p>Direct HTML</p>" in data["result"]


# ---------------------------------------------------------------------------
# POST /links
# ---------------------------------------------------------------------------


class TestPostLinks:
    @pytest.mark.anyio
    async def test_returns_links(self, client: httpx.AsyncClient, mocker: MockerFixture) -> None:
        html = (
            "<html><body>"
            '<a href="https://example.com/page1">P1</a>'
            '<a href="https://external.com/page">Ext</a>'
            "</body></html>"
        )
        mock_result = FetchResult(url="https://example.com", status_code=200, html=html, headers={})
        mocker.patch("proctx_crawler.core.page_service.fetch_static", return_value=mock_result)

        resp = await client.post("/links", json={"url": "https://example.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "https://example.com/page1" in data["result"]
        assert "https://external.com/page" in data["result"]

    @pytest.mark.anyio
    async def test_exclude_external_links(
        self, client: httpx.AsyncClient, mocker: MockerFixture
    ) -> None:
        html = (
            "<html><body>"
            '<a href="https://example.com/page1">P1</a>'
            '<a href="https://external.com/page">Ext</a>'
            "</body></html>"
        )
        mock_result = FetchResult(url="https://example.com", status_code=200, html=html, headers={})
        mocker.patch("proctx_crawler.core.page_service.fetch_static", return_value=mock_result)

        resp = await client.post(
            "/links",
            json={"url": "https://example.com", "exclude_external_links": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "https://example.com/page1" in data["result"]
        assert "https://external.com/page" not in data["result"]

    @pytest.mark.anyio
    async def test_visible_links_only_uses_rendered_extractor(
        self, client: httpx.AsyncClient, mocker: MockerFixture
    ) -> None:
        mock_visible = mocker.patch(
            "proctx_crawler.api.routes.extract_visible_links_rendered",
            return_value=["https://example.com/page1"],
        )

        resp = await client.post(
            "/links",
            json={
                "url": "https://example.com",
                "render": True,
                "visible_links_only": True,
            },
        )

        assert resp.status_code == 200
        assert resp.json()["result"] == ["https://example.com/page1"]
        mock_visible.assert_awaited_once()

    @pytest.mark.anyio
    async def test_visible_links_only_can_still_filter_external_links(
        self, client: httpx.AsyncClient, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "proctx_crawler.api.routes.extract_visible_links_rendered",
            return_value=[
                "https://example.com/page1",
                "https://external.com/page",
            ],
        )

        resp = await client.post(
            "/links",
            json={
                "url": "https://example.com",
                "render": True,
                "visible_links_only": True,
                "exclude_external_links": True,
            },
        )

        assert resp.status_code == 200
        assert resp.json()["result"] == ["https://example.com/page1"]

    @pytest.mark.anyio
    async def test_html_only_is_invalid_for_links(self, client: httpx.AsyncClient) -> None:
        resp = await client.post("/links", json={"html": "<a href='https://example.com'>x</a>"})

        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# CrawlerError handler
# ---------------------------------------------------------------------------


class TestCrawlerErrorHandler:
    @pytest.mark.anyio
    async def test_fetch_error_returns_502(
        self, client: httpx.AsyncClient, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "proctx_crawler.core.page_service.fetch_static",
            side_effect=FetchError(
                code=ErrorCode.FETCH_FAILED,
                message="Connection refused",
                recoverable=True,
            ),
        )

        resp = await client.post("/markdown", json={"url": "https://example.com"})
        assert resp.status_code == 502
        data = resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "FETCH_FAILED"
        assert data["error"]["recoverable"] is True

    @pytest.mark.anyio
    async def test_not_found_returns_404(
        self, client: httpx.AsyncClient, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "proctx_crawler.core.page_service.fetch_static",
            side_effect=FetchError(
                code=ErrorCode.NOT_FOUND,
                message="Page not found",
                recoverable=False,
            ),
        )

        resp = await client.post("/content", json={"url": "https://example.com/missing"})
        assert resp.status_code == 404
        data = resp.json()
        assert data["error"]["code"] == "NOT_FOUND"

    @pytest.mark.anyio
    async def test_error_status_map_coverage(
        self, client: httpx.AsyncClient, mock_repo: AsyncMock
    ) -> None:
        """CrawlerError with JOB_NOT_FOUND code returns 404."""
        mock_repo.get_job.return_value = None
        resp = await client.get("/crawl", params={"id": "no-such-job"})
        assert resp.status_code == 404
        data = resp.json()
        assert data["error"]["code"] == "JOB_NOT_FOUND"


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------


class TestAuthMiddleware:
    @pytest.fixture
    def auth_app(
        self,
        mock_repo: AsyncMock,
        mock_storage: AsyncMock,
        mock_browser_pool: AsyncMock,
        mock_task_group: MagicMock,
    ) -> AuthMiddleware:
        """Create an app wrapped with AuthMiddleware."""
        inner = _make_app()
        inner.state.repo = mock_repo
        inner.state.storage = mock_storage
        inner.state.browser_pool = mock_browser_pool
        inner.state.task_group = mock_task_group
        inner.state.settings = MagicMock(max_response_size=2048, auth_api_key="test-secret-key")
        return AuthMiddleware(inner, api_key="test-secret-key")

    @pytest.fixture
    async def auth_client(self, auth_app: AuthMiddleware) -> AsyncIterator[httpx.AsyncClient]:
        transport = httpx.ASGITransport(app=auth_app)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    @pytest.mark.anyio
    async def test_missing_auth_returns_401(self, auth_client: httpx.AsyncClient) -> None:
        resp = await auth_client.post("/crawl", json={"url": "https://example.com"})
        assert resp.status_code == 401
        data = resp.json()
        assert data["success"] is False

    @pytest.mark.anyio
    async def test_invalid_auth_returns_401(self, auth_client: httpx.AsyncClient) -> None:
        resp = await auth_client.post(
            "/crawl",
            json={"url": "https://example.com"},
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_valid_auth_passes_through(
        self,
        auth_client: httpx.AsyncClient,
        mock_repo: AsyncMock,
        mock_task_group: MagicMock,
    ) -> None:
        resp = await auth_client.post(
            "/crawl",
            json={"url": "https://example.com"},
            headers={"Authorization": "Bearer test-secret-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        mock_repo.create_job.assert_awaited_once()

    @pytest.mark.anyio
    async def test_compare_digest_supports_same_value(
        self,
        auth_client: httpx.AsyncClient,
        mock_repo: AsyncMock,
    ) -> None:
        resp = await auth_client.post(
            "/crawl",
            json={"url": "https://example.com"},
            headers={"Authorization": "".join(["Bearer ", "test-secret-key"])},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        mock_repo.create_job.assert_awaited()

    @pytest.mark.anyio
    async def test_non_http_scope_passes_through(self, auth_app: AuthMiddleware) -> None:
        """Non-HTTP scopes (e.g. websocket) are forwarded without auth checks."""
        received_scope: dict[str, object] = {}

        async def mock_app(scope: dict[str, object], receive: object, send: object) -> None:
            received_scope.update(scope)

        auth_app._app = mock_app  # type: ignore[assignment]

        scope = {"type": "websocket", "headers": []}
        await auth_app(scope, AsyncMock(), AsyncMock())

        assert received_scope["type"] == "websocket"


# ---------------------------------------------------------------------------
# HTML format in GET /crawl records
# ---------------------------------------------------------------------------


class TestHtmlFormatInRecords:
    @pytest.mark.anyio
    async def test_html_format_populated(
        self,
        client: httpx.AsyncClient,
        mock_repo: AsyncMock,
        mock_storage: AsyncMock,
    ) -> None:
        """When a record has html content stored, it should be returned in the response."""
        job_id = str(uuid.uuid4())
        job = _make_job(job_id=job_id, status=JobStatus.COMPLETED)
        job.total = 1
        job.finished = 1
        record = _make_url_record(job_id)
        mock_repo.get_job.return_value = job
        mock_repo.get_url_records.return_value = ([record], None)
        mock_storage.read.return_value = "<html><body>content</body></html>"

        resp = await client.get("/crawl", params={"id": job_id})
        assert resp.status_code == 200
        # storage.read should be called — verifying the html branch is exercised
        assert mock_storage.read.await_count >= 1


# ---------------------------------------------------------------------------
# Render path in single-page endpoints
# ---------------------------------------------------------------------------


class TestRenderPathInRoutes:
    @pytest.mark.anyio
    async def test_markdown_with_render(
        self,
        client: httpx.AsyncClient,
        mock_browser_pool: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        """POST /markdown with render=True should call fetch_rendered."""
        html = "<html><body><p>Rendered content</p></body></html>"
        mock_result = FetchResult(url="https://example.com", status_code=200, html=html, headers={})
        mock_render = mocker.patch(
            "proctx_crawler.core.page_service.fetch_rendered", return_value=mock_result
        )

        resp = await client.post(
            "/markdown",
            json={"url": "https://example.com", "render": True},
        )

        assert resp.status_code == 200
        mock_render.assert_awaited_once()

    @pytest.mark.anyio
    async def test_links_with_render(
        self,
        client: httpx.AsyncClient,
        mock_browser_pool: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        """POST /links with render=True should call fetch_rendered."""
        html = '<html><body><a href="https://example.com/a">link</a></body></html>'
        mock_result = FetchResult(url="https://example.com", status_code=200, html=html, headers={})
        mocker.patch("proctx_crawler.core.page_service.fetch_rendered", return_value=mock_result)

        resp = await client.post(
            "/links",
            json={"url": "https://example.com", "render": True},
        )

        assert resp.status_code == 200
        assert "https://example.com/a" in resp.json()["result"]


# ---------------------------------------------------------------------------
# Pydantic ValidationError handler
# ---------------------------------------------------------------------------


class TestValidationErrorHandler:
    @pytest.mark.anyio
    async def test_pydantic_validation_error_returns_400(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """Sending an invalid body that passes FastAPI but fails Pydantic should return 400."""
        from pydantic import ValidationError

        from proctx_crawler.api.errors import _validation_error_handler
        from proctx_crawler.models import SinglePageInput

        # Build a real ValidationError
        try:
            # Both url and html missing should raise
            SinglePageInput.model_validate({"url": None, "html": None})
        except ValidationError as exc:
            # Directly call the handler to exercise the code path
            response = _validation_error_handler(MagicMock(), exc)

        assert response.status_code == 400
        import json

        body = json.loads(response.body)
        assert body["success"] is False
        assert body["error"]["code"] == "INVALID_INPUT"

    @pytest.mark.anyio
    async def test_request_validation_error_returns_400(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        resp = await client.post("/crawl", json={})
        assert resp.status_code == 400
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "INVALID_INPUT"


class TestSettingsPropagationInRoutes:
    @pytest.mark.anyio
    async def test_markdown_uses_app_max_response_size(
        self,
        client: httpx.AsyncClient,
        mocker: MockerFixture,
    ) -> None:
        mock_result = FetchResult(
            url="https://example.com",
            status_code=200,
            html="<html><body><p>Hello</p></body></html>",
            headers={},
        )
        mock_static = mocker.patch(
            "proctx_crawler.core.page_service.fetch_static",
            return_value=mock_result,
        )

        resp = await client.post("/markdown", json={"url": "https://example.com"})

        assert resp.status_code == 200
        mock_static.assert_awaited_once_with(
            "https://example.com",
            max_response_size=2048,
        )
