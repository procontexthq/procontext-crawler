# ProContext Crawler: Functional Specification

> **Document**: 01-functional-spec.md
> **Status**: Draft v1
> **Last Updated**: 2026-03-16

---

## Table of Contents

- [1. Introduction](#1-introduction)
- [2. Design Philosophy](#2-design-philosophy)
- [3. Non-Goals](#3-non-goals)
- [4. Release Phases](#4-release-phases)
  - [4.1 v0.1 — Core](#41-v01--core)
  - [4.2 v0.2 — Enhanced](#42-v02--enhanced)
  - [4.3 v0.3+ — Extended](#43-v03--extended)
- [5. Interfaces](#5-interfaces)
  - [5.1 Python API](#51-python-api)
  - [5.2 HTTP API](#52-http-api)
  - [5.3 CLI](#53-cli)
- [6. Shared Parameters](#6-shared-parameters)
  - [6.1 Single-Page Base Parameters](#61-single-page-base-parameters)
  - [6.2 Rendering Parameters](#62-rendering-parameters)
  - [6.3 Authentication Parameters](#63-authentication-parameters)
- [7. Endpoints](#7-endpoints)
  - [7.1 POST /crawl — Start Crawl Job](#71-post-crawl--start-crawl-job)
  - [7.2 GET /crawl — Poll Status / Retrieve Results](#72-get-crawl--poll-status--retrieve-results)
  - [7.3 DELETE /crawl — Cancel Job](#73-delete-crawl--cancel-job)
  - [7.4 POST /markdown — Single-Page Markdown](#74-post-markdown--single-page-markdown)
  - [7.5 POST /content — Single-Page HTML](#75-post-content--single-page-html)
  - [7.6 POST /links — Extract Links](#76-post-links--extract-links)
  - [7.7 POST /scrape — CSS Selector Extraction [v0.2]](#77-post-scrape--css-selector-extraction-v02)
  - [7.8 POST /json — AI-Powered Extraction [v0.3]](#78-post-json--ai-powered-extraction-v03)
  - [7.9 POST /screenshot — Capture Screenshot [v0.3+]](#79-post-screenshot--capture-screenshot-v03)
  - [7.10 POST /pdf — Render PDF [v0.3+]](#710-post-pdf--render-pdf-v03)
  - [7.11 POST /snapshot — MHTML Snapshot [v0.3+]](#711-post-snapshot--mhtml-snapshot-v03)
- [8. Job Lifecycle](#8-job-lifecycle)
  - [8.1 Job States](#81-job-states)
  - [8.2 URL Record States](#82-url-record-states)
  - [8.3 State Transitions](#83-state-transitions)
  - [8.4 Cancellation Semantics](#84-cancellation-semantics)
  - [8.5 Job Timeout and Cleanup](#85-job-timeout-and-cleanup)
- [9. Content Storage](#9-content-storage)
  - [9.1 File-Based Output](#91-file-based-output)
  - [9.2 API Response Format](#92-api-response-format)
- [10. Error Handling](#10-error-handling)
  - [10.1 Error Envelope](#101-error-envelope)
  - [10.2 Error Codes](#102-error-codes)
- [11. Design Decisions](#11-design-decisions)

---

## 1. Introduction

ProContext Crawler is a self-hosted crawl API for extracting structured content from websites. Given a starting URL, it discovers linked pages (up to a configurable depth and page limit), fetches them with optional JavaScript rendering via Playwright, and returns clean Markdown, raw HTML, or structured data.

**The problem it solves**: Documentation sites, knowledge bases, and content-rich websites need to be converted into structured formats for RAG pipelines, LLM consumption, and offline access. Many sites use JavaScript-heavy frameworks (Next.js, Docusaurus, Gatsby) that require a real browser to render. ProContext Crawler handles both static and dynamic pages, producing clean output suitable for downstream processing.

**Inspired by**: [Cloudflare's Browser Rendering /crawl API](https://developers.cloudflare.com/browser-rendering/rest-api/crawl-endpoint/). See `docs/research/` for the full analysis.

---

## 2. Design Philosophy

**Speed-first.** Most documentation pages are static or server-side rendered. The default fetch path is a fast `httpx` GET — no browser, no JavaScript execution. Playwright rendering is opt-in (`render: true`) or, in v0.2, auto-detected when the static response looks like a JS shell. This keeps the 80% case fast.

**Library-first, server-second.** ProContext Crawler is a Python library that can be used directly (`await crawler.crawl(url)`) without running an HTTP server. The HTTP API and CLI are thin wrappers over the core library. This makes it embeddable in RAG pipelines, scripts, and other Python applications.

**File-based output.** Crawled content lands on disk as individual files — one per page, organized by job. Content is inspectable, git-friendly, and trivially consumable by downstream tools. No database for content; the database only tracks job metadata and URL queue state.

**Swappable infrastructure.** The database is behind a `Repository` protocol (abstraction layer). Start with SQLite, swap to Postgres or anything else without touching business logic.

---

## 3. Non-Goals

The following are explicitly out of scope:

- **Hosted/managed service**: This is self-hosted software. No multi-tenant SaaS infrastructure, no usage-based billing, no global edge deployment.
- **Bot detection bypass**: The crawler does not attempt to evade CAPTCHAs, Turnstile, or bot management systems. Sites that block automated access will return errors.
- **Content transformation beyond extraction**: No summarization, chunking, or semantic processing. The crawler extracts content as-is. Downstream tools handle transformation.
- **Full-text search across crawled pages**: No FTS index, no BM25. The crawler produces files; search is the consumer's responsibility.
- **Distributed crawling**: Single-process, single-machine. Horizontal scaling is not a design goal for v0.x.
- **Real-time monitoring dashboard**: Job status is available via API poll. No WebSocket push, no live UI.

---

## 4. Release Phases

### 4.1 v0.1 — Core

The minimum to be useful. Crawl a URL, get Markdown files on disk.

**Endpoints**: `/crawl` (POST/GET/DELETE), `/markdown`, `/content`, `/links`

**Features**:
- Single-URL crawl with link discovery (HTML `<a>` tags)
- llms.txt URL discovery mode (`source: "llms_txt"`)
- Configurable depth (default: 1000) and page limit (default: 10)
- URL include/exclude patterns with wildcard matching
- Subdomain and external link controls
- Static fetching via httpx (default)
- Playwright rendering (opt-in via `render: true`)
- Markdown and HTML output formats
- File-based content storage on disk
- Async job API (POST to start, GET to poll, DELETE to cancel)
- DB-backed job state with Repository abstraction (SQLite implementation)
- Python API: `Crawler` class usable without the HTTP server
- CLI: `proctx-crawler crawl <url>` for one-off use

### 4.2 v0.2 — Enhanced

Polish, resilience, and new extraction capabilities.

**New endpoints**: `/scrape`

**Features**:
- Auto-detect JS rendering (static fetch → detect JS shell → auto-retry with Playwright)
- robots.txt compliance (respect by default, flag to override)
- Per-domain rate limiting (configurable delay between requests to same host)
- Authentication to target sites (`authenticate`, `cookies`, `set_extra_http_headers`)
- Page caching with configurable TTL (`max_age`)
- Content deduplication (skip identical pages)
- Metadata extraction per page (title, canonical URL, HTTP status, content hash)
- Incremental crawling (`modified_since` — skip unmodified pages)
- Sitemap discovery (`source: "sitemaps"`)
- CSS selector-based element extraction (`/scrape` endpoint)

### 4.3 v0.3+ — Extended

Advanced features for specialized use cases.

**New endpoints**: `/json`, `/screenshot`, `/pdf`, `/snapshot`

**Features**:
- AI-powered structured JSON extraction (requires LLM backend)
- Screenshot capture (PNG/JPEG)
- PDF rendering
- MHTML snapshot (full page archive)
- Streaming results (SSE for real-time crawl progress)
- Export (zip/tar download of crawl output)
- Webhook callbacks on job completion
- Request pattern filtering (`reject_request_pattern`, `allow_request_pattern`)
- Pluggable extractors (custom HTML-to-Markdown pipelines)

---

## 5. Interfaces

ProContext Crawler exposes three interfaces. All three share the same core behavior — the interfaces differ only in how parameters are passed and results are returned.

### 5.1 Python API

The primary interface. No server required.

```python
from proctx_crawler import Crawler

async with Crawler() as crawler:
    # Multi-page crawl
    job = await crawler.crawl("https://docs.pydantic.dev/llms.txt", depth=2, formats=["markdown"])
    for record in job.records:
        print(record.url, record.markdown[:100])

    # Single-page extraction
    md = await crawler.markdown("https://docs.pydantic.dev/concepts/models")
    html = await crawler.content("https://docs.pydantic.dev/concepts/models")
    links = await crawler.links("https://docs.pydantic.dev/concepts/models")
```

### 5.2 HTTP API

FastAPI server for language-agnostic access. Intended for integrating with non-Python systems or running as a shared service.

```bash
# Start the server
proctx-crawler serve --port 8080

# Start a crawl
curl -X POST http://localhost:8080/crawl \
  -H "Content-Type: application/json" \
  -d '{"url": "https://docs.pydantic.dev/llms.txt", "depth": 2}'

# Poll results
curl http://localhost:8080/crawl?id=<job-id>

# Single-page Markdown
curl -X POST http://localhost:8080/markdown \
  -H "Content-Type: application/json" \
  -d '{"url": "https://docs.pydantic.dev/concepts/models"}'
```

### 5.3 CLI

For one-off crawls and scripting. No server needed — uses the Python API directly.

```bash
# Crawl and save to disk
proctx-crawler crawl https://docs.pydantic.dev/llms.txt --depth 2 --format markdown

# Single-page Markdown to stdout
proctx-crawler markdown https://docs.pydantic.dev/concepts/models

# Extract links
proctx-crawler links https://docs.pydantic.dev/concepts/models
```

---

## 6. Shared Parameters

Parameters used across multiple endpoints. Defined once here, referenced by endpoint sections.

### 6.1 Single-Page Base Parameters

Used by `/markdown`, `/content`, `/links`, `/scrape`, `/screenshot`, `/pdf`, `/snapshot`.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | Yes* | — | URL of the page to process. |
| `html` | string | Yes* | — | Raw HTML content to process (alternative to `url`). |
| `render` | boolean | No | `false` | When `true`, use Playwright to render the page (executes JavaScript). When `false`, fetch raw HTML via httpx. |

\* Provide either `url` or `html`, not both. At least one is required.

### 6.2 Rendering Parameters

Only apply when `render: true`. Ignored when `render: false`.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `goto_options.wait_until` | string | No | `"load"` | Page load strategy: `"load"`, `"domcontentloaded"`, `"networkidle0"` (no connections for 500ms), `"networkidle2"` (≤2 connections for 500ms). |
| `goto_options.timeout` | integer | No | 30000 | Navigation timeout in milliseconds. |
| `wait_for_selector` | string | No | — | CSS selector to wait for before extracting content. Useful for SPAs where content loads asynchronously. |
| `reject_resource_types` | array | No | — | Resource types to block: `"image"`, `"media"`, `"font"`, `"stylesheet"`. Speeds up rendering by skipping unnecessary resources. |

### 6.3 Authentication Parameters [v0.2]

For fetching gated or authenticated content. Apply to both static and rendered fetches.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `authenticate` | object | No | — | HTTP Basic Auth credentials: `{"username": "...", "password": "..."}`. |
| `cookies` | array | No | — | Cookies to set before loading. Each entry: `{"name": "...", "value": "...", "domain": "...", "path": "/"}`. |
| `set_extra_http_headers` | object | No | — | Custom HTTP headers for the request (e.g., `{"Authorization": "Bearer ..."}` for token-based auth). |
| `user_agent` | string | No | — | Custom User-Agent string. Note: does not bypass bot detection. |

---

## 7. Endpoints

### 7.1 POST /crawl — Start Crawl Job

**Purpose**: Start an asynchronous multi-page crawl. Returns a job ID immediately. Use `GET /crawl` to poll for status and results.

**Input**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | Yes | — | Starting URL. Can be any webpage or an llms.txt index. |
| `limit` | integer | No | 10 | Maximum number of pages to crawl. |
| `depth` | integer | No | 1000 | Maximum link hops from the starting URL. |
| `source` | string | No | `"links"` | URL discovery strategy: `"links"`, `"llms_txt"`, `"sitemaps"` [v0.2], `"all"` [v0.2]. |
| `formats` | array | No | `["markdown"]` | Output formats per page: `"markdown"`, `"html"`. `"json"` added in v0.3. |
| `render` | boolean | No | `false` | Use Playwright for all pages in this crawl. |
| `goto_options` | object | No | — | Rendering params (see Section 6.2). Apply to all pages when `render: true`. |
| `wait_for_selector` | string | No | — | CSS selector to wait for on each page (see Section 6.2). |
| `reject_resource_types` | array | No | — | Resource types to block (see Section 6.2). |
| `options.include_patterns` | array | No | — | Wildcard URL patterns to include. |
| `options.exclude_patterns` | array | No | — | Wildcard URL patterns to exclude. **Exclude always wins over include.** |
| `options.include_subdomains` | boolean | No | `false` | Follow links to subdomains of the starting URL's domain. |
| `options.include_external_links` | boolean | No | `false` | Follow links to external domains. |

**URL discovery sources**:

| Source | Behavior |
|--------|----------|
| `"links"` | Parse HTML `<a>` tags from each fetched page to discover new URLs. Default. |
| `"llms_txt"` | Parse the starting URL as an llms.txt file. Extract all documentation links listed in it. Do not follow HTML links from individual pages. |
| `"sitemaps"` [v0.2] | Parse `sitemap.xml` from the starting URL's domain to discover URLs. |
| `"all"` [v0.2] | Combine all discovery strategies: sitemaps first, then HTML links for pages not found via sitemap, with llms.txt auto-detected if the starting URL matches the format. |

**URL pattern matching**:

- `*` matches any character except `/`
- `**` matches any character including `/`
- Example: `"https://docs.example.com/api/**"` matches all pages under `/api/`
- Example: `"https://docs.example.com/*/v2/*"` matches `/en/v2/guide` but not `/en/v2/api/auth`
- When no patterns are specified, all discovered URLs are crawled
- When only exclude patterns are specified, everything except excluded URLs is crawled
- When only include patterns are specified, only matching URLs are crawled
- **Exclude always takes precedence over include** — if a URL matches both, it is excluded

**Processing**:

1. Validate inputs; create job record in DB with status `queued`
2. Enqueue starting URL; set job status to `running`
3. BFS crawl loop:
   a. Dequeue next URL
   b. Skip if already visited, or if depth exceeds `depth`, or if URL doesn't match include/exclude patterns
   c. Fetch page (static or Playwright depending on `render`)
   d. Extract content in requested formats (Markdown, HTML)
   e. Write content files to disk under `<output_dir>/<job_id>/`
   f. Mark URL as `completed` in DB
   g. Discover new URLs from the page (per `source` strategy)
   h. Enqueue newly discovered URLs (that pass pattern filtering and haven't been visited)
   i. Stop if `limit` reached or queue exhausted
4. Set job status to `completed`

**Output**:

```json
{
  "success": true,
  "result": "550e8400-e29b-41d4-a716-446655440000"
}
```

The `result` is the job ID (UUID). Use it with `GET /crawl` to poll.

---

### 7.2 GET /crawl — Poll Status / Retrieve Results

**Purpose**: Check job status and retrieve crawled content. Supports pagination for large result sets.

**Input** (query parameters):

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `id` | string | Yes | — | Job ID from `POST /crawl`. |
| `limit` | integer | No | 100 | Maximum number of records to return. |
| `cursor` | string | No | — | Pagination cursor from a previous response. |
| `status` | string | No | — | Filter records by URL status: `"queued"`, `"completed"`, `"errored"`, `"skipped"`. |

**Output**:

```json
{
  "success": true,
  "result": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "completed",
    "total": 15,
    "finished": 15,
    "records": [
      {
        "url": "https://docs.pydantic.dev/concepts/models",
        "status": "completed",
        "markdown": "# Models\n\nPydantic models are the core...",
        "html": "<html>...</html>",
        "metadata": {
          "http_status": 200,
          "title": "Models - Pydantic",
          "content_hash": "a1b2c3d4e5f6"
        }
      }
    ],
    "cursor": "eyJvZmZzZXQiOjEwMH0"
  }
}
```

| Field | Description |
|-------|-------------|
| `id` | Job ID. |
| `status` | Job-level status (see Section 8.1). |
| `total` | Total number of URLs discovered for this job. |
| `finished` | Number of URLs in a terminal state (completed, errored, skipped). |
| `records` | Array of URL records for this page of results. |
| `records[].url` | The URL that was crawled. |
| `records[].status` | URL-level status (see Section 8.2). |
| `records[].markdown` | Markdown content (if `"markdown"` was in `formats`). |
| `records[].html` | HTML content (if `"html"` was in `formats`). |
| `records[].metadata` | Per-URL metadata: HTTP status, page title, content hash. |
| `cursor` | Pagination cursor. Pass as `cursor` in the next request. `null` when no more results. |

**Notes**:

- For lightweight status checks while a job is running, use `limit=0` — this returns job-level metadata without any records.
- Records are returned in the order they were crawled (insertion order).
- The `cursor` is opaque — do not parse or construct it. It encodes internal pagination state.

---

### 7.3 DELETE /crawl — Cancel Job

**Purpose**: Cancel a running crawl job. URLs already completed are preserved; queued URLs are cancelled.

**Input** (query parameters):

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | string | Yes | Job ID to cancel. |

**Processing**:

1. Mark all `queued` URLs as `cancelled`
2. Wait for any in-flight fetches to complete (do not abort mid-fetch)
3. Set job status to `cancelled`

**Output**:

```json
{
  "success": true,
  "result": "cancelled"
}
```

**Notes**:

- Cancelling a job that is already in a terminal state (`completed`, `errored`, `cancelled`) returns success (idempotent).
- Completed URL records and their content files are preserved on disk after cancellation.

---

### 7.4 POST /markdown — Single-Page Markdown

**Purpose**: Fetch a single page and return its content as Markdown. Synchronous — the response contains the result directly.

**Input**: Single-page base parameters (Section 6.1) + rendering parameters (Section 6.2).

**Processing**:

1. Fetch the page (static or Playwright depending on `render`)
2. Convert HTML to Markdown
3. Return the Markdown content

**Output**:

```json
{
  "success": true,
  "result": "# Models\n\nPydantic models are the core building block..."
}
```

**Notes**:

- For JavaScript-heavy pages, set `render: true` and consider `goto_options.wait_until: "networkidle0"` or `wait_for_selector` to ensure content has loaded before extraction.
- Blocking images, media, and fonts via `reject_resource_types` significantly speeds up Playwright rendering when only text content is needed.

---

### 7.5 POST /content — Single-Page HTML

**Purpose**: Fetch a single page and return its fully-rendered HTML. When `render: true`, JavaScript is executed before capturing the HTML.

**Input**: Single-page base parameters (Section 6.1) + rendering parameters (Section 6.2).

**Processing**:

1. Fetch the page (static or Playwright depending on `render`)
2. Return the HTML content (includes `<head>` when rendered)

**Output**:

```json
{
  "success": true,
  "result": "<!DOCTYPE html><html>...</html>"
}
```

---

### 7.6 POST /links — Extract Links

**Purpose**: Extract all links from a page. Useful for understanding page structure before crawling, or for building URL lists programmatically.

**Input**: Single-page base parameters (Section 6.1) + rendering parameters (Section 6.2), plus:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `visible_links_only` | boolean | No | `false` | Return only user-visible links (skip hidden elements). Only effective when `render: true`. |
| `exclude_external_links` | boolean | No | `false` | Filter out cross-domain links. |

**Processing**:

1. Fetch the page (static or Playwright depending on `render`)
2. Parse all `<a href="...">` elements
3. Resolve relative URLs to absolute
4. Apply filters (`visible_links_only`, `exclude_external_links`)
5. Deduplicate and return

**Output**:

```json
{
  "success": true,
  "result": [
    "https://docs.pydantic.dev/concepts/models",
    "https://docs.pydantic.dev/concepts/fields",
    "https://docs.pydantic.dev/concepts/validators"
  ]
}
```

---

### 7.7 POST /scrape — CSS Selector Extraction [v0.2]

**Purpose**: Extract specific HTML elements from a page using CSS selectors. Returns text content, inner HTML, attributes, and dimensions for each matched element.

**Input**: Single-page base parameters (Section 6.1) + rendering parameters (Section 6.2), plus:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `elements` | array | Yes | CSS selectors to extract. Each entry: `{"selector": "CSS selector"}`. |

**Output**:

```json
{
  "success": true,
  "result": [
    {
      "selector": "h1",
      "results": [
        {
          "text": "Models",
          "html": "<h1>Models</h1>",
          "attributes": [{"name": "class", "value": "title"}],
          "width": 800,
          "height": 40,
          "top": 10,
          "left": 0
        }
      ]
    }
  ]
}
```

**Notes**: Dimension and position data (`width`, `height`, `top`, `left`) are only available when `render: true`.

---

### 7.8 POST /json — AI-Powered Extraction [v0.3]

**Purpose**: Extract structured data from a page using an AI model. Provide a natural language prompt or a JSON schema, and the endpoint returns structured data matching the specification.

**Input**: Single-page base parameters (Section 6.1) + rendering parameters (Section 6.2), plus:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `prompt` | string | Yes* | Natural language extraction instruction. |
| `response_format` | object | Yes* | JSON schema defining the expected output structure: `{"type": "json_schema", "schema": {...}}`. |
| `model` | object | No | AI model configuration: `{"provider": "...", "model": "...", "api_key": "..."}`. |

\* Provide `prompt`, `response_format`, or both.

**Output**:

```json
{
  "success": true,
  "result": {
    "title": "Models - Pydantic",
    "sections": ["Defining a Model", "Field Types", "Validators"],
    "code_examples": 12
  }
}
```

**Notes**: This endpoint requires an AI model backend. The model configuration is provided per-request — no server-side AI credentials are stored.

---

### 7.9 POST /screenshot — Capture Screenshot [v0.3+]

**Purpose**: Capture a screenshot of a page. Always uses Playwright (`render` is implicitly `true`).

**Input**: Single-page base parameters (Section 6.1) + rendering parameters (Section 6.2), plus:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `screenshot_options.type` | string | No | `"png"` | Image format: `"png"` or `"jpeg"`. |
| `screenshot_options.quality` | integer | No | — | JPEG quality (0-100). Only valid with `type: "jpeg"`. |
| `screenshot_options.full_page` | boolean | No | `false` | Capture the full scrollable page. |
| `screenshot_options.clip` | object | No | — | Crop region: `{x, y, width, height}`. |
| `viewport` | object | No | `{width: 1920, height: 1080}` | Browser viewport dimensions. |
| `selector` | string | No | — | CSS selector — capture only this element. |

**Output**: Binary image data (PNG or JPEG).

---

### 7.10 POST /pdf — Render PDF [v0.3+]

**Purpose**: Render a page as a PDF document. Always uses Playwright.

**Input**: Single-page base parameters (Section 6.1) + rendering parameters (Section 6.2), plus:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `pdf_options.format` | string | No | `"a4"` | Paper size: `"a4"`, `"a5"`, `"letter"`, etc. |
| `pdf_options.landscape` | boolean | No | `false` | Landscape orientation. |
| `pdf_options.scale` | number | No | 1.0 | Zoom level. |
| `pdf_options.print_background` | boolean | No | `false` | Include background colors/images. |
| `pdf_options.margin` | object | No | — | Page margins: `{top, bottom, left, right}`. |
| `pdf_options.display_header_footer` | boolean | No | `false` | Show header and footer. |
| `pdf_options.header_template` | string | No | — | HTML header template. |
| `pdf_options.footer_template` | string | No | — | HTML footer template. |

**Output**: Binary PDF data.

---

### 7.11 POST /snapshot — MHTML Snapshot [v0.3+]

**Purpose**: Take an MHTML snapshot of a page — a single-file archive containing HTML, CSS, images, and other resources. Always uses Playwright.

**Input**: Single-page base parameters (Section 6.1) + rendering parameters (Section 6.2).

**Output**: Binary MHTML data.

**Notes**: MHTML snapshots are useful for archival and offline viewing. The snapshot captures the page exactly as rendered, including all embedded resources.

---

## 8. Job Lifecycle

### 8.1 Job States

| State | Description |
|-------|-------------|
| `queued` | Job created, not yet started. |
| `running` | Crawl is in progress. URLs are being fetched and processed. |
| `completed` | All URLs have been processed (some may have errored). |
| `cancelled` | Job was cancelled by the user. Completed URLs are preserved. |
| `errored` | Job failed due to an internal error (not a per-URL error). |

### 8.2 URL Record States

| State | Description |
|-------|-------------|
| `queued` | URL discovered but not yet fetched. |
| `running` | URL is currently being fetched. |
| `completed` | URL successfully fetched and content extracted. |
| `errored` | Fetch or extraction failed for this URL. |
| `skipped` | URL was skipped (duplicate, filtered by pattern, or depth exceeded). |
| `cancelled` | URL was cancelled before fetching (job cancellation). |
| `disallowed` [v0.2] | URL blocked by robots.txt. |

### 8.3 State Transitions

```
Job:     queued → running → completed
                         → cancelled (user-initiated)
                         → errored (internal failure)

URL:     queued → running → completed
                         → errored
                         → skipped
               → cancelled (job cancelled)
               → disallowed (robots.txt, v0.2)
```

A job transitions to `completed` when all URLs have reached a terminal state — even if some URLs errored. The job only transitions to `errored` for internal failures (e.g., DB write failure, unhandled exception), not because individual URLs failed.

### 8.4 Cancellation Semantics

When `DELETE /crawl` is called:

1. All `queued` URLs are moved to `cancelled`
2. URLs currently in `running` state are allowed to finish (no mid-fetch abort)
3. No new URLs are enqueued
4. Once all in-flight URLs finish, the job moves to `cancelled`

Content files for completed URLs are preserved on disk.

### 8.5 Job Timeout and Cleanup

- Default job timeout: 1 hour (configurable). Jobs exceeding the timeout are cancelled automatically.
- Content files persist on disk until explicitly deleted. No auto-expiry.
- Job metadata in the DB can be cleaned up via a configurable retention period (default: 7 days).

---

## 9. Content Storage

### 9.1 File-Based Output

Crawled content is written to disk under a configurable output directory:

```
<output_dir>/
  <job_id>/
    manifest.json            # Job metadata + URL-to-file mapping
    <url_hash>.md            # Markdown content (if "markdown" in formats)
    <url_hash>.html          # HTML content (if "html" in formats)
    ...
```

- `<output_dir>` defaults to `platformdirs.user_data_dir("proctx-crawler") / "jobs"`. Configurable.
- `<job_id>` is a UUID.
- `<url_hash>` is a truncated SHA-256 of the URL (16 hex chars). This avoids filesystem path issues with long/special-character URLs.
- `manifest.json` maps each `<url_hash>` back to its original URL and contains job-level metadata (status, timing, config).

### 9.2 API Response Format

When retrieving results via `GET /crawl`, content is returned inline in the JSON response (the `markdown` and `html` fields in each record). The file-based output and the API response contain the same content — the files are the source of truth, and the API reads from them.

For very large crawls, the cursor-based pagination prevents the response from exceeding memory limits.

---

## 10. Error Handling

### 10.1 Error Envelope

All error responses follow this structure:

```json
{
  "success": false,
  "error": {
    "code": "FETCH_FAILED",
    "message": "Failed to fetch https://example.com/page: connection timeout",
    "recoverable": true
  }
}
```

| Field | Description |
|-------|-------------|
| `code` | Machine-readable error code. |
| `message` | Human-readable description of what went wrong. |
| `recoverable` | `true` if retrying the same request may succeed (transient failure). `false` if the request must change. |

### 10.2 Error Codes

| Code | Endpoints | `recoverable` | Description |
|------|-----------|---------------|-------------|
| `INVALID_INPUT` | All | `false` | Input validation failed (missing required field, invalid URL, etc.). |
| `FETCH_FAILED` | `/markdown`, `/content`, `/links`, `/scrape`, `/crawl` | `true` | Network error, timeout, or non-200 HTTP response. |
| `NOT_FOUND` | `/markdown`, `/content`, `/links`, `/scrape`, `/crawl` | `false` | HTTP 404 — page does not exist. |
| `JOB_NOT_FOUND` | `GET /crawl`, `DELETE /crawl` | `false` | Job ID does not exist. |
| `RENDER_FAILED` | Any (when `render: true`) | `true` | Playwright rendering failed (browser crash, timeout, etc.). |
| `INVALID_SELECTOR` | `/scrape`, single-page with `wait_for_selector` | `false` | CSS selector is invalid. |
| `DISALLOWED` | `/crawl` [v0.2] | `false` | URL blocked by robots.txt. |
| `EXTRACTION_FAILED` | `/json` [v0.3] | `true` | AI extraction failed (model error, invalid response). |

---

## 11. Design Decisions

**D1: Static-first, Playwright-second**
The default fetch mode is static httpx — no browser, no JavaScript. Playwright rendering is opt-in via `render: true`. Most documentation sites are static or SSR'd, making static fetch the right default for speed. Playwright adds 10-50x latency per page.

_Trade-off_: Users must explicitly set `render: true` for JS-heavy sites, or wait for the auto-detect feature in v0.2. Accepted — explicit is better than implicit, and the speed difference is substantial.

**D2: File-based content, DB-backed metadata**
Crawled content goes to disk as individual files. The database only stores job state, URL queue, and metadata. This means content is inspectable with standard tools, easy to pipe into RAG pipelines, and never bloats the database. A 10,000-page crawl produces 10,000 files rather than 10,000 rows of large text in SQLite.

_Trade-off_: File I/O is slower than SQLite reads for serving content via the API. Accepted — the primary consumption path is direct file access, not API polling.

**D3: llms.txt as a URL discovery feature, not the core**
The `source: "llms_txt"` option treats the starting URL as an llms.txt index and extracts documentation links from it rather than parsing HTML `<a>` tags. This is a first-class feature, but it's one of several URL discovery strategies — the crawler works with any URL. llms.txt is the most reliable discovery method for documentation sites that publish one, because it's a curated list rather than ad-hoc link scraping.

**D4: Repository pattern for DB abstraction**
The database is accessed through a `Repository` protocol (Python Protocol class) with methods like `save_job`, `get_job`, `enqueue_urls`, `mark_url_complete`. The v0.1 implementation uses SQLite. The abstraction exists from day one so that business logic never imports `aiosqlite` directly — swapping to Postgres, DynamoDB, or any other backend requires only a new `Repository` implementation.

_Trade-off_: Slight over-engineering for v0.1 where SQLite is the only backend. Accepted — the cost is one protocol definition, and the payoff is clean separation that prevents coupling.

**D5: render: false by default (opposite of Cloudflare)**
Cloudflare defaults `render: true` because they own the browser fleet and rendering is cheap. We default `render: false` because Playwright is a heavyweight dependency that is 10-50x slower than httpx. For documentation sites — our primary use case — most content is accessible via static fetch. Users who need rendering opt in explicitly.

_Trade-off_: JS-heavy sites return empty or incomplete content by default. Accepted — users targeting these sites set `render: true`, and v0.2 auto-detection will handle the middle ground.

**D6: Exclude patterns always win over include**
When a URL matches both an include pattern and an exclude pattern, it is excluded. This follows Cloudflare's semantics and prevents accidental inclusion of sensitive or irrelevant URLs. There is no "priority" or "ordering" — exclude is always final.

**D7: Cursor-based pagination for crawl results**
Crawl results are paginated using an opaque cursor rather than offset-based pagination. This is better for crawl jobs because the result set grows during the crawl — offset-based pagination can skip or duplicate records when new results are inserted. The cursor encodes a stable position in the result set.

**D8: Library first, server second**
The `Crawler` class is a standalone Python library with no dependency on FastAPI. The HTTP API and CLI are thin wrappers. This makes the crawler embeddable in any Python project — RAG pipelines, scripts, CI/CD, Jupyter notebooks — without running a server process. The HTTP API exists for non-Python consumers and shared deployments.

**D9: All 9 Cloudflare endpoints, phased across releases**
Every Cloudflare Browser Rendering endpoint has a counterpart in ProContext Crawler, but they are implemented in phases. v0.1 ships the 4 most useful endpoints for documentation extraction (`/crawl`, `/markdown`, `/content`, `/links`). v0.2 adds `/scrape`. v0.3+ adds `/json`, `/screenshot`, `/pdf`, `/snapshot`. This avoids scope creep while ensuring nothing is permanently excluded.

_Trade-off_: v0.1 users who need screenshots or PDFs must wait or use other tools. Accepted — those are not core to the documentation extraction use case that motivates this project.

**D10: Depth default of 1000**
The crawl depth defaults to 1000, which is high enough to handle deep documentation trees without configuration, but still bounded to prevent truly unbounded crawls. The `limit` parameter (default: 10 pages) is the primary safety valve — even with unlimited depth, the crawl stops after 10 pages unless the user raises the limit.

_Trade-off_: A depth of 1000 is effectively unlimited for most sites. The real protection comes from `limit`, not `depth`. This is intentional — depth is a structural constraint (how far from the root), while limit is a resource constraint (how many pages total).
