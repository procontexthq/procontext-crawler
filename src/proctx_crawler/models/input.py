"""API input models for crawl configuration and single-page requests."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


class GotoOptions(BaseModel):
    """Playwright navigation options."""

    wait_until: Literal["load", "domcontentloaded", "networkidle0", "networkidle2"] = "load"
    timeout: int = Field(default=30000, ge=1000, le=120000)


class CrawlOptions(BaseModel):
    """URL filtering options for multi-page crawls."""

    include_patterns: list[str] | None = None
    exclude_patterns: list[str] | None = None
    include_subdomains: bool = False
    include_external_links: bool = False


class CrawlConfig(BaseModel):
    """Input for POST /crawl."""

    url: str
    limit: int = Field(default=10, ge=1)
    depth: int = Field(default=1000, ge=0)
    source: Literal["links", "llms_txt", "sitemaps", "all"] = "links"
    formats: list[Literal["markdown", "html"]] = ["markdown"]
    render: bool = False
    goto_options: GotoOptions | None = None
    wait_for_selector: str | None = None
    reject_resource_types: list[str] | None = None
    options: CrawlOptions = Field(default_factory=CrawlOptions)


class SinglePageInput(BaseModel):
    """Shared input for /markdown and /content."""

    url: str | None = None
    html: str | None = None
    render: bool = False
    goto_options: GotoOptions | None = None
    wait_for_selector: str | None = None
    reject_resource_types: list[str] | None = None

    @model_validator(mode="after")
    def url_or_html_required(self) -> Self:
        if not self.url and not self.html:
            raise ValueError("Either 'url' or 'html' must be provided")
        if self.url and self.html:
            raise ValueError("Provide 'url' or 'html', not both")
        return self


class LinksInput(SinglePageInput):
    """Input for POST /links. Unlike SinglePageInput, url is required."""

    visible_links_only: bool = False
    exclude_external_links: bool = False

    @model_validator(mode="after")
    def url_required(self) -> Self:
        if not self.url:
            raise ValueError("'url' is required for /links")
        if self.html is not None:
            raise ValueError("Provide 'url' only for /links; raw 'html' is not supported")
        return self
