# ProContext Crawler: Technical Specification

> **Document**: 02-technical-spec.md
> **Status**: Draft v1
> **Last Updated**: 2026-04-15
> **Depends on**: 01-functional-spec.md

---

## Table of Contents

- [1. System Architecture](#1-system-architecture)
  - [1.1 Component Overview](#11-component-overview)
  - [1.2 Request Flow: Single-Page](#12-request-flow-single-page)
  - [1.3 Request Flow: Multi-Page Crawl](#13-request-flow-multi-page-crawl)
- [2. Technology Stack](#2-technology-stack)
- [3. Data Models](#3-data-models)
  - [3.1 Job Models](#31-job-models)
  - [3.2 URL Record Models](#32-url-record-models)
  - [3.3 API Input Models](#33-api-input-models)
  - [3.4 API Output Models](#34-api-output-models)
  - [3.5 Error Model](#35-error-model)
- [4. Crawl Engine](#4-crawl-engine)
  - [4.1 BFS Algorithm](#41-bfs-algorithm)
  - [4.2 URL Discovery Strategies](#42-url-discovery-strategies)
  - [4.3 URL Normalisation](#43-url-normalisation)
  - [4.4 Pattern Matching](#44-pattern-matching)
  - [4.5 Concurrency Model](#45-concurrency-model)
- [5. Fetcher](#5-fetcher)
  - [5.1 Static Fetcher (httpx)](#51-static-fetcher-httpx)
  - [5.2 Playwright Renderer](#52-playwright-renderer)
  - [5.3 Auto-Detect JS Rendering [v0.2]](#53-auto-detect-js-rendering-v02)
  - [5.4 Redirect Handling](#54-redirect-handling)
  - [5.5 Error Classification](#55-error-classification)
- [6. Content Extraction](#6-content-extraction)
  - [6.1 HTML-to-Markdown](#61-html-to-markdown)
  - [6.2 Link Extraction](#62-link-extraction)
  - [6.3 CSS Selector Extraction [v0.2]](#63-css-selector-extraction-v02)
  - [6.4 AI-Powered Extraction [v0.3]](#64-ai-powered-extraction-v03)
- [7. Repository Layer](#7-repository-layer)
  - [7.1 Protocol Definition](#71-protocol-definition)
  - [7.2 SQLite Implementation](#72-sqlite-implementation)
  - [7.3 Filesystem Storage](#73-filesystem-storage)
- [8. Job Scheduler](#8-job-scheduler)
  - [8.1 Job Creation](#81-job-creation)
  - [8.2 Polling and Cursor Pagination](#82-polling-and-cursor-pagination)
  - [8.3 Cancellation](#83-cancellation)
  - [8.4 Timeout and Cleanup](#84-timeout-and-cleanup)
- [9. Cache [v0.2]](#9-cache-v02)
  - [9.1 Page Cache](#91-page-cache)
  - [9.2 Deduplication](#92-deduplication)
  - [9.3 Incremental Crawling](#93-incremental-crawling)
- [10. API Layer](#10-api-layer)
  - [10.1 FastAPI Application](#101-fastapi-application)
  - [10.2 Routes](#102-routes)
  - [10.3 Middleware](#103-middleware)
- [11. Python API](#11-python-api)
  - [11.1 Crawler Class](#111-crawler-class)
  - [11.2 Async Context Manager](#112-async-context-manager)
  - [11.3 Single-Page Methods](#113-single-page-methods)
- [12. CLI](#12-cli)
  - [12.1 Command Structure](#121-command-structure)
  - [12.2 Output Formatting](#122-output-formatting)
- [13. Configuration](#13-configuration)
  - [13.1 Settings Schema](#131-settings-schema)
  - [13.2 Configuration Loading Order](#132-configuration-loading-order)
- [14. Logging](#14-logging)

---

## 1. System Architecture

### 1.1 Component Overview

```
┌────────────────────────────────────────────────────────────────┐
│                        Consumers                               │
│   Python script  │  HTTP client  │  CLI (proctx-crawler)       │
└───────┬──────────┴───────┬───────┴───────┬─────────────────────┘
        │ Python API       │ HTTP          │ Python API
        ▼                  ▼               ▼
┌────────────────────────────────────────────────────────────────┐
│                    ProContext Crawler                           │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Interface Layer                                         │  │
│  │  ┌────────────┐  ┌─────────────┐  ┌──────────────────┐  │  │
│  │  │ Crawler    │  │ FastAPI     │  │ CLI (argparse)   │  │  │
│  │  │ (Python)   │  │ (HTTP API)  │  │                  │  │  │
│  │  └─────┬──────┘  └──────┬──────┘  └────────┬─────────┘  │  │
│  └────────┼────────────────┼──────────────────┼─────────────┘  │
│           │                │                  │                 │
│  ┌────────▼────────────────▼──────────────────▼─────────────┐  │
│  │  Services Layer (shared domain orchestration)            │  │
│  │  ┌──────────────────────┐  ┌──────────────────────────┐  │  │
│  │  │ page_service         │  │ crawl_service            │  │  │
│  │  │ (fetch dispatch:     │  │ (job construction,       │  │  │
│  │  │  static vs render)   │  │  record materialisation, │  │  │
│  │  │                      │  │  result collection)      │  │  │
│  │  └──────────┬───────────┘  └────────────┬─────────────┘  │  │
│  └─────────────┼───────────────────────────┼────────────────┘  │
│                │                           │                    │
│  ┌─────────────▼───────────────────────────▼────────────────┐  │
│  │  Core Layer                                              │  │
│  │                                                          │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │  │
│  │  │ Crawl Engine │  │ Fetcher      │  │ Extractors    │  │  │
│  │  │ (BFS, queue, │  │ (httpx,      │  │ (markdown,    │  │  │
│  │  │  scheduling) │  │  Playwright) │  │  links, HTML) │  │  │
│  │  └──────┬───────┘  └──────────────┘  └───────────────┘  │  │
│  │         │                                                │  │
│  │  ┌──────▼────────────────────────────────────────────┐   │  │
│  │  │ Job Scheduler                                     │   │  │
│  │  │ (creation, polling, cancellation, timeout)        │   │  │
│  │  └──────┬────────────────────────────────────────────┘   │  │
│  └─────────┼────────────────────────────────────────────────┘  │
│            │                                                    │
│  ┌─────────▼────────────────────────────────────────────────┐  │
│  │  Infrastructure Layer                                     │  │
│  │  ┌─────────────┐  ┌──────────┐  ┌────────┐  ┌────────┐  │  │
│  │  │ Repository  │  │ Content  │  │ Config │  │ Logger │  │  │
│  │  │ (Protocol + │  │ Storage  │  │        │  │        │  │  │
│  │  │  SQLite)    │  │ (files)  │  │        │  │        │  │  │
│  │  └─────────────┘  └──────────┘  └────────┘  └────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

**Layer responsibilities**:

| Layer | Responsibility | Framework imports allowed |
|-------|---------------|--------------------------|
| Interface | Accept input, return output. Thin adapters — HTTP routes adapt request/response, `Crawler` adapts async-context lifecycle and Python kwargs. No domain logic. | FastAPI, argparse |
| Services | Shared domain orchestration called by both interface layers. Single-page fetch dispatch, job construction, record materialisation. | None |
| Core | Low-level primitives. BFS crawl loop, fetchers, extractors. | None (zero framework imports) |
| Infrastructure | Persistence, config, logging. | aiosqlite, pydantic-settings, structlog |

**Why a services layer?** The HTTP API and Python API are two different adapters over the same domain. Without a services layer, each one reimplements job construction, fetch dispatch, and record mapping. The services layer is the single owner of those flows so the adapters stay thin and no logic is duplicated.

### 1.2 Request Flow: Single-Page

```
POST /markdown {"url": "https://docs.pydantic.dev/concepts/models"}
  │
  ├─ Validate input (pydantic model)
  ├─ Fetch page:
  │    render=false → httpx GET (30s timeout)
  │    render=true  → Playwright navigate + wait + page.content()
  ├─ Extract: HTML → Markdown (markdownify + BeautifulSoup)
  └─ Return: {"success": true, "result": "# Models\n\n..."}
```

### 1.3 Request Flow: Multi-Page Crawl

```
POST /crawl {"url": "https://docs.pydantic.dev/llms.txt", "source": "llms_txt", "limit": 50}
  │
  ├─ Validate input
  ├─ Create job record (status: queued) in Repository
  ├─ Return job ID immediately: {"success": true, "result": "uuid"}
  │
  └─ Background task (async):
       │
       ├─ Set job status → running
       ├─ Enqueue starting URL
       │
       ├─ BFS loop:
       │    ├─ Dequeue next URL (FIFO)
       │    ├─ Check: visited? depth exceeded? pattern match?
       │    ├─ Set URL status → running
       │    ├─ Fetch page (static or Playwright)
       │    ├─ Extract content (Markdown, HTML as requested)
       │    ├─ Write content files to disk: <output_dir>/<job_id>/<url_hash>.md
       │    ├─ Set URL status → completed
       │    ├─ Discover new URLs (per source strategy)
       │    ├─ Filter + enqueue new URLs
       │    └─ Check: limit reached? queue empty? cancelled?
       │
       ├─ Write manifest.json
       └─ Set job status → completed
```

---

## 2. Technology Stack

| Component | Choice | Version | Rationale |
|-----------|--------|---------|-----------|
| Language | Python | 3.12+ | Modern asyncio, `from __future__ import annotations`, type union syntax |
| Package manager | uv | latest | Fast installs, lock files, `uv run` for development |
| HTTP client | httpx | ≥0.28 | Async-native, connection pooling, manual redirect control |
| Browser engine | Playwright | ≥1.40 | Multi-browser (Chromium default), async API, resource blocking |
| Web framework | FastAPI | ≥0.115 | Async routes, pydantic integration, OpenAPI docs |
| ASGI server | uvicorn | ≥0.34 | HTTP transport, lifespan support |
| Data validation | pydantic v2 | ≥2.5 | Input validation, model serialisation, settings |
| Config | pydantic-settings | ≥2.2 | YAML config with env var overrides |
| Config parsing | pyyaml | ≥6.0 | YAML parser for pydantic-settings |
| SQLite driver | aiosqlite | ≥0.19 | Async wrapper; WAL mode for concurrent reads |
| HTML parsing | BeautifulSoup4 | ≥4.12 | Robust HTML parser for link/content extraction |
| Markdown conversion | markdownify | ≥0.14 | HTML-to-Markdown with configurable options |
| Logging | structlog | ≥24.1 | Structured JSON logs, context binding |
| Platform paths | platformdirs | ≥4.0 | OS-native data/config directories |
| Async runtime | anyio | ≥4.0 | Backend-agnostic async (used for testing, task groups) |
| Linting/formatting | ruff | ≥0.11 | Single tool for lint + format |
| Type checking | pyright | ≥1.1.400 | Standard mode enforced |

---

## 3. Data Models

All models use pydantic v2. Models are defined in `src/proctx_crawler/models/`, split by domain. All modules use `from __future__ import annotations`.

### 3.1 Job Models

```python
# models/job.py

from pydantic import BaseModel, Field
from enum import StrEnum
from datetime import datetime

class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERRORED = "errored"

class Job(BaseModel):
    id: str                                   # UUID
    status: JobStatus = JobStatus.QUEUED
    url: str                                  # Starting URL
    config: CrawlConfig                       # Full crawl configuration (see 3.3)
    total: int = 0                            # Total URLs discovered
    finished: int = 0                         # URLs in terminal state
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
```

### 3.2 URL Record Models

```python
# models/url_record.py

class UrlStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    ERRORED = "errored"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    DISALLOWED = "disallowed"                 # v0.2 — robots.txt

class UrlRecord(BaseModel):
    id: str                                   # UUID
    job_id: str                               # FK to Job
    url: str                                  # Absolute URL
    url_hash: str                             # Truncated SHA-256 (16 hex chars)
    depth: int                                # Hops from starting URL
    status: UrlStatus = UrlStatus.QUEUED
    http_status: int | None = None            # HTTP response code
    error_message: str | None = None          # Error detail if status=errored
    content_hash: str | None = None           # SHA-256 of extracted content
    title: str | None = None                  # Page title from <title> or <h1>
    created_at: datetime
    completed_at: datetime | None = None
```

### 3.3 API Input Models

```python
# models/input.py

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
    options: CrawlOptions = CrawlOptions()

class CrawlOptions(BaseModel):
    include_patterns: list[str] | None = None
    exclude_patterns: list[str] | None = None
    include_subdomains: bool = False
    include_external_links: bool = False

class GotoOptions(BaseModel):
    wait_until: Literal["load", "domcontentloaded", "networkidle0", "networkidle2"] = "load"
    timeout: int = Field(default=30000, ge=1000, le=120000)

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
    visible_links_only: bool = False
    exclude_external_links: bool = False

    @model_validator(mode="after")
    def url_required(self) -> Self:
        if not self.url:
            raise ValueError("'url' is required for /links")
        if self.html is not None:
            raise ValueError("Provide 'url' only for /links; raw 'html' is not supported")
        return self
```

### 3.4 API Output Models

```python
# models/output.py

class SuccessResponse[T](BaseModel):
    success: Literal[True] = True
    result: T

class CrawlResult(BaseModel):
    id: str
    status: JobStatus
    total: int
    finished: int
    records: list[CrawlRecord]
    cursor: str | None = None

class CrawlRecord(BaseModel):
    url: str
    status: UrlStatus
    markdown: str | None = None
    html: str | None = None
    metadata: RecordMetadata | None = None

class RecordMetadata(BaseModel):
    http_status: int
    title: str | None = None
    content_hash: str | None = None
```

### 3.5 Error Model

```python
# models/errors.py

class ErrorCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    FETCH_FAILED = "FETCH_FAILED"
    NOT_FOUND = "NOT_FOUND"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    RENDER_FAILED = "RENDER_FAILED"
    INVALID_SELECTOR = "INVALID_SELECTOR"
    DISALLOWED = "DISALLOWED"                 # v0.2
    EXTRACTION_FAILED = "EXTRACTION_FAILED"   # v0.3

class ErrorDetail(BaseModel):
    code: ErrorCode
    message: str
    recoverable: bool

class ErrorResponse(BaseModel):
    success: Literal[False] = False
    error: ErrorDetail

class CrawlerError(Exception):
    """Base exception for all crawler errors."""
    def __init__(self, code: ErrorCode, message: str, recoverable: bool = False):
        self.code = code
        self.message = message
        self.recoverable = recoverable
        super().__init__(message)

class FetchError(CrawlerError): ...
class RenderError(CrawlerError): ...
class JobNotFoundError(CrawlerError): ...
```

---

## 4. Crawl Engine

### 4.1 BFS Algorithm

The crawl engine uses a breadth-first search with an explicit FIFO queue.

```python
# Pseudocode — actual implementation in core/engine.py

async def run_crawl(job: Job, repo: Repository, storage: ContentStorage):
    queue: deque[QueueEntry] = deque()
    visited: set[str] = set()

    # Seed the queue
    seed_urls = await discover_seed_urls(job.config)
    for url in seed_urls:
        if should_crawl(url, job.config, visited, depth=0):
            queue.append(QueueEntry(url=url, depth=0))
            visited.add(normalise_url(url))
            await repo.enqueue_url(job.id, url, depth=0)

    await repo.update_job_status(job.id, JobStatus.RUNNING)

    completed_count = 0
    while queue and completed_count < job.config.limit:
        if await repo.is_job_cancelled(job.id):
            break

        entry = queue.popleft()
        await repo.update_url_status(job.id, entry.url, UrlStatus.RUNNING)

        try:
            page = await fetch_page(entry.url, job.config)
            content = await extract_content(page, job.config.formats)
            await storage.write(job.id, entry.url, content)
            await repo.mark_url_completed(job.id, entry.url, page.metadata)
            completed_count += 1

            # Discover and enqueue new URLs
            if job.config.source != "llms_txt":  # llms_txt only uses seed URLs
                new_urls = await discover_urls(page, job.config.source)
                for new_url in new_urls:
                    normalised = normalise_url(new_url)
                    new_depth = entry.depth + 1
                    if should_crawl(new_url, job.config, visited, new_depth):
                        queue.append(QueueEntry(url=new_url, depth=new_depth))
                        visited.add(normalised)
                        await repo.enqueue_url(job.id, new_url, depth=new_depth)

        except CrawlerError as e:
            await repo.mark_url_errored(job.id, entry.url, str(e))

    # Finalise
    status = JobStatus.CANCELLED if await repo.is_job_cancelled(job.id) else JobStatus.COMPLETED
    await storage.write_manifest(job.id)
    await repo.update_job_status(job.id, status)
```

**Key properties**:

- **FIFO order**: Pages closer to the starting URL are processed first.
- **Visited set**: Normalised URLs are tracked in-memory to prevent re-crawling. The set uses normalised URLs (see Section 4.3) for deduplication.
- **Early termination**: The loop exits when the `limit` is reached, the queue is empty, or the job is cancelled.
- **Error isolation**: A failed fetch does not stop the crawl. The URL is marked as `errored` and the loop continues.

### 4.2 URL Discovery Strategies

| Source | Seed URLs | Per-Page Discovery |
|--------|-----------|--------------------|
| `"links"` | Starting URL only | Parse `<a href>` from each crawled page |
| `"llms_txt"` | Parse starting URL as llms.txt, extract all links | None — only seed URLs are crawled |
| `"sitemaps"` [v0.2] | Parse `sitemap.xml` from starting URL's domain | None — only sitemap URLs are crawled |
| `"all"` [v0.2] | Sitemap URLs + starting URL | Parse `<a href>` from each crawled page (for pages not found via sitemap) |

**llms.txt parsing**: The starting URL is fetched and parsed as a plain text file. The parser extracts all HTTP(S) URLs found in the file using two strategies:

1. **Markdown links**: `[text](url)` or `- [text](url)` — extract the URL from the parentheses
2. **Bare URLs**: Lines containing `https://...` or `http://...` — extract the URL (terminated by whitespace, `>`, `)`, or end-of-line)

The parser is intentionally lenient — real-world llms.txt files vary in structure. Section headers and descriptive text are ignored; only URLs are extracted. All extracted URLs become seed entries in the queue at depth 0. Duplicate URLs are deduplicated before enqueuing.

**Link discovery from HTML**: After fetching a page, all `<a href="...">` elements are extracted. Relative URLs are resolved to absolute using the page's base URL. Fragment-only links (`#section`) are discarded. Each discovered URL goes through the pattern matching and domain filtering pipeline before being enqueued.

### 4.3 URL Normalisation

Before checking the visited set or comparing URLs, all URLs are normalised:

1. Parse with `urllib.parse.urlparse`
2. Lowercase the scheme and hostname
3. Remove default ports (`:80` for HTTP, `:443` for HTTPS)
4. Remove trailing slash (except for root `/`)
5. Remove fragment (`#section`)
6. Sort query parameters alphabetically
7. Remove empty query string (`?` with no params)
8. Percent-decode unreserved characters, re-encode with uppercase hex

```python
normalise_url("HTTPS://Docs.Example.Com:443/api/../guide/?b=2&a=1#section")
# → "https://docs.example.com/guide/?a=1&b=2"
```

### 4.4 Pattern Matching

URL include/exclude patterns use wildcard syntax (from the functional spec):

- `*` — matches any character except `/`
- `**` — matches any character including `/`

**Implementation**: Convert wildcard patterns to regex at job creation time.

```python
def compile_pattern(pattern: str) -> re.Pattern[str]:
    """Convert wildcard pattern to compiled regex."""
    parts = pattern.split("**")
    regex_parts = []
    for i, part in enumerate(parts):
        # Escape everything except *, then replace * with [^/]*
        escaped = re.escape(part).replace(r"\*", "[^/]*")
        regex_parts.append(escaped)
    return re.compile(".*".join(regex_parts) + "$")
```

**Evaluation order** (per functional spec D6):

1. If the URL matches any exclude pattern → **skip** (exclude always wins)
2. If include patterns exist and the URL matches none → **skip**
3. Otherwise → **crawl**

**Domain filtering** (evaluated before pattern matching):

1. Extract the domain from the starting URL
2. If `include_subdomains` is false: only URLs with the exact same domain pass
3. If `include_subdomains` is true: URLs with the same domain or any subdomain pass
4. If `include_external_links` is false: cross-domain URLs are filtered out
5. If `include_external_links` is true: all domains pass

### 4.5 Concurrency Model

v0.1 uses a **single-worker sequential** model — one URL is fetched at a time within a crawl job. This is simple and avoids overwhelming target sites.

**Future (v0.2+)**: Configurable concurrency with `anyio.create_task_group()` and a semaphore.

```python
# v0.2 concurrency sketch
async def run_crawl_concurrent(job, repo, storage, max_workers: int = 5):
    semaphore = anyio.Semaphore(max_workers)

    async with anyio.create_task_group() as tg:
        while queue and completed_count < limit:
            entry = queue.popleft()
            await semaphore.acquire()
            tg.start_soon(process_url, entry, semaphore)
```

**Rate limiting** (v0.2): Per-domain delay enforced by tracking the last request time per domain and sleeping if needed before the next request to the same domain.

---

## 5. Fetcher

The fetcher is responsible for downloading page content. It has two implementations behind a common interface.

### 5.1 Static Fetcher (httpx)

The default fetch path. Fast, no browser, no JavaScript execution.

```python
# core/fetcher.py

class FetchResult(BaseModel):
    url: str                          # Final URL after redirects
    status_code: int
    html: str                         # Raw HTML body
    headers: dict[str, str]

async def fetch_static(
    url: str,
    *,
    timeout: float = 30.0,
    max_response_size: int = 10_485_760,
) -> FetchResult:
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()

            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > max_response_size:
                    raise FetchError(
                        ErrorCode.FETCH_FAILED,
                        f"Response size exceeds {max_response_size} bytes",
                    )

            return FetchResult(
                url=str(response.url),
                status_code=response.status_code,
                html=body.decode(response.encoding or "utf-8", errors="replace"),
                headers=dict(response.headers),
            )
```

**Configuration**:

| Setting | Default | Description |
|---------|---------|-------------|
| Timeout | 30s | Per-request timeout |
| Max redirects | 10 | Redirect chain limit (handled manually so each hop can be re-validated) |
| Max response size | 10 MB | Static responses are streamed and rejected once the byte limit is exceeded |
| User-Agent | `proctx-crawler/<version>` | Customisable in v0.2 |

### 5.2 Playwright Renderer

Used when `render: true`. Uses a shared browser pool to avoid launching Chromium on every fetch. Each fetch gets a fresh `BrowserContext` for isolation.

#### 5.2.1 Browser Pool

The `BrowserPool` manages a single long-lived Chromium instance shared across all crawl jobs and single-page requests. Each fetch acquires a `BrowserContext` (cheap — ~10ms), uses it, and closes it. The browser is launched lazily on first use.

```python
# core/browser_pool.py

class BrowserPool:
    def __init__(self, *, headless: bool = True):
        self._headless = headless
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._lock = anyio.Lock()

    async def start(self) -> None:
        """Launch the browser. Called once during application startup."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)

    async def stop(self) -> None:
        """Close the browser and Playwright. Called during shutdown."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._browser = None
        self._playwright = None

    async def _ensure_browser(self) -> Browser:
        """Relaunch the browser if it crashed."""
        async with self._lock:
            if self._browser is None or not self._browser.is_connected():
                if self._playwright is None:
                    self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(headless=self._headless)
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
```

**Key properties**:

- **Lazy start**: The browser is launched on `start()` or on first use via `_ensure_browser()`.
- **Crash recovery**: If the browser process dies (detected via `is_connected()`), `_ensure_browser()` relaunches it transparently. A lock prevents multiple concurrent relaunches.
- **Context isolation**: Each fetch gets a new `BrowserContext` — separate cookies, localStorage, cache. No state leaks between fetches.
- **Lifecycle**: Created once during application startup (in the FastAPI lifespan or `Crawler.__aenter__`). Closed during shutdown.

#### 5.2.2 Rendered Fetch

```python
# core/renderer.py

async def fetch_rendered(
    url: str,
    pool: BrowserPool,
    *,
    goto_options: GotoOptions | None = None,
    wait_for_selector: str | None = None,
    reject_resource_types: list[str] | None = None,
) -> FetchResult:
    async with pool.acquire_context() as context:
        page = await context.new_page()

        # Block unwanted resource types (images, fonts, etc.)
        if reject_resource_types:
            await page.route("**/*", make_resource_blocker(reject_resource_types))

        wait_until = (goto_options.wait_until if goto_options else "load")
        timeout = (goto_options.timeout if goto_options else 30000)

        response = await page.goto(url, wait_until=wait_until, timeout=timeout)

        if wait_for_selector:
            await page.wait_for_selector(wait_for_selector, timeout=timeout)

        html = await page.content()

        return FetchResult(
            url=page.url,
            status_code=response.status if response else 0,
            html=html,
            headers={},
        )
```

**Resource blocking**: The `reject_resource_types` parameter maps to Playwright's route interception. Blocking images, fonts, and stylesheets dramatically speeds up rendering when only text content is needed.

### 5.3 Auto-Detect JS Rendering [v0.2]

When `render` is not explicitly set and auto-detect is enabled:

1. Fetch the page via httpx (static)
2. Inspect the response body for JS-shell indicators:
   - Body length < 2 KB
   - Contains `<div id="root"></div>` or `<div id="app"></div>` with no other content
   - Contains `__NEXT_DATA__` script tag with no visible text nodes
   - Contains `<noscript>` tags suggesting JS-required content
3. If indicators are detected, re-fetch with Playwright

This keeps the fast path for static pages while catching SPAs automatically.

### 5.4 Redirect Handling

- **Static**: httpx follows redirects automatically (up to 10 hops). The final URL is recorded.
- **Playwright**: The browser handles redirects natively. `page.url` returns the final URL.
- **Cross-domain redirects**: If a redirect crosses domain boundaries, the final URL is checked against domain filters. A redirect to an excluded domain causes the URL to be skipped (not errored).

### 5.5 Error Classification

| HTTP Status | Classification | URL Status | Recoverable |
|-------------|---------------|------------|-------------|
| 200-299 | Success | `completed` | — |
| 301, 302, 307, 308 | Redirect | Handled transparently | — |
| 403 | Forbidden | `errored` | `false` |
| 404 | Not Found | `errored` | `false` |
| 429 | Rate Limited | `errored` | `true` |
| 500-599 | Server Error | `errored` | `true` |
| Connection error | Network failure | `errored` | `true` |
| Timeout | Timeout | `errored` | `true` |
| Playwright crash | Browser error | `errored` | `true` |

---

## 6. Content Extraction

### 6.1 HTML-to-Markdown

Uses `markdownify` with BeautifulSoup for HTML parsing.

```python
# extractors/markdown.py

from markdownify import markdownify as md
from bs4 import BeautifulSoup

def html_to_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    # Remove non-content elements
    for tag in soup.find_all(["nav", "header", "footer", "aside", "script", "style", "noscript"]):
        tag.decompose()

    # Prefer <main> or <article> if present, otherwise use <body>
    main = soup.find("main") or soup.find("article") or soup.find("body") or soup
    return md(str(main), heading_style="ATX", strip=["img"])
```

**Content selection heuristic**: If the page contains a `<main>` or `<article>` element, only that element is converted. This strips navigation, sidebars, and footers, producing cleaner Markdown for documentation pages. Falls back to `<body>` or full HTML.

### 6.2 Link Extraction

```python
# extractors/links.py

from urllib.parse import urljoin, urlparse

def extract_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]

        # Skip fragment-only and non-HTTP links
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("javascript:"):
            continue

        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)

        # Only HTTP(S) links
        if parsed.scheme not in ("http", "https"):
            continue

        # Remove fragment for deduplication
        clean = parsed._replace(fragment="").geturl()
        if clean not in seen:
            seen.add(clean)
            links.append(clean)

    return links
```

### 6.3 CSS Selector Extraction [v0.2]

For the `/scrape` endpoint. Requires Playwright for dimension/position data.

```python
# extractors/scrape.py (v0.2)

async def extract_elements(page: Page, selectors: list[dict]) -> list[ScrapeResult]:
    results = []
    for selector_spec in selectors:
        selector = selector_spec["selector"]
        elements = await page.query_selector_all(selector)
        matches = []
        for el in elements:
            box = await el.bounding_box()
            matches.append(ScrapeMatch(
                text=await el.inner_text(),
                html=await el.inner_html(),
                attributes=await el.evaluate("el => [...el.attributes].map(a => ({name: a.name, value: a.value}))"),
                width=box["width"] if box else None,
                height=box["height"] if box else None,
                top=box["y"] if box else None,
                left=box["x"] if box else None,
            ))
        results.append(ScrapeResult(selector=selector, results=matches))
    return results
```

### 6.4 AI-Powered Extraction [v0.3]

For the `/json` endpoint. The crawler sends the page content to an external AI model and returns structured data.

**Design**:

- No AI model is bundled — the model configuration is provided per-request (`provider`, `model`, `api_key`)
- The page's Markdown content is sent as context along with the user's `prompt` or `response_format`
- Response validation against the `response_format` schema is performed before returning

---

## 7. Repository Layer

### 7.1 Protocol Definition

The Repository protocol defines the contract between business logic and persistence. Business logic imports only this protocol — never the concrete implementation.

```python
# core/repository.py

from typing import Protocol, runtime_checkable

@runtime_checkable
class Repository(Protocol):
    # Job operations
    async def create_job(self, job: Job) -> None: ...
    async def get_job(self, job_id: str) -> Job | None: ...
    async def update_job_status(self, job_id: str, status: JobStatus) -> None: ...
    async def update_job_counts(self, job_id: str, total: int, finished: int) -> None: ...
    async def is_job_cancelled(self, job_id: str) -> bool: ...
    async def list_jobs(self, *, limit: int = 100, offset: int = 0) -> list[Job]: ...

    # URL record operations
    async def enqueue_url(self, job_id: str, url: str, depth: int) -> None: ...
    async def get_url_records(
        self, job_id: str, *, limit: int = 100, cursor: str | None = None,
        status: UrlStatus | None = None,
    ) -> tuple[list[UrlRecord], str | None]: ...
    async def update_url_status(self, job_id: str, url: str, status: UrlStatus) -> None: ...
    async def mark_url_completed(
        self, job_id: str, url: str, metadata: RecordMetadata,
    ) -> None: ...
    async def mark_url_errored(self, job_id: str, url: str, error: str) -> None: ...
    async def cancel_queued_urls(self, job_id: str) -> int: ...

    # Lifecycle
    async def initialise(self) -> None: ...
    async def close(self) -> None: ...
```

### 7.2 SQLite Implementation

```python
# infrastructure/sqlite_repository.py

class SQLiteRepository:
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialise(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._create_tables()

    async def _create_tables(self) -> None:
        await self._db.executescript(SCHEMA_DDL)
```

**Schema DDL**:

```sql
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    status      TEXT NOT NULL DEFAULT 'queued',
    url         TEXT NOT NULL,
    config      TEXT NOT NULL,              -- JSON-serialised CrawlConfig
    total       INTEGER NOT NULL DEFAULT 0,
    finished    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,              -- ISO 8601
    updated_at  TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS url_records (
    id            TEXT PRIMARY KEY,
    job_id        TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    url           TEXT NOT NULL,
    url_hash      TEXT NOT NULL,            -- Truncated SHA-256 (16 hex chars)
    depth         INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'queued',
    http_status   INTEGER,
    error_message TEXT,
    content_hash  TEXT,
    title         TEXT,
    created_at    TEXT NOT NULL,
    completed_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_url_records_job_id ON url_records(job_id);
CREATE INDEX IF NOT EXISTS idx_url_records_job_status ON url_records(job_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_url_records_job_url ON url_records(job_id, url);
```

**WAL mode**: Enables concurrent reads while a write is in progress. Essential when the crawl engine is writing URL records while the API layer is reading job status.

**Cursor pagination**: The cursor is an opaque token representing the last returned insertion-order position. The next query resumes from that stable position using SQLite row insertion order, which avoids skipping newly inserted records during a live crawl.

### 7.3 Filesystem Storage

Content files are managed by a separate `ContentStorage` class — not the Repository.

```python
# infrastructure/content_storage.py

class ContentStorage:
    def __init__(self, output_dir: Path):
        self._output_dir = output_dir

    def job_dir(self, job_id: str) -> Path:
        return self._output_dir / job_id

    def url_hash(self, url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    async def write(self, job_id: str, url: str, content: ExtractedContent) -> None:
        job_path = self.job_dir(job_id)
        job_path.mkdir(parents=True, exist_ok=True)
        h = self.url_hash(url)

        if content.markdown is not None:
            (job_path / f"{h}.md").write_text(content.markdown, encoding="utf-8")
        if content.html is not None:
            (job_path / f"{h}.html").write_text(content.html, encoding="utf-8")

    async def read(self, job_id: str, url: str, format: str) -> str | None:
        h = self.url_hash(url)
        ext = ".md" if format == "markdown" else ".html"
        path = self.job_dir(job_id) / f"{h}{ext}"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    async def write_manifest(self, job_id: str, job: Job, records: list[UrlRecord]) -> None:
        """Write manifest.json mapping url_hash → original URL + metadata."""
        manifest = {
            "job_id": job.id,
            "status": job.status,
            "url": job.url,
            "created_at": job.created_at.isoformat(),
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            "config": job.config.model_dump(),
            "total": job.total,
            "finished": job.finished,
            "pages": {
                self.url_hash(r.url): {
                    "url": r.url,
                    "status": r.status,
                    "http_status": r.http_status,
                    "title": r.title,
                    "content_hash": r.content_hash,
                    "files": {
                        "markdown": f"{self.url_hash(r.url)}.md",
                        "html": f"{self.url_hash(r.url)}.html",
                    },
                }
                for r in records
                if r.status == UrlStatus.COMPLETED
            },
        }
        path = self.job_dir(job_id) / "manifest.json"
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
```

**manifest.json schema**:

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "url": "https://docs.pydantic.dev/llms.txt",
  "created_at": "2026-03-16T10:00:00+00:00",
  "finished_at": "2026-03-16T10:05:32+00:00",
  "config": { "limit": 50, "depth": 1000, "source": "llms_txt", "..." : "..." },
  "total": 50,
  "finished": 50,
  "pages": {
    "a1b2c3d4e5f67890": {
      "url": "https://docs.pydantic.dev/concepts/models",
      "status": "completed",
      "http_status": 200,
      "title": "Models - Pydantic",
      "content_hash": "sha256:abcdef1234567890...",
      "files": {
        "markdown": "a1b2c3d4e5f67890.md",
        "html": "a1b2c3d4e5f67890.html"
      }
    }
  }
}
```

**File layout** (from functional spec Section 9.1):

```
<output_dir>/
  <job_id>/
    manifest.json
    <url_hash>.md
    <url_hash>.html
    ...
```

---

## 8. Job Scheduler

The job scheduler orchestrates the lifecycle of crawl jobs.

### 8.1 Job Creation

```python
async def create_crawl_job(config: CrawlConfig, repo: Repository) -> str:
    job_id = str(uuid.uuid4())
    job = Job(
        id=job_id,
        url=config.url,
        config=config,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await repo.create_job(job)
    return job_id
```

After returning the job ID, the crawl is started as a background async task:

```python
# In the API layer or Crawler class
task_group.start_soon(run_crawl, job, repo, storage)
```

### 8.2 Polling and Cursor Pagination

When `GET /crawl?id=<job_id>` is called:

1. Load job metadata from the Repository
2. If `limit=0`, return only job-level status (no records)
3. Load URL records with cursor-based pagination
4. For each completed record, read content from ContentStorage
5. Return the assembled `CrawlResult`

**Cursor encoding**:

```python
import base64, json

def encode_cursor(last_rowid: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"rowid": last_rowid}).encode()).decode()

def decode_cursor(cursor: str) -> int:
    data = json.loads(base64.urlsafe_b64decode(cursor))
    return int(data["rowid"])
```

The cursor is opaque to the client. It encodes a stable position in insertion order so pagination remains complete even while new URL records are being appended.

### 8.3 Cancellation

When `DELETE /crawl?id=<job_id>` is called:

1. Call `repo.cancel_queued_urls(job_id)` — bulk-update all `queued` URLs to `cancelled`
2. Set a cancellation flag in the Repository (or update job status)
3. The crawl engine checks `repo.is_job_cancelled(job_id)` at the top of each loop iteration
4. In-flight fetches are allowed to complete (no mid-fetch abort)
5. Once the crawl loop exits, the job status is set to `cancelled`

### 8.4 Timeout and Cleanup

**Job timeout**: A configurable maximum runtime per job (default: 1 hour). This setting exists in `Settings` but is not yet enforced in the v0.1 runtime.

**Metadata cleanup**: The retention setting also exists in `Settings` but is not yet enforced in the v0.1 runtime. Content files on disk are never auto-deleted by the current implementation.

---

## 9. Cache [v0.2]

Caching is a v0.2 feature. This section defines the design for forward compatibility.

### 9.1 Page Cache

Pages fetched by the crawler can be cached to avoid re-fetching within a TTL.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_age` | 86400 (24h) | Cache TTL in seconds |

**Cache key**: SHA-256 of the normalised URL.

**Storage**: A `page_cache` table in SQLite:

```sql
CREATE TABLE IF NOT EXISTS page_cache (
    url_hash    TEXT PRIMARY KEY,
    url         TEXT NOT NULL,
    html        TEXT NOT NULL,
    http_status INTEGER NOT NULL,
    fetched_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);
```

**Lookup**: Before fetching, check the cache. If a non-expired entry exists, use the cached HTML. If expired, re-fetch and update the cache.

### 9.2 Deduplication

Within a single crawl job, content deduplication is handled by the visited set (Section 4.1). Across jobs, the page cache serves as a deduplication mechanism — if the same URL was recently crawled by another job, the cached HTML is reused.

### 9.3 Incremental Crawling

The `modified_since` parameter (v0.2) allows skipping pages that haven't changed since a given timestamp. Implementation:

1. Before fetching, check the cache for a prior fetch of this URL
2. If the cached `fetched_at` is after `modified_since`, use the cached version
3. Optionally, send `If-Modified-Since` headers to the target server

---

## 10. API Layer

### 10.1 FastAPI Application

```python
# api/app.py

from fastapi import FastAPI
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    settings = load_settings()
    repo = SQLiteRepository(settings.db_path)
    await repo.initialise()
    storage = ContentStorage(settings.output_dir)
    browser_pool = BrowserPool(headless=settings.playwright_headless)

    app.state.repo = repo
    app.state.storage = storage
    app.state.browser_pool = browser_pool
    app.state.settings = settings
    app.state.task_group = anyio.create_task_group()

    async with app.state.task_group:
        yield

    # Shutdown
    await browser_pool.stop()
    await repo.close()

app = FastAPI(title="ProContext Crawler", lifespan=lifespan)
```

**State injection**: `Repository`, `ContentStorage`, `BrowserPool`, and `Settings` are created in the lifespan and stored on `app.state`. Route handlers access them via `request.app.state`. No global singletons.

**Lazy browser startup**: The HTTP app now constructs the `BrowserPool` during lifespan startup but does not launch Chromium immediately. The pool starts itself on the first render request, so static-only deployments can serve requests without Playwright boot cost or a browser install at process start.

### 10.2 Routes

Routes are thin HTTP adapters. They validate input with pydantic, pull shared resources off `app.state`, delegate to the services layer, and map results back to the response envelope. All job construction, fetch dispatch, and record materialisation lives in `core/crawl_service.py` and `core/page_service.py` — not in route bodies.

```python
# api/routes.py

from proctx_crawler.core.crawl_service import (
    build_and_persist_job,
    url_record_to_crawl_record,
)
from proctx_crawler.core.page_service import fetch_page_html

@router.post("/crawl")
async def start_crawl(config: CrawlConfig, request: Request) -> SuccessResponse[str]:
    repo = request.app.state.repo
    storage = request.app.state.storage
    pool = request.app.state.browser_pool if config.render else None
    job = await build_and_persist_job(config.url, config, repo)
    # Scheduling model differs from the Python API: HTTP returns immediately,
    # crawl runs in the lifespan-scoped task group.
    request.app.state.task_group.start_soon(run_crawl, job, repo, storage, pool)
    return SuccessResponse(result=job.id)

@router.get("/crawl")
async def poll_crawl(
    request: Request,
    id: str,
    limit: int = 100,
    cursor: str | None = None,
    status: UrlStatus | None = None,
) -> SuccessResponse[CrawlResult]:
    # Route owns pagination params; mapping each UrlRecord -> CrawlRecord
    # uses the shared service function so HTTP and Python agree on shape.
    ...

@router.delete("/crawl")
async def cancel_crawl(id: str, request: Request) -> SuccessResponse[str]:
    ...

@router.post("/markdown")
async def extract_markdown(body: SinglePageInput, request: Request) -> SuccessResponse[str]:
    # HTML-only shortcut stays in the route: it's a pure extractor call at
    # the HTTP boundary, no domain logic worth sharing.
    if body.html is not None:
        return SuccessResponse(result=html_to_markdown(body.html))
    result = await _fetch_single_page_html(body, request)
    return SuccessResponse(result=html_to_markdown(result.html))

@router.post("/content")
async def extract_content(body: SinglePageInput, request: Request) -> SuccessResponse[str]:
    ...

@router.post("/links")
async def extract_links(body: LinksInput, request: Request) -> SuccessResponse[list[str]]:
    ...


async def _fetch_single_page_html(body: SinglePageInput, request: Request) -> FetchResult:
    """Adapt the HTTP request shape to the page_service call."""
    pool = request.app.state.browser_pool if body.render else None
    return await fetch_page_html(
        body.url,
        render=body.render,
        browser_pool=pool,
        goto_options=body.goto_options,
        wait_for_selector=body.wait_for_selector,
        reject_resource_types=body.reject_resource_types,
    )
```

**Error handling**: A global exception handler catches `CrawlerError` subclasses and returns the `ErrorResponse` envelope.

```python
@app.exception_handler(CrawlerError)
async def crawler_error_handler(request: Request, exc: CrawlerError) -> JSONResponse:
    status_map = {
        ErrorCode.INVALID_INPUT: 400,
        ErrorCode.NOT_FOUND: 404,
        ErrorCode.JOB_NOT_FOUND: 404,
        ErrorCode.FETCH_FAILED: 502,
        ErrorCode.RENDER_FAILED: 502,
        ErrorCode.INVALID_SELECTOR: 400,
    }
    return JSONResponse(
        status_code=status_map.get(exc.code, 500),
        content=ErrorResponse(
            error=ErrorDetail(code=exc.code, message=exc.message, recoverable=exc.recoverable)
        ).model_dump(),
    )
```

### 10.3 Middleware

**Optional API key authentication**: When `PROCTX_CRAWLER__AUTH_API_KEY` is set, all requests must include `Authorization: Bearer <key>`. Implemented as ASGI middleware (not `BaseHTTPMiddleware`, to preserve SSE streaming for v0.3+). Token comparison uses `secrets.compare_digest`.

**CORS**: Disabled by default. Configurable via settings for browser-based consumers.

---

## 11. Python API

### 11.1 Crawler Class

The primary Python-facing interface. Usable without the HTTP server.

The class is a **thin adapter**: it owns the lifecycle of per-instance resources (repo, storage, lazily-initialised browser pool), applies the Settings-merge contract to constructor kwargs, and delegates all domain work to `core/page_service.py` and `core/crawl_service.py`. It does not reimplement job construction, fetch dispatch, or record materialisation — those live in the services layer so the HTTP API and Python API share a single source of truth.

```python
# crawler.py

class Crawler:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        output_dir: Path | None = None,
        db_path: Path | None = None,
    ):
        # Priority: explicit kwargs > injected Settings > load_settings()
        self._settings = settings or load_settings()
        self._output_dir = output_dir or self._settings.output_dir
        self._db_path = db_path or self._settings.db_path
        self._repo: Repository | None = None
        self._storage: ContentStorage | None = None
        self._browser_pool: BrowserPool | None = None

    async def __aenter__(self) -> Crawler:
        self._repo = SQLiteRepository(self._db_path)
        await self._repo.initialise()
        self._storage = ContentStorage(self._output_dir)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._browser_pool:
            await self._browser_pool.stop()
        if self._repo:
            await self._repo.close()

    async def _ensure_browser_pool(self) -> BrowserPool:
        """Lazily start Chromium the first time render=True is requested."""
        if self._browser_pool is None:
            self._browser_pool = BrowserPool(headless=self._settings.playwright_headless)
            await self._browser_pool.start()
        return self._browser_pool
```

### 11.2 Async Context Manager

The `Crawler` class is an async context manager that manages database connections and cleanup:

```python
async with Crawler() as crawler:
    job = await crawler.crawl("https://docs.pydantic.dev/llms.txt", depth=2)
    for record in job.records:
        print(record.url, record.markdown[:100])
```

### 11.3 Single-Page Methods

Each public method is ~5 lines of delegation to the services layer.

```python
from proctx_crawler.core.crawl_service import build_and_persist_job, collect_crawl_result
from proctx_crawler.core.page_service import fetch_page_html

class Crawler:
    ...

    async def crawl(
        self,
        url: str,
        *,
        limit: int = 10,
        depth: int = 1000,
        source: str = "links",
        formats: list[str] | None = None,
        render: bool = False,
        **kwargs: Any,
    ) -> CrawlResult:
        """Start a crawl and wait for completion. Returns the full result."""
        resolved_formats = formats or ["markdown"]
        config = CrawlConfig(url=url, limit=limit, depth=depth, source=source,
                             formats=resolved_formats, render=render, **kwargs)
        job = await build_and_persist_job(url, config, self._repo)
        pool = await self._ensure_browser_pool() if render else None
        await run_crawl(job, self._repo, self._storage, pool)
        return await collect_crawl_result(job.id, self._repo, self._storage, resolved_formats)

    async def markdown(self, url: str, *, render: bool = False, **kwargs: Any) -> str:
        """Fetch a single page and return Markdown."""
        page = await self._fetch_page(url, render=render, **kwargs)
        return html_to_markdown(page.html)

    async def content(self, url: str, *, render: bool = False, **kwargs: Any) -> str:
        """Fetch a single page and return rendered HTML."""
        page = await self._fetch_page(url, render=render, **kwargs)
        return page.html

    async def links(self, url: str, *, render: bool = False, **kwargs: Any) -> list[str]:
        """Fetch a single page and return all links."""
        page = await self._fetch_page(url, render=render, **kwargs)
        return extract_links(page.html, url)

    async def _fetch_page(
        self,
        url: str,
        *,
        render: bool,
        goto_options: dict[str, Any] | None = None,
        wait_for_selector: str | None = None,
        reject_resource_types: list[str] | None = None,
    ) -> FetchResult:
        pool = await self._ensure_browser_pool() if render else None
        return await fetch_page_html(
            url,
            render=render,
            browser_pool=pool,
            goto_options=_build_goto_options(goto_options),
            wait_for_selector=wait_for_selector,
            reject_resource_types=reject_resource_types,
        )
```

**Blocking behaviour**: Unlike the HTTP API (which returns a job ID and runs the crawl in the background), the Python API's `crawl()` method is `await`-able and blocks until the crawl is complete. For non-blocking use, callers can use `anyio.create_task_group()` to run crawls concurrently.

**Scheduling split is intentional, not duplication**: `run_crawl` is invoked directly from both adapters but with different scheduling — `await` in the Python API (blocking contract) vs `task_group.start_soon` in the HTTP API (return-job-id contract). That's a legitimate contract difference at the adapter boundary, so it stays out of the services layer.

---

## 12. CLI

### 12.1 Command Structure

```
proctx-crawler <command> [options]

Commands:
  crawl       Start a multi-page crawl
  markdown    Extract Markdown from a single page
  content     Fetch rendered HTML from a single page
  links       Extract links from a single page
  serve       Start the HTTP API server
```

**Implementation**: `argparse` (stdlib). No external CLI framework dependency.

**Entry point**: `src/proctx_crawler/cli.py:main()`, registered as `proctx-crawler` in `pyproject.toml`.

**Default behaviour**: Running `proctx-crawler` with no subcommand prints the help message and exits with code 0.

**Command details**:

```
proctx-crawler crawl <url> [options]
  --limit N          Max pages (default: 10)
  --depth N          Max link depth (default: 1000)
  --source MODE      Discovery: links, llms_txt (default: links)
  --format FMT       Output format: markdown, html (default: markdown; repeatable)
  --render           Enable Playwright rendering
  --include PATTERN  URL include pattern (repeatable)
  --exclude PATTERN  URL exclude pattern (repeatable)
  --output DIR       Output directory (default: platform data dir)
  --quiet            Suppress progress output

proctx-crawler markdown <url> [options]
  --render           Enable Playwright rendering
  --output FILE      Write to file instead of stdout

proctx-crawler content <url> [options]
  --render           Enable Playwright rendering
  --output FILE      Write to file instead of stdout

proctx-crawler links <url> [options]
  --render           Enable Playwright rendering
  --external         Include external links

proctx-crawler serve [options]
  --host HOST        Bind address (default: 127.0.0.1)
  --port PORT        Bind port (default: 8080)
```

### 12.2 Output Formatting

- **`crawl`**: Prints progress to stderr (`Crawling [3/10] https://...`). On completion, prints the output directory path.
- **`markdown`** and **`content`**: Print content to stdout (pipe-friendly). Use `--output` to write to a file.
- **`links`**: One URL per line to stdout.
- **`serve`**: Prints server URL to stderr, then blocks.

All progress/status messages go to stderr. Content goes to stdout. This makes CLI output composable with Unix pipes.

---

## 13. Configuration

### 13.1 Settings Schema

```python
# config.py

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from pathlib import Path
import platformdirs

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PROCTX_CRAWLER__",
        env_nested_delimiter="__",
        yaml_file="proctx-crawler.yaml",
        yaml_file_encoding="utf-8",
    )

    # Storage
    output_dir: Path = Field(
        default_factory=lambda: Path(platformdirs.user_data_dir("proctx-crawler")) / "jobs"
    )
    db_path: Path = Field(
        default_factory=lambda: Path(platformdirs.user_data_dir("proctx-crawler")) / "crawler.db"
    )

    # Server
    server_host: str = "127.0.0.1"
    server_port: int = 8080

    # Crawl defaults
    default_limit: int = 10
    default_depth: int = 1000
    job_timeout: int = 3600           # defined, not yet enforced in v0.1
    max_concurrent_jobs: int = 10     # defined, not yet enforced in v0.1
    max_response_size: int = 10485760 # enforced on static fetches
    metadata_retention_days: int = 7  # defined, not yet enforced in v0.1

    # Auth (optional)
    auth_api_key: str | None = None

    # Playwright
    playwright_headless: bool = True
```

### 13.2 Configuration Loading Order

Settings are resolved in this order (last wins):

1. **Defaults** — hardcoded in the `Settings` class
2. **YAML config file** — `proctx-crawler.yaml` in the current directory, or `platformdirs.user_config_dir("proctx-crawler") / "config.yaml"`
3. **Environment variables** — `PROCTX_CRAWLER__OUTPUT_DIR`, `PROCTX_CRAWLER__SERVER_PORT`, etc.
4. **CLI arguments** — override everything (for CLI commands only)

---

## 14. Logging

```python
# logging_config.py

import structlog
import sys

def configure_logging(*, json: bool = False) -> None:
    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if json:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )
```

**Key rules**:

- All log output goes to **stderr** — stdout may be used by CLI commands for content output.
- Use `structlog.get_logger()` in all modules. Never use `print()` or stdlib `logging` directly.
- Context variables are used to bind `job_id` and `url` to log entries during crawl operations.
- JSON format is enabled in server mode for machine-parseable logs. Console format for CLI and development.
