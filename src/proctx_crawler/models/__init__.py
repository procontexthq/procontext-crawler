"""Public data models for ProContext Crawler."""

from __future__ import annotations

from proctx_crawler.models.errors import (
    CrawlerError,
    ErrorCode,
    ErrorDetail,
    ErrorResponse,
    FetchError,
    InputValidationError,
    JobNotFoundError,
    RenderError,
)
from proctx_crawler.models.input import (
    CrawlConfig,
    CrawlOptions,
    GotoOptions,
    LinksInput,
    SinglePageInput,
)
from proctx_crawler.models.job import Job, JobStatus
from proctx_crawler.models.output import (
    CrawlRecord,
    CrawlResult,
    RecordMetadata,
    SuccessResponse,
)
from proctx_crawler.models.url_record import UrlRecord, UrlStatus

__all__ = [
    "CrawlConfig",
    "CrawlOptions",
    "CrawlRecord",
    "CrawlResult",
    "CrawlerError",
    "ErrorCode",
    "ErrorDetail",
    "ErrorResponse",
    "FetchError",
    "GotoOptions",
    "InputValidationError",
    "Job",
    "JobNotFoundError",
    "JobStatus",
    "LinksInput",
    "RecordMetadata",
    "RenderError",
    "SinglePageInput",
    "SuccessResponse",
    "UrlRecord",
    "UrlStatus",
]
