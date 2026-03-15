# ProContext Crawler: API Reference

> **Document**: 04-api-reference.md
> **Status**: Draft v1
> **Last Updated**: 2026-03-16
> **Depends on**: 01-functional-spec.md, 02-technical-spec.md

---

## Table of Contents

- [1. HTTP API Overview](#1-http-api-overview)
  - [1.1 Base URL](#11-base-url)
  - [1.2 Authentication](#12-authentication)
  - [1.3 Response Envelope](#13-response-envelope)
  - [1.4 Error Envelope](#14-error-envelope)
- [2. POST /crawl — Start Crawl Job](#2-post-crawl--start-crawl-job)
- [3. GET /crawl — Poll Status / Retrieve Results](#3-get-crawl--poll-status--retrieve-results)
- [4. DELETE /crawl — Cancel Job](#4-delete-crawl--cancel-job)
- [5. POST /markdown — Single-Page Markdown](#5-post-markdown--single-page-markdown)
- [6. POST /content — Single-Page HTML](#6-post-content--single-page-html)
- [7. POST /links — Extract Links](#7-post-links--extract-links)
- [8. POST /scrape — CSS Selector Extraction [v0.2]](#8-post-scrape--css-selector-extraction-v02)
- [9. POST /json — AI-Powered Extraction [v0.3]](#9-post-json--ai-powered-extraction-v03)
- [10. POST /screenshot — Capture Screenshot [v0.3+]](#10-post-screenshot--capture-screenshot-v03)
- [11. POST /pdf — Render PDF [v0.3+]](#11-post-pdf--render-pdf-v03)
- [12. POST /snapshot — MHTML Snapshot [v0.3+]](#12-post-snapshot--mhtml-snapshot-v03)
- [13. Python API Reference](#13-python-api-reference)
  - [13.1 Crawler Class](#131-crawler-class)
  - [13.2 crawl()](#132-crawl)
  - [13.3 markdown()](#133-markdown)
  - [13.4 content()](#134-content)
  - [13.5 links()](#135-links)
  - [13.6 Result Types](#136-result-types)
- [14. CLI Reference](#14-cli-reference)
  - [14.1 crawl](#141-crawl)
  - [14.2 markdown](#142-markdown)
  - [14.3 content](#143-content)
  - [14.4 links](#144-links)
  - [14.5 serve](#145-serve)
- [15. Error Reference](#15-error-reference)

---

## 1. HTTP API Overview

### 1.1 Base URL

```
http://localhost:8080
```

Configurable via `PROCTX_CRAWLER__SERVER_HOST` and `PROCTX_CRAWLER__SERVER_PORT` environment variables, or in `proctx-crawler.yaml`.

### 1.2 Authentication

Authentication is **optional**. When `PROCTX_CRAWLER__AUTH__API_KEY` is set, all requests must include:

```
Authorization: Bearer <api-key>
```

Requests without a valid key receive a `401 Unauthorized` response.

### 1.3 Response Envelope

All successful responses share this structure:

```json
{
  "success": true,
  "result": <T>
}
```

The type of `result` varies by endpoint.

### 1.4 Error Envelope

All error responses share this structure:

```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable description",
    "recoverable": true
  }
}
```

See [Section 15](#15-error-reference) for the full error catalogue.

---

## 2. POST /crawl — Start Crawl Job

Start an asynchronous multi-page crawl.

### Request

```
POST /crawl
Content-Type: application/json
```

**Body** (JSON):

```json
{
  "url": "https://docs.pydantic.dev/llms.txt",
  "limit": 50,
  "depth": 1000,
  "source": "llms_txt",
  "formats": ["markdown"],
  "render": false,
  "options": {
    "include_patterns": ["https://docs.pydantic.dev/**"],
    "exclude_patterns": ["https://docs.pydantic.dev/blog/**"],
    "include_subdomains": false,
    "include_external_links": false
  }
}
```

**Parameters**:

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `url` | string | Yes | — | Starting URL |
| `limit` | integer | No | 10 | Max pages to crawl (min: 1) |
| `depth` | integer | No | 1000 | Max link hops from starting URL (min: 0) |
| `source` | string | No | `"links"` | URL discovery: `"links"`, `"llms_txt"`, `"sitemaps"` [v0.2], `"all"` [v0.2] |
| `formats` | string[] | No | `["markdown"]` | Output formats: `"markdown"`, `"html"` |
| `render` | boolean | No | `false` | Use Playwright rendering |
| `goto_options.wait_until` | string | No | `"load"` | Page load strategy (render only) |
| `goto_options.timeout` | integer | No | 30000 | Navigation timeout in ms (render only) |
| `wait_for_selector` | string | No | — | CSS selector to wait for (render only) |
| `reject_resource_types` | string[] | No | — | Resource types to block (render only) |
| `options.include_patterns` | string[] | No | — | Wildcard URL include patterns |
| `options.exclude_patterns` | string[] | No | — | Wildcard URL exclude patterns |
| `options.include_subdomains` | boolean | No | `false` | Follow subdomain links |
| `options.include_external_links` | boolean | No | `false` | Follow cross-domain links |

### Response

**200 OK**:

```json
{
  "success": true,
  "result": "550e8400-e29b-41d4-a716-446655440000"
}
```

`result` is the job ID (UUID). Use it with `GET /crawl` to poll.

### Errors

| Code | HTTP Status | Cause |
|------|-------------|-------|
| `INVALID_INPUT` | 400 | Missing `url`, invalid parameters |

### curl Example

```bash
# Start a crawl with llms.txt discovery
curl -X POST http://localhost:8080/crawl \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://docs.pydantic.dev/llms.txt",
    "source": "llms_txt",
    "limit": 50,
    "formats": ["markdown"]
  }'

# Start a crawl with Playwright rendering
curl -X POST http://localhost:8080/crawl \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://react.dev/learn",
    "limit": 20,
    "render": true,
    "goto_options": {"wait_until": "networkidle0"},
    "options": {
      "include_patterns": ["https://react.dev/learn/**"]
    }
  }'
```

---

## 3. GET /crawl — Poll Status / Retrieve Results

Check job status and retrieve crawled content.

### Request

```
GET /crawl?id=<job-id>&limit=100&cursor=<cursor>&status=completed
```

**Query parameters**:

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | Yes | — | Job ID |
| `limit` | integer | No | 100 | Max records to return (0 for status only) |
| `cursor` | string | No | — | Pagination cursor from previous response |
| `status` | string | No | — | Filter by URL status: `"queued"`, `"completed"`, `"errored"`, `"skipped"` |

### Response

**200 OK**:

```json
{
  "success": true,
  "result": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "running",
    "total": 50,
    "finished": 23,
    "records": [
      {
        "url": "https://docs.pydantic.dev/concepts/models",
        "status": "completed",
        "markdown": "# Models\n\nPydantic models are...",
        "html": null,
        "metadata": {
          "http_status": 200,
          "title": "Models - Pydantic",
          "content_hash": "a1b2c3d4e5f67890"
        }
      },
      {
        "url": "https://docs.pydantic.dev/concepts/fields",
        "status": "completed",
        "markdown": "# Fields\n\nFields define...",
        "html": null,
        "metadata": {
          "http_status": 200,
          "title": "Fields - Pydantic",
          "content_hash": "b2c3d4e5f6789012"
        }
      }
    ],
    "cursor": "eyJpZCI6ICIxMjM0NTY3OCJ9"
  }
}
```

**Response fields**:

| Field | Type | Description |
|-------|------|-------------|
| `result.id` | string | Job ID |
| `result.status` | string | Job status: `"queued"`, `"running"`, `"completed"`, `"cancelled"`, `"errored"` |
| `result.total` | integer | Total URLs discovered |
| `result.finished` | integer | URLs in terminal state |
| `result.records` | array | URL records for this page |
| `result.records[].url` | string | Crawled URL |
| `result.records[].status` | string | URL status |
| `result.records[].markdown` | string\|null | Markdown content (if requested) |
| `result.records[].html` | string\|null | HTML content (if requested) |
| `result.records[].metadata` | object\|null | Page metadata |
| `result.cursor` | string\|null | Next page cursor (`null` when no more) |

### Errors

| Code | HTTP Status | Cause |
|------|-------------|-------|
| `JOB_NOT_FOUND` | 404 | Job ID does not exist |

### curl Example

```bash
# Check status (no records)
curl "http://localhost:8080/crawl?id=550e8400-e29b-41d4-a716-446655440000&limit=0"

# Get first page of results
curl "http://localhost:8080/crawl?id=550e8400-e29b-41d4-a716-446655440000&limit=10"

# Get next page
curl "http://localhost:8080/crawl?id=550e8400-e29b-41d4-a716-446655440000&limit=10&cursor=eyJpZCI6ICIxMjM0NTY3OCJ9"

# Get only completed records
curl "http://localhost:8080/crawl?id=550e8400-e29b-41d4-a716-446655440000&status=completed"
```

---

## 4. DELETE /crawl — Cancel Job

Cancel a running crawl job.

### Request

```
DELETE /crawl?id=<job-id>
```

**Query parameters**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Job ID to cancel |

### Response

**200 OK**:

```json
{
  "success": true,
  "result": "cancelled"
}
```

Idempotent — cancelling an already-terminal job returns success.

### Errors

| Code | HTTP Status | Cause |
|------|-------------|-------|
| `JOB_NOT_FOUND` | 404 | Job ID does not exist |

### curl Example

```bash
curl -X DELETE "http://localhost:8080/crawl?id=550e8400-e29b-41d4-a716-446655440000"
```

---

## 5. POST /markdown — Single-Page Markdown

Fetch a single page and return Markdown.

### Request

```
POST /markdown
Content-Type: application/json
```

**Body**:

```json
{
  "url": "https://docs.pydantic.dev/concepts/models",
  "render": false
}
```

**Parameters**:

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `url` | string | Yes* | — | URL to fetch |
| `html` | string | Yes* | — | Raw HTML to convert (alternative to `url`) |
| `render` | boolean | No | `false` | Use Playwright rendering |
| `goto_options.wait_until` | string | No | `"load"` | Page load strategy (render only) |
| `goto_options.timeout` | integer | No | 30000 | Navigation timeout in ms (render only) |
| `wait_for_selector` | string | No | — | CSS selector to wait for (render only) |
| `reject_resource_types` | string[] | No | — | Resource types to block (render only) |

\* Provide either `url` or `html`, not both.

### Response

**200 OK**:

```json
{
  "success": true,
  "result": "# Models\n\nPydantic models are the core building block of Pydantic.\nA model is a class that inherits from `BaseModel`..."
}
```

### Errors

| Code | HTTP Status | Cause |
|------|-------------|-------|
| `INVALID_INPUT` | 400 | Neither `url` nor `html` provided, or both provided |
| `FETCH_FAILED` | 502 | Network error or timeout |
| `NOT_FOUND` | 404 | HTTP 404 from target |
| `RENDER_FAILED` | 502 | Playwright error (when `render: true`) |

### curl Example

```bash
# Static fetch (fast)
curl -X POST http://localhost:8080/markdown \
  -H "Content-Type: application/json" \
  -d '{"url": "https://docs.pydantic.dev/concepts/models"}'

# With Playwright rendering (for JS-heavy pages)
curl -X POST http://localhost:8080/markdown \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://react.dev/learn",
    "render": true,
    "goto_options": {"wait_until": "networkidle0"},
    "reject_resource_types": ["image", "font", "stylesheet"]
  }'

# From raw HTML
curl -X POST http://localhost:8080/markdown \
  -H "Content-Type: application/json" \
  -d '{"html": "<html><body><h1>Title</h1><p>Content</p></body></html>"}'
```

---

## 6. POST /content — Single-Page HTML

Fetch a single page and return its HTML.

### Request

```
POST /content
Content-Type: application/json
```

**Body**: Same as `/markdown` (see Section 5).

### Response

**200 OK**:

```json
{
  "success": true,
  "result": "<!DOCTYPE html><html><head><title>Models - Pydantic</title></head><body>...</body></html>"
}
```

When `render: true`, the response includes the fully-rendered DOM after JavaScript execution (including `<head>`).

### Errors

Same as `/markdown` (see Section 5).

### curl Example

```bash
# Get raw HTML
curl -X POST http://localhost:8080/content \
  -H "Content-Type: application/json" \
  -d '{"url": "https://docs.pydantic.dev/concepts/models"}'

# Get rendered HTML (after JS execution)
curl -X POST http://localhost:8080/content \
  -H "Content-Type: application/json" \
  -d '{"url": "https://react.dev/learn", "render": true}'
```

---

## 7. POST /links — Extract Links

Extract all links from a page.

### Request

```
POST /links
Content-Type: application/json
```

**Body**:

```json
{
  "url": "https://docs.pydantic.dev/concepts/models",
  "render": false,
  "exclude_external_links": true
}
```

**Parameters**: All single-page base parameters (Section 5), plus:

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `visible_links_only` | boolean | No | `false` | Only visible links (render only) |
| `exclude_external_links` | boolean | No | `false` | Filter out cross-domain links |

### Response

**200 OK**:

```json
{
  "success": true,
  "result": [
    "https://docs.pydantic.dev/concepts/fields",
    "https://docs.pydantic.dev/concepts/validators",
    "https://docs.pydantic.dev/concepts/types",
    "https://docs.pydantic.dev/concepts/config"
  ]
}
```

### Errors

Same as `/markdown` (see Section 5).

### curl Example

```bash
# Get all links
curl -X POST http://localhost:8080/links \
  -H "Content-Type: application/json" \
  -d '{"url": "https://docs.pydantic.dev/concepts/models"}'

# Get only same-domain links
curl -X POST http://localhost:8080/links \
  -H "Content-Type: application/json" \
  -d '{"url": "https://docs.pydantic.dev/concepts/models", "exclude_external_links": true}'
```

---

## 8. POST /scrape — CSS Selector Extraction [v0.2]

Extract specific HTML elements using CSS selectors.

### Request

```
POST /scrape
Content-Type: application/json
```

**Body**:

```json
{
  "url": "https://docs.pydantic.dev/concepts/models",
  "render": true,
  "elements": [
    {"selector": "h1"},
    {"selector": "pre code"},
    {"selector": ".api-reference .method-name"}
  ]
}
```

**Parameters**: All single-page base parameters (Section 5), plus:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `elements` | array | Yes | CSS selectors: `[{"selector": "..."}]` |

### Response

**200 OK**:

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
    },
    {
      "selector": "pre code",
      "results": [
        {
          "text": "from pydantic import BaseModel\n\nclass User(BaseModel):\n    name: str",
          "html": "<code>from pydantic import BaseModel...</code>",
          "attributes": [{"name": "class", "value": "language-python"}],
          "width": 600,
          "height": 80,
          "top": 200,
          "left": 50
        }
      ]
    }
  ]
}
```

**Note**: `width`, `height`, `top`, `left` are only populated when `render: true`.

### Errors

| Code | HTTP Status | Cause |
|------|-------------|-------|
| `INVALID_INPUT` | 400 | Missing `elements` |
| `INVALID_SELECTOR` | 400 | Invalid CSS selector syntax |
| `FETCH_FAILED` | 502 | Network error |
| `RENDER_FAILED` | 502 | Playwright error |

---

## 9. POST /json — AI-Powered Extraction [v0.3]

Extract structured data using an AI model.

### Request

```
POST /json
Content-Type: application/json
```

**Body**:

```json
{
  "url": "https://docs.pydantic.dev/concepts/models",
  "prompt": "Extract all method names and their descriptions",
  "response_format": {
    "type": "json_schema",
    "schema": {
      "type": "object",
      "properties": {
        "methods": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "name": {"type": "string"},
              "description": {"type": "string"}
            }
          }
        }
      }
    }
  },
  "model": {
    "provider": "anthropic",
    "model": "claude-sonnet-4-20250514",
    "api_key": "sk-ant-..."
  }
}
```

**Parameters**: All single-page base parameters (Section 5), plus:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `prompt` | string | Yes* | Natural language extraction instruction |
| `response_format` | object | Yes* | JSON schema for output: `{"type": "json_schema", "schema": {...}}` |
| `model` | object | No | AI model config: `{"provider": "...", "model": "...", "api_key": "..."}` |

\* Provide `prompt`, `response_format`, or both.

### Response

**200 OK**:

```json
{
  "success": true,
  "result": {
    "methods": [
      {"name": "model_validate", "description": "Validate data against the model schema"},
      {"name": "model_dump", "description": "Serialize the model to a dictionary"}
    ]
  }
}
```

### Errors

| Code | HTTP Status | Cause |
|------|-------------|-------|
| `INVALID_INPUT` | 400 | Neither `prompt` nor `response_format` provided |
| `EXTRACTION_FAILED` | 502 | AI model error or invalid response |

---

## 10. POST /screenshot — Capture Screenshot [v0.3+]

Capture a page screenshot. Always uses Playwright.

### Request

```
POST /screenshot
Content-Type: application/json
```

**Body**:

```json
{
  "url": "https://docs.pydantic.dev/concepts/models",
  "screenshot_options": {
    "type": "png",
    "full_page": true
  },
  "viewport": {"width": 1920, "height": 1080}
}
```

**Parameters**: All single-page base parameters (Section 5, `render` is implicitly `true`), plus:

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `screenshot_options.type` | string | No | `"png"` | `"png"` or `"jpeg"` |
| `screenshot_options.quality` | integer | No | — | JPEG quality (0-100) |
| `screenshot_options.full_page` | boolean | No | `false` | Capture full scrollable page |
| `screenshot_options.clip` | object | No | — | Crop: `{x, y, width, height}` |
| `viewport` | object | No | `{width: 1920, height: 1080}` | Browser viewport |
| `selector` | string | No | — | Capture only this element |

### Response

**200 OK**: Binary image data (PNG or JPEG).

```
Content-Type: image/png
```

### curl Example

```bash
# Full-page screenshot
curl -X POST http://localhost:8080/screenshot \
  -H "Content-Type: application/json" \
  -d '{"url": "https://docs.pydantic.dev", "screenshot_options": {"full_page": true}}' \
  --output screenshot.png

# Element screenshot
curl -X POST http://localhost:8080/screenshot \
  -H "Content-Type: application/json" \
  -d '{"url": "https://docs.pydantic.dev", "selector": ".hero"}' \
  --output hero.png
```

---

## 11. POST /pdf — Render PDF [v0.3+]

Render a page as PDF. Always uses Playwright.

### Request

```
POST /pdf
Content-Type: application/json
```

**Body**:

```json
{
  "url": "https://docs.pydantic.dev/concepts/models",
  "pdf_options": {
    "format": "a4",
    "print_background": true,
    "margin": {"top": "1cm", "bottom": "1cm", "left": "1cm", "right": "1cm"}
  }
}
```

**Parameters**: All single-page base parameters (Section 5, `render` is implicitly `true`), plus:

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `pdf_options.format` | string | No | `"a4"` | Paper size |
| `pdf_options.landscape` | boolean | No | `false` | Landscape orientation |
| `pdf_options.scale` | number | No | 1.0 | Zoom level |
| `pdf_options.print_background` | boolean | No | `false` | Include background |
| `pdf_options.margin` | object | No | — | `{top, bottom, left, right}` |
| `pdf_options.display_header_footer` | boolean | No | `false` | Show header/footer |
| `pdf_options.header_template` | string | No | — | HTML header template |
| `pdf_options.footer_template` | string | No | — | HTML footer template |

### Response

**200 OK**: Binary PDF data.

```
Content-Type: application/pdf
```

### curl Example

```bash
curl -X POST http://localhost:8080/pdf \
  -H "Content-Type: application/json" \
  -d '{"url": "https://docs.pydantic.dev/concepts/models", "pdf_options": {"format": "a4"}}' \
  --output page.pdf
```

---

## 12. POST /snapshot — MHTML Snapshot [v0.3+]

Take an MHTML snapshot of a page. Always uses Playwright.

### Request

```
POST /snapshot
Content-Type: application/json
```

**Body**:

```json
{
  "url": "https://docs.pydantic.dev/concepts/models"
}
```

**Parameters**: Single-page base parameters (Section 5, `render` is implicitly `true`).

### Response

**200 OK**: Binary MHTML data.

```
Content-Type: multipart/related
```

### curl Example

```bash
curl -X POST http://localhost:8080/snapshot \
  -H "Content-Type: application/json" \
  -d '{"url": "https://docs.pydantic.dev/concepts/models"}' \
  --output page.mhtml
```

---

## 13. Python API Reference

### 13.1 Crawler Class

```python
from proctx_crawler import Crawler

async with Crawler(
    output_dir=Path("./output"),   # optional, default: platform data dir
    db_path=Path("./crawler.db"),  # optional, default: platform data dir
) as crawler:
    ...
```

The `Crawler` is an async context manager. It initialises the database and content storage on enter, and closes connections on exit.

### 13.2 crawl()

```python
result = await crawler.crawl(
    url="https://docs.pydantic.dev/llms.txt",
    limit=50,                          # default: 10
    depth=1000,                        # default: 1000
    source="llms_txt",                 # default: "links"
    formats=["markdown"],              # default: ["markdown"]
    render=False,                      # default: False
    options={                          # default: no filtering
        "include_patterns": ["https://docs.pydantic.dev/**"],
        "exclude_patterns": ["https://docs.pydantic.dev/blog/**"],
    },
)

# result.status -> "completed"
# result.total -> 50
# result.finished -> 50
# result.records -> list[CrawlRecord]

for record in result.records:
    print(record.url)
    print(record.markdown[:200])
```

**Signature**:

```python
async def crawl(
    self,
    url: str,
    *,
    limit: int = 10,
    depth: int = 1000,
    source: Literal["links", "llms_txt", "sitemaps", "all"] = "links",
    formats: list[Literal["markdown", "html"]] | None = None,
    render: bool = False,
    goto_options: dict | None = None,
    wait_for_selector: str | None = None,
    reject_resource_types: list[str] | None = None,
    options: dict | None = None,
) -> CrawlResult:
```

**Behaviour**: Blocks until the crawl is complete. For non-blocking crawls, wrap in `anyio.create_task_group()`.

**Raises**: `CrawlerError` subclasses for job-level failures.

### 13.3 markdown()

```python
md = await crawler.markdown(
    "https://docs.pydantic.dev/concepts/models",
    render=False,
)
print(md)  # "# Models\n\nPydantic models are..."
```

**Signature**:

```python
async def markdown(
    self,
    url: str,
    *,
    render: bool = False,
    goto_options: dict | None = None,
    wait_for_selector: str | None = None,
    reject_resource_types: list[str] | None = None,
) -> str:
```

**Returns**: Markdown string.

**Raises**: `FetchError`, `RenderError`.

### 13.4 content()

```python
html = await crawler.content(
    "https://docs.pydantic.dev/concepts/models",
    render=True,
)
print(html)  # "<!DOCTYPE html><html>..."
```

**Signature**: Same as `markdown()`.

**Returns**: HTML string.

### 13.5 links()

```python
urls = await crawler.links(
    "https://docs.pydantic.dev/concepts/models",
    exclude_external_links=True,
)
for url in urls:
    print(url)
```

**Signature**:

```python
async def links(
    self,
    url: str,
    *,
    render: bool = False,
    visible_links_only: bool = False,
    exclude_external_links: bool = False,
    goto_options: dict | None = None,
    wait_for_selector: str | None = None,
    reject_resource_types: list[str] | None = None,
) -> list[str]:
```

**Returns**: List of absolute URL strings.

### 13.6 Result Types

```python
from proctx_crawler.models import CrawlResult, CrawlRecord, RecordMetadata

class CrawlResult:
    id: str                        # Job ID
    status: str                    # "completed", "cancelled", "errored"
    total: int                     # Total URLs discovered
    finished: int                  # URLs in terminal state
    records: list[CrawlRecord]    # All URL records
    cursor: str | None             # Pagination cursor (None when complete)

class CrawlRecord:
    url: str                       # Crawled URL
    status: str                    # "completed", "errored", "skipped", etc.
    markdown: str | None           # Markdown content (if requested)
    html: str | None               # HTML content (if requested)
    metadata: RecordMetadata | None

class RecordMetadata:
    http_status: int               # HTTP response code
    title: str | None              # Page title
    content_hash: str | None       # SHA-256 of content
```

---

## 14. CLI Reference

### 14.1 crawl

```bash
proctx-crawler crawl <url> [options]
```

Start a multi-page crawl and save results to disk.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `<url>` | positional | required | Starting URL |
| `--limit N` | int | 10 | Max pages to crawl |
| `--depth N` | int | 1000 | Max link depth |
| `--source MODE` | str | `links` | Discovery: `links`, `llms_txt` |
| `--format FMT` | str | `markdown` | Output format (repeatable) |
| `--render` | flag | false | Enable Playwright |
| `--include PATTERN` | str | — | Include pattern (repeatable) |
| `--exclude PATTERN` | str | — | Exclude pattern (repeatable) |
| `--output DIR` | path | platform default | Output directory |
| `--quiet` | flag | false | Suppress progress |

**Example**:

```bash
# Crawl pydantic docs via llms.txt
proctx-crawler crawl https://docs.pydantic.dev/llms.txt \
  --source llms_txt --limit 50 --format markdown

# Crawl with URL filtering
proctx-crawler crawl https://fastapi.tiangolo.com/tutorial/ \
  --include "https://fastapi.tiangolo.com/tutorial/**" \
  --exclude "https://fastapi.tiangolo.com/tutorial/bigger-applications/**" \
  --limit 30

# Crawl with Playwright (JS-heavy site)
proctx-crawler crawl https://react.dev/learn --render --limit 20
```

**Output**: Progress to stderr, output directory path to stdout on completion.

### 14.2 markdown

```bash
proctx-crawler markdown <url> [options]
```

Extract Markdown from a single page.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `<url>` | positional | required | Target URL |
| `--render` | flag | false | Enable Playwright |
| `--output FILE` | path | stdout | Write to file |

**Example**:

```bash
# Print Markdown to stdout
proctx-crawler markdown https://docs.pydantic.dev/concepts/models

# Save to file
proctx-crawler markdown https://docs.pydantic.dev/concepts/models --output models.md

# Pipe to another tool
proctx-crawler markdown https://docs.pydantic.dev/concepts/models | wc -l
```

### 14.3 content

```bash
proctx-crawler content <url> [options]
```

Fetch HTML from a single page.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `<url>` | positional | required | Target URL |
| `--render` | flag | false | Enable Playwright |
| `--output FILE` | path | stdout | Write to file |

**Example**:

```bash
proctx-crawler content https://docs.pydantic.dev/concepts/models --output page.html
```

### 14.4 links

```bash
proctx-crawler links <url> [options]
```

Extract links from a single page.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `<url>` | positional | required | Target URL |
| `--render` | flag | false | Enable Playwright |
| `--external` | flag | false | Include external links |

**Example**:

```bash
# List all internal links
proctx-crawler links https://docs.pydantic.dev/concepts/models

# Include external links
proctx-crawler links https://docs.pydantic.dev/concepts/models --external
```

**Output**: One URL per line to stdout.

### 14.5 serve

```bash
proctx-crawler serve [options]
```

Start the HTTP API server.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--host HOST` | str | `127.0.0.1` | Bind address |
| `--port PORT` | int | `8080` | Bind port |

**Example**:

```bash
# Start on default port
proctx-crawler serve

# Start on custom port
proctx-crawler serve --port 3000 --host 0.0.0.0
```

---

## 15. Error Reference

### Error Codes

| Code | HTTP Status | Recoverable | Description | Applicable Endpoints |
|------|-------------|-------------|-------------|---------------------|
| `INVALID_INPUT` | 400 | No | Input validation failed. Missing required fields, invalid URL, conflicting parameters. | All |
| `FETCH_FAILED` | 502 | Yes | Network error, connection timeout, or non-success HTTP status from the target URL. | `/markdown`, `/content`, `/links`, `/scrape`, `/crawl` |
| `NOT_FOUND` | 404 | No | Target URL returned HTTP 404. | `/markdown`, `/content`, `/links`, `/scrape` |
| `JOB_NOT_FOUND` | 404 | No | The specified job ID does not exist in the database. | `GET /crawl`, `DELETE /crawl` |
| `RENDER_FAILED` | 502 | Yes | Playwright rendering failed: browser crash, navigation timeout, or page error. Only occurs when `render: true`. | Any (when render enabled) |
| `INVALID_SELECTOR` | 400 | No | Invalid CSS selector syntax in `elements` or `wait_for_selector`. | `/scrape`, any with `wait_for_selector` |
| `DISALLOWED` | 403 | No | URL blocked by robots.txt. [v0.2] | `/crawl` |
| `EXTRACTION_FAILED` | 502 | Yes | AI model returned an error or invalid response. [v0.3] | `/json` |

### HTTP Status Mapping

| HTTP Status | Meaning |
|-------------|---------|
| 200 | Success |
| 400 | Client error (invalid input, bad selector) |
| 401 | Unauthorized (missing or invalid API key) |
| 403 | Forbidden (robots.txt disallowed) |
| 404 | Not found (job or target page) |
| 502 | Upstream error (fetch/render/extraction failed) |
| 500 | Internal server error (unexpected) |
