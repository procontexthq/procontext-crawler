# Cloudflare Browser Rendering — Endpoint Details

> **Source**: [developers.cloudflare.com/browser-rendering/rest-api](https://developers.cloudflare.com/browser-rendering/rest-api/)
> **Captured**: 2026-03-15
> **Purpose**: Detailed parameter reference for each endpoint. Used to inform ProContext Crawler API design.

---

## 1. `/content` — Fetch Rendered HTML

**POST** `/accounts/<id>/browser-rendering/content`

Returns fully-rendered HTML after JavaScript execution (includes `<head>`).

**Input**: `url` or `html` (required, pick one) + shared params.

**Response**:
```json
{
  "success": true,
  "result": "<html>...</html>"
}
```

**Notes**: For SPAs, use `gotoOptions.waitUntil: "networkidle0"`.

---

## 2. `/markdown` — Extract Markdown

**POST** `/accounts/<id>/browser-rendering/markdown`

Renders the page, then converts HTML to Markdown.

**Input**: `url` or `html` (required) + shared params.

**Response**:
```json
{
  "success": true,
  "result": "# Page Title\n\nContent..."
}
```

**Notes**: JS-heavy pages may return incomplete results without `waitUntil` or `waitForSelector`.

---

## 3. `/screenshot` — Capture Screenshot

**POST** `/accounts/<id>/browser-rendering/screenshot`

Returns binary image (PNG by default, JPEG optional).

**Endpoint-specific params**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `screenshotOptions.omitBackground` | boolean | Transparent background |
| `screenshotOptions.quality` | number | JPEG quality (incompatible with PNG) |
| `screenshotOptions.type` | string | `png` or `jpeg` |
| `screenshotOptions.fullPage` | boolean | Capture full scrollable page |
| `screenshotOptions.clip` | object | `{x, y, width, height}` crop region |
| `screenshotOptions.captureBeyondViewport` | boolean | Capture beyond visible area |
| `selector` | string | CSS selector — capture specific element only |
| `viewport` | object | `{width, height, deviceScaleFactor}` (default: 1920x1080) |

**Response**: Binary PNG/JPEG data.

---

## 4. `/pdf` — Render PDF

**POST** `/accounts/<id>/browser-rendering/pdf`

Returns binary PDF.

**Endpoint-specific params**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `pdfOptions.format` | string | Paper size: `a4`, `a5`, `letter`, etc. |
| `pdfOptions.landscape` | boolean | Landscape orientation |
| `pdfOptions.scale` | number | Zoom level |
| `pdfOptions.printBackground` | boolean | Include background colors/images |
| `pdfOptions.preferCSSPageSize` | boolean | Use CSS `@page` dimensions |
| `pdfOptions.displayHeaderFooter` | boolean | Show header/footer |
| `pdfOptions.headerTemplate` | string | HTML with `<span class="date/title/pageNumber/totalPages">` |
| `pdfOptions.footerTemplate` | string | Same placeholders as header |
| `pdfOptions.margin` | object | `{top, bottom, left, right}` |
| `pdfOptions.timeout` | number | Generation timeout (ms) |

**Constraint**: Max request body 50 MB.

**Response**: Binary PDF data.

---

## 5. `/scrape` — Extract HTML Elements

**POST** `/accounts/<id>/browser-rendering/scrape`

Extract specific elements by CSS selector.

**Endpoint-specific params**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `elements` | array | Required. Each entry: `{selector: "CSS selector"}` |

**Response**:
```json
{
  "success": true,
  "result": [
    {
      "selector": "h1",
      "results": [
        {
          "text": "Page Title",
          "html": "<h1>Page Title</h1>",
          "attributes": [{"name": "class", "value": "title"}],
          "height": 40,
          "width": 800,
          "top": 10,
          "left": 0
        }
      ]
    }
  ]
}
```

Each matched element includes: `text`, `html`, `attributes` (name/value pairs), `height`, `width`, `top`, `left`.

---

## 6. `/json` — AI-Powered Structured Extraction

**POST** `/accounts/<id>/browser-rendering/json`

Uses AI (Workers AI by default) to extract structured data from page content.

**Endpoint-specific params**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `prompt` | string | Natural language extraction instruction |
| `response_format` | object | JSON schema: `{type: "json_schema", schema: {...}}` |
| `custom_ai` | array | Override AI model: `[{model: "provider/name", authorization: "Bearer ..."}]` |

Must provide either `prompt` or `response_format` (or both).

**Response**:
```json
{
  "success": true,
  "result": {
    "title": "Product Name",
    "price": "$29.99"
  }
}
```

**Notes**: Supports custom models (Anthropic, OpenAI, etc.) via `custom_ai` with automatic failover.

---

## 7. `/links` — Extract Links

**POST** `/accounts/<id>/browser-rendering/links`

Returns all links found on the page.

**Endpoint-specific params**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `visibleLinksOnly` | boolean | `false` | Only return visible links |
| `excludeExternalLinks` | boolean | `false` | Filter out cross-domain links |

**Response**:
```json
{
  "success": true,
  "result": [
    "https://example.com/page1",
    "https://example.com/page2"
  ]
}
```

---

## 8. `/snapshot` — Webpage Snapshot

**POST** `/accounts/<id>/browser-rendering/snapshot`

Takes an MHTML snapshot of the page (single-file archive with all resources embedded).

**Documentation**: 404 at time of capture. Likely same shared params as other endpoints.

**Response**: Binary MHTML data.

---

## 9. `/crawl` — Multi-Page Async Crawl

**POST** `/accounts/<id>/browser-rendering/crawl` — Start job
**GET** `/accounts/<id>/browser-rendering/crawl?id=<jobId>` — Poll status / get results
**DELETE** `/accounts/<id>/browser-rendering/crawl?id=<jobId>` — Cancel job

The only async, multi-page endpoint. All others are synchronous, single-page.

### POST — Start Crawl

**Required**: `url` (string)

**Crawl-specific params**:

| Parameter | Type | Default | Max | Description |
|-----------|------|---------|-----|-------------|
| `limit` | number | 10 | 100,000 | Max pages to crawl |
| `depth` | number | 100,000 | 100,000 | Max link hops from start URL |
| `source` | string | `"all"` | — | URL discovery: `"all"`, `"sitemaps"`, `"links"` |
| `formats` | array | `["HTML"]` | — | Output: `"HTML"`, `"Markdown"`, `"JSON"` |
| `render` | boolean | `true` | — | Execute JS. `false` = fast fetch, no browser |
| `maxAge` | number | 86,400 | 604,800 | Cache TTL in seconds |
| `modifiedSince` | number | — | — | Unix timestamp — skip unmodified pages |

**URL filtering** (under `options`):

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `includeExternalLinks` | boolean | `false` | Follow cross-domain links |
| `includeSubdomains` | boolean | `false` | Follow subdomain links |
| `includePatterns` | array | — | Wildcard URL patterns to include |
| `excludePatterns` | array | — | Wildcard URL patterns to exclude (overrides include) |

**Pattern rules**: `*` matches any char except `/`. `**` matches including `/`. Exclude always wins over include.

**AI extraction** (when `"JSON"` in formats):

| Parameter | Type | Description |
|-----------|------|-------------|
| `jsonOptions.prompt` | string | Natural language extraction instruction |
| `jsonOptions.response_format` | object | JSON schema for structured output |
| `jsonOptions.custom_ai` | array | Custom AI model config |

**POST Response**:
```json
{
  "success": true,
  "result": "job-uuid"
}
```

### GET — Poll / Retrieve Results

**Query params**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | string | Job ID (required) |
| `limit` | number | Max records to return |
| `cursor` | number | Pagination token (for responses > 10 MB) |
| `status` | string | Filter by URL status |

**Job status values**: `running`, `completed`, `cancelled_due_to_timeout`, `cancelled_due_to_limits`, `cancelled_by_user`, `errored`

**URL record status values**: `queued`, `completed`, `disallowed`, `skipped`, `errored`, `cancelled`

**GET Response**:
```json
{
  "success": true,
  "result": {
    "id": "job-uuid",
    "status": "completed",
    "browserSecondsUsed": 134.7,
    "total": 50,
    "finished": 50,
    "records": [
      {
        "url": "https://example.com/page",
        "status": "completed",
        "markdown": "# Content...",
        "html": "<html>...</html>",
        "json": {},
        "metadata": {
          "status": 200,
          "title": "Page Title",
          "url": "https://example.com/page"
        }
      }
    ],
    "cursor": 10
  }
}
```

### DELETE — Cancel Job

Returns 200 OK. All queued (not yet started) URLs are cancelled.

### URL Discovery Order (source: "all")

1. Starting URL
2. Sitemap links (`sitemap.xml`)
3. Links scraped from pages (only if not already found via sitemap)

### robots.txt Behavior

- Respects `robots.txt` directives including `crawl-delay`
- Disallowed URLs get `status: "disallowed"` in results
- User-Agent: `CloudflareBrowserRenderingCrawler/1.0` (fixed, not customizable)
- Blocked by CAPTCHA, Turnstile, Bot Management, WAF
- For owned sites: create WAF skip rule to allowlist

### render: false Optimization

- Skips browser entirely — fast HTML fetch on Workers runtime
- Currently unbilled (beta); Workers pricing after beta
- Cannot use browser-specific features (waitForSelector, JS execution)
- Ideal for static documentation sites
