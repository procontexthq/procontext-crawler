"""Tests for all data models: creation, validation, serialisation, and errors."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from proctx_crawler.models import (
    CrawlConfig,
    CrawlerError,
    CrawlOptions,
    CrawlRecord,
    CrawlResult,
    ErrorCode,
    ErrorDetail,
    ErrorResponse,
    FetchError,
    GotoOptions,
    InputValidationError,
    Job,
    JobNotFoundError,
    JobStatus,
    LinksInput,
    RecordMetadata,
    RenderError,
    SinglePageInput,
    SuccessResponse,
    UrlRecord,
    UrlStatus,
)

# ---------------------------------------------------------------------------
# ErrorCode enum
# ---------------------------------------------------------------------------


class TestErrorCode:
    def test_all_values_present(self) -> None:
        expected = {
            "INVALID_INPUT",
            "FETCH_FAILED",
            "NOT_FOUND",
            "JOB_NOT_FOUND",
            "RENDER_FAILED",
            "INVALID_SELECTOR",
            "DISALLOWED",
            "EXTRACTION_FAILED",
        }
        assert {e.value for e in ErrorCode} == expected

    def test_string_representation(self) -> None:
        assert str(ErrorCode.FETCH_FAILED) == "FETCH_FAILED"


# ---------------------------------------------------------------------------
# ErrorDetail / ErrorResponse
# ---------------------------------------------------------------------------


class TestErrorModels:
    def test_error_detail_creation(self) -> None:
        detail = ErrorDetail(code=ErrorCode.FETCH_FAILED, message="timeout", recoverable=True)
        assert detail.code == ErrorCode.FETCH_FAILED
        assert detail.message == "timeout"
        assert detail.recoverable is True

    def test_error_response_success_is_false(self) -> None:
        resp = ErrorResponse(
            error=ErrorDetail(code=ErrorCode.NOT_FOUND, message="gone", recoverable=False)
        )
        assert resp.success is False

    def test_error_response_serialisation_roundtrip(self) -> None:
        resp = ErrorResponse(
            error=ErrorDetail(code=ErrorCode.INVALID_INPUT, message="bad field", recoverable=False)
        )
        data = resp.model_dump()
        restored = ErrorResponse.model_validate(data)
        assert restored == resp


# ---------------------------------------------------------------------------
# CrawlerError and subclasses
# ---------------------------------------------------------------------------


class TestCrawlerErrors:
    def test_base_error_attributes(self) -> None:
        err = CrawlerError(ErrorCode.FETCH_FAILED, "network error", recoverable=True)
        assert err.code == ErrorCode.FETCH_FAILED
        assert err.message == "network error"
        assert err.recoverable is True
        assert str(err) == "network error"

    def test_default_recoverable_is_false(self) -> None:
        err = CrawlerError(ErrorCode.NOT_FOUND, "missing")
        assert err.recoverable is False

    def test_fetch_error_is_crawler_error(self) -> None:
        err = FetchError(ErrorCode.FETCH_FAILED, "timeout", recoverable=True)
        assert isinstance(err, CrawlerError)
        assert err.code == ErrorCode.FETCH_FAILED

    def test_render_error(self) -> None:
        err = RenderError(ErrorCode.RENDER_FAILED, "crash")
        assert isinstance(err, CrawlerError)
        assert err.code == ErrorCode.RENDER_FAILED

    def test_job_not_found_error(self) -> None:
        err = JobNotFoundError(ErrorCode.JOB_NOT_FOUND, "no such job")
        assert isinstance(err, CrawlerError)

    def test_input_validation_error(self) -> None:
        err = InputValidationError(ErrorCode.INVALID_INPUT, "bad url")
        assert isinstance(err, CrawlerError)
        assert err.code == ErrorCode.INVALID_INPUT


# ---------------------------------------------------------------------------
# GotoOptions
# ---------------------------------------------------------------------------


class TestGotoOptions:
    def test_defaults(self) -> None:
        opts = GotoOptions()
        assert opts.wait_until == "load"
        assert opts.timeout == 30000

    def test_timeout_min(self) -> None:
        with pytest.raises(ValidationError):
            GotoOptions(timeout=999)

    def test_timeout_max(self) -> None:
        with pytest.raises(ValidationError):
            GotoOptions(timeout=120001)

    def test_timeout_boundaries_ok(self) -> None:
        assert GotoOptions(timeout=1000).timeout == 1000
        assert GotoOptions(timeout=120000).timeout == 120000

    def test_wait_until_values(self) -> None:
        for val in ("load", "domcontentloaded", "networkidle0", "networkidle2"):
            assert GotoOptions(wait_until=val).wait_until == val  # type: ignore[arg-type]

    def test_invalid_wait_until(self) -> None:
        with pytest.raises(ValidationError):
            GotoOptions(wait_until="invalid")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# CrawlOptions
# ---------------------------------------------------------------------------


class TestCrawlOptions:
    def test_defaults(self) -> None:
        opts = CrawlOptions()
        assert opts.include_patterns is None
        assert opts.exclude_patterns is None
        assert opts.include_subdomains is False
        assert opts.include_external_links is False


# ---------------------------------------------------------------------------
# CrawlConfig
# ---------------------------------------------------------------------------


class TestCrawlConfig:
    def test_defaults(self) -> None:
        cfg = CrawlConfig(url="https://example.com")
        assert cfg.limit == 10
        assert cfg.depth == 1000
        assert cfg.source == "links"
        assert cfg.formats == ["markdown"]
        assert cfg.render is False
        assert cfg.goto_options is None
        assert cfg.wait_for_selector is None
        assert cfg.reject_resource_types is None
        assert isinstance(cfg.options, CrawlOptions)

    def test_limit_min(self) -> None:
        with pytest.raises(ValidationError):
            CrawlConfig(url="https://example.com", limit=0)

    def test_depth_min(self) -> None:
        # depth=0 is valid (no crawling beyond seed)
        cfg = CrawlConfig(url="https://example.com", depth=0)
        assert cfg.depth == 0

    def test_negative_depth(self) -> None:
        with pytest.raises(ValidationError):
            CrawlConfig(url="https://example.com", depth=-1)

    def test_full_config(self) -> None:
        cfg = CrawlConfig(
            url="https://docs.example.com",
            limit=50,
            depth=3,
            source="llms_txt",
            formats=["markdown", "html"],
            render=True,
            goto_options=GotoOptions(wait_until="networkidle0", timeout=60000),
            wait_for_selector="#content",
            reject_resource_types=["image", "font"],
            options=CrawlOptions(
                include_patterns=["https://docs.example.com/**"],
                exclude_patterns=["**/api/**"],
                include_subdomains=True,
            ),
        )
        assert cfg.source == "llms_txt"
        assert cfg.goto_options is not None
        assert cfg.goto_options.timeout == 60000

    def test_serialisation_roundtrip(self) -> None:
        cfg = CrawlConfig(url="https://example.com", limit=5)
        data = cfg.model_dump()
        restored = CrawlConfig.model_validate(data)
        assert restored == cfg


# ---------------------------------------------------------------------------
# SinglePageInput
# ---------------------------------------------------------------------------


class TestSinglePageInput:
    def test_url_only(self) -> None:
        inp = SinglePageInput(url="https://example.com")
        assert inp.url == "https://example.com"
        assert inp.html is None

    def test_html_only(self) -> None:
        inp = SinglePageInput(html="<h1>Hello</h1>")
        assert inp.html == "<h1>Hello</h1>"
        assert inp.url is None

    def test_both_raises(self) -> None:
        with pytest.raises(ValidationError, match="not both"):
            SinglePageInput(url="https://example.com", html="<h1>Hello</h1>")

    def test_neither_raises(self) -> None:
        with pytest.raises(ValidationError, match="must be provided"):
            SinglePageInput()

    def test_defaults(self) -> None:
        inp = SinglePageInput(url="https://example.com")
        assert inp.render is False
        assert inp.goto_options is None
        assert inp.wait_for_selector is None
        assert inp.reject_resource_types is None


# ---------------------------------------------------------------------------
# LinksInput
# ---------------------------------------------------------------------------


class TestLinksInput:
    def test_inherits_validation(self) -> None:
        with pytest.raises(ValidationError):
            LinksInput()

    def test_extra_fields(self) -> None:
        inp = LinksInput(url="https://example.com", visible_links_only=True)
        assert inp.visible_links_only is True
        assert inp.exclude_external_links is False

    def test_rejects_html_only(self) -> None:
        with pytest.raises(ValidationError):
            LinksInput(html="<a href='https://example.com'>x</a>")


# ---------------------------------------------------------------------------
# JobStatus / Job
# ---------------------------------------------------------------------------


class TestJobModels:
    def test_job_status_values(self) -> None:
        expected = {"queued", "running", "completed", "cancelled", "errored"}
        assert {s.value for s in JobStatus} == expected

    def test_job_creation(self) -> None:
        now = datetime.now(UTC)
        job = Job(
            id="abc-123",
            url="https://example.com",
            config=CrawlConfig(url="https://example.com"),
            created_at=now,
            updated_at=now,
        )
        assert job.status == JobStatus.QUEUED
        assert job.total == 0
        assert job.finished == 0
        assert job.started_at is None
        assert job.finished_at is None

    def test_job_serialisation_roundtrip(self) -> None:
        now = datetime.now(UTC)
        job = Job(
            id="abc-123",
            url="https://example.com",
            config=CrawlConfig(url="https://example.com"),
            created_at=now,
            updated_at=now,
            started_at=now,
        )
        data = job.model_dump()
        restored = Job.model_validate(data)
        assert restored == job


# ---------------------------------------------------------------------------
# UrlStatus / UrlRecord
# ---------------------------------------------------------------------------


class TestUrlRecordModels:
    def test_url_status_values(self) -> None:
        expected = {
            "queued",
            "running",
            "completed",
            "errored",
            "skipped",
            "cancelled",
            "disallowed",
        }
        assert {s.value for s in UrlStatus} == expected

    def test_url_record_creation(self) -> None:
        now = datetime.now(UTC)
        record = UrlRecord(
            id="rec-1",
            job_id="job-1",
            url="https://example.com/page",
            url_hash="abcdef1234567890",
            depth=1,
            created_at=now,
        )
        assert record.status == UrlStatus.QUEUED
        assert record.http_status is None
        assert record.error_message is None
        assert record.content_hash is None
        assert record.title is None
        assert record.completed_at is None

    def test_url_record_serialisation_roundtrip(self) -> None:
        now = datetime.now(UTC)
        record = UrlRecord(
            id="rec-1",
            job_id="job-1",
            url="https://example.com/page",
            url_hash="abcdef1234567890",
            depth=0,
            status=UrlStatus.COMPLETED,
            http_status=200,
            title="Example",
            content_hash="sha256:abc",
            created_at=now,
            completed_at=now,
        )
        data = record.model_dump()
        restored = UrlRecord.model_validate(data)
        assert restored == record


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------


class TestOutputModels:
    def test_record_metadata(self) -> None:
        meta = RecordMetadata(http_status=200, title="Hello")
        assert meta.content_hash is None

    def test_crawl_record(self) -> None:
        rec = CrawlRecord(url="https://example.com", status=UrlStatus.COMPLETED, markdown="# Hi")
        assert rec.html is None
        assert rec.metadata is None

    def test_crawl_result(self) -> None:
        result = CrawlResult(
            id="job-1",
            status=JobStatus.COMPLETED,
            total=5,
            finished=5,
            records=[
                CrawlRecord(url="https://example.com", status=UrlStatus.COMPLETED, markdown="# A")
            ],
        )
        assert result.cursor is None
        assert len(result.records) == 1

    def test_success_response_with_string(self) -> None:
        resp = SuccessResponse[str](result="hello")
        assert resp.success is True
        assert resp.result == "hello"

    def test_success_response_with_crawl_result(self) -> None:
        cr = CrawlResult(id="j1", status=JobStatus.RUNNING, total=10, finished=3, records=[])
        resp = SuccessResponse[CrawlResult](result=cr)
        assert resp.success is True
        assert resp.result.id == "j1"

    def test_success_response_serialisation(self) -> None:
        resp = SuccessResponse[str](result="test")
        data = resp.model_dump()
        assert data == {"success": True, "result": "test"}

    def test_success_response_with_list(self) -> None:
        resp = SuccessResponse[list[str]](result=["a", "b"])
        data = resp.model_dump()
        assert data["result"] == ["a", "b"]
