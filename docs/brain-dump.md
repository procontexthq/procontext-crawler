# Brain Dump

Living document capturing design discussions, ideas, and decisions as they happen.

---

## 2026-03-15 — Initial Design Discussion

### What is this?

An independent, self-hosted crawl library/service. Given a URL, it discovers all linked pages (up to a configurable depth), fetches them, and outputs clean Markdown/HTML. Built for RAG pipelines and documentation extraction, but not tied to any specific consumer.

### Core Identity

- **Independent library** — not an extension of ProContext. Can be used by anyone for any crawl-and-extract use case.
- **Speed is a priority** — most documentation pages are static or SSR'd. Default to fast httpx fetches. Playwright is opt-in or auto-fallback for JS-heavy pages.
- **File-based content storage** — crawled pages land on disk as individual files. Inspectable, exportable, git-friendly, easy to pipe into RAG pipelines.
- **DB for metadata only** — job state, URL queue, crawl history. Behind a `Repository` abstraction so the backing store (SQLite → Postgres → whatever) can be swapped without touching business logic.

### Inspiration

Cloudflare's [Browser Rendering /crawl API](https://developers.cloudflare.com/browser-rendering/rest-api/crawl-endpoint/) — async job model (POST/GET/DELETE), configurable depth/limits, multiple output formats, optional JS rendering.

### Key Design Decisions

**D1: Static-first, Playwright-second**
Playwright is 10-50x slower than httpx. Default to static fetch. Two strategies for when to use Playwright:
- Explicit opt-in (`render: true` on the crawl request)
- Auto-detect: if static fetch returns a JS-shell page (minimal HTML, no real content), auto-retry with Playwright

This keeps the 80% case (static/SSR pages) fast while handling SPAs when needed.

**D2: File-based content, DB-backed metadata**
Content goes to disk: `<output_dir>/<job_id>/<url_hash>.md` (and `.html` if requested). The DB tracks which URLs were crawled, their status, and job-level metadata. This separation means:
- Content is trivially consumable (point a RAG pipeline at a directory)
- DB can be swapped without migrating content
- Large crawls don't bloat a database

**D3: llms.txt as a feature, not the core**
llms.txt is a URL discovery strategy — an alternative to HTML link following. When the starting URL is an llms.txt file (or the user enables llms.txt mode), the crawler parses it to extract documentation links rather than parsing HTML `<a>` tags. It's a first-class feature, but the crawler works with any URL.

**D4: Repository pattern for DB abstraction**
Define a `Repository` protocol: `save_job`, `get_job`, `enqueue_urls`, `mark_url_complete`, `get_job_results`, etc. Start with SQLite. The abstraction exists from day one so we never couple business logic to a specific database.

### Ideas / Future Thinking

- **Auto-detect rendering need**: Fetch static first. If the response body is < N bytes and contains common JS loader patterns (`<div id="root"></div>`, `__NEXT_DATA__` without content), re-fetch with Playwright. Could save significant time on mixed-content sites.
- **Streaming results**: Instead of waiting for the full crawl to complete, stream results as pages are crawled (SSE or WebSocket). Useful for large crawls.
- **Export formats**: Zip/tar download of crawled content. Useful for offline RAG ingestion.
- **Pluggable extractors**: Let users bring their own HTML-to-Markdown pipeline. Different doc sites have different structures.
- **ProContext integration**: Eventually, ProContext could call this service to pre-crawl library docs. But that's a consumer decision, not a crawler decision.
- **Concurrency tuning**: Per-domain rate limiting and global concurrency caps. Don't hammer documentation sites.
- **Incremental crawling**: Only re-crawl pages that changed since last crawl (ETags, Last-Modified, content hashing).

### Resolved Questions

- **Q1**: Should the library also work as a pure Python API? **Yes** — library-first, server-second (Design Decision D8 in functional spec). `Crawler` class is the primary interface.
- **Q2**: How do we handle authentication for gated docs? **v0.2** — custom headers, cookies, HTTP Basic Auth. Out of scope for v0.1.
- **Q3**: robots.txt — respect by default or opt-in? **v0.2** — respect by default, with `respect_robots_txt: false` flag to override.
- **Q4**: Should we support non-documentation sites? **Build for docs, don't prevent general use.** Extractors prefer `<main>`/`<article>` content, but work on any HTML.

---

## 2026-03-15 — Cloudflare Research & Surface Area

### Research Documents

Full Cloudflare API research is in `docs/research/`:
- `cloudflare-api-overview.md` — high-level summary of all 9 endpoints, shared params, limits
- `cloudflare-endpoint-details.md` — per-endpoint parameter reference
- `cloudflare-analysis.md` — adopt/adapt/skip analysis, feature mapping, what we learn from CF

### Revised Surface Area (post-research)

Based on the Cloudflare research, here's the refined scope by tier.

**Cloudflare has 9 endpoints.** We adopt 4, skip 5:
- Adopt: `/crawl`, `/markdown`, `/content`, `/links`
- Skip: `/screenshot`, `/pdf`, `/snapshot`, `/scrape`, `/json`

#### Tier 1 — v0.1 (Core)

**Endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/crawl` | POST | Start async crawl job |
| `/crawl` | GET | Poll status, retrieve results |
| `/crawl` | DELETE | Cancel a running job |
| `/markdown` | POST | Single-page Markdown extraction |
| `/content` | POST | Single-page rendered HTML |
| `/links` | POST | Extract links from a page |

**Crawl params:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `url` | required | Starting URL |
| `limit` | 10 | Max pages to crawl |
| `depth` | 10 | Max link hops from start |
| `source` | `"links"` | URL discovery: `"links"`, `"llms_txt"`, `"sitemaps"`, `"all"` |
| `formats` | `["markdown"]` | Output: `"markdown"`, `"html"` |
| `render` | `false` | Playwright rendering (opt-in) |
| `options.includePatterns` | — | Wildcard URL include patterns |
| `options.excludePatterns` | — | Wildcard URL exclude patterns (wins over include) |
| `options.includeSubdomains` | `false` | Follow subdomain links |
| `options.includeExternalLinks` | `false` | Follow cross-domain links |

**Shared single-page params** (for `/markdown`, `/content`, `/links`):

| Parameter | Description |
|-----------|-------------|
| `url` | Target URL (required) |
| `render` | Playwright rendering (default: `false`) |
| `gotoOptions` | `{waitUntil, timeout}` for Playwright navigation |
| `waitForSelector` | CSS selector to wait for before extracting |
| `rejectResourceTypes` | Block images, media, fonts, stylesheets |

**Rendering params** (only apply when `render: true`):

| Parameter | Description |
|-----------|-------------|
| `gotoOptions.waitUntil` | `"networkidle0"`, `"networkidle2"`, `"domcontentloaded"`, `"load"` |
| `gotoOptions.timeout` | Navigation timeout (ms) |
| `waitForSelector` | Wait for CSS selector before extracting |
| `rejectResourceTypes` | Block resource types for speed |

**Job lifecycle:**
- POST returns job ID immediately
- GET polls status: `queued`, `running`, `completed`, `cancelled`, `errored`
- GET returns paginated results (cursor-based)
- DELETE cancels queued URLs
- URL record status: `queued`, `completed`, `errored`, `skipped`

**Output:**
- File-based: `<output_dir>/<job_id>/<url_hash>.md` and/or `.html`
- DB tracks job state + URL queue (Repository pattern, SQLite)
- API returns results in JSON (same shape as Cloudflare)

**Interfaces:**
- HTTP API (FastAPI)
- Python API: `crawler = Crawler(); results = await crawler.crawl(url, depth=2)`
- CLI: `proctx-crawler crawl <url> --depth 2 --format markdown`

#### Tier 2 — v0.2

| Feature | Description |
|---------|-------------|
| Auto-detect JS rendering | Static fetch → detect JS shell → auto-retry with Playwright |
| robots.txt compliance | Respect by default, flag to override |
| Per-domain rate limiting | Configurable delay between requests to same host |
| Authentication to targets | `authenticate`, `cookies`, `setExtraHTTPHeaders` |
| Caching / deduplication | Skip pages crawled within a TTL (`maxAge`) |
| `/scrape` endpoint | CSS selector-based element extraction |
| Metadata extraction | Title, canonical URL, HTTP status, content hash per page |
| Incremental crawling | `modifiedSince` — skip unmodified pages |

#### Tier 3 — v0.3+

| Feature | Description |
|---------|-------------|
| `/json` endpoint | AI-powered structured extraction (needs LLM backend) |
| Streaming results | SSE for real-time crawl progress |
| Export | Zip/tar download of crawl output |
| Webhook callbacks | Notify on job completion |
| Request pattern filtering | `rejectRequestPattern`, `allowRequestPattern` |
| Pluggable extractors | Custom HTML-to-Markdown pipelines |
| Distributed crawling | Multiple workers for large-scale crawls |

### Key Learnings from Cloudflare

1. **`render: false` is the speed lever** — we default to `false` (opposite of CF which defaults `true`) because our primary audience is doc sites which are mostly static/SSR.
2. **Shared params across endpoints** — reduces API surface. Our `/markdown`, `/content`, `/links` share the same base params.
3. **Exclude always wins over include** — copy CF's pattern precedence exactly. No ambiguity.
4. **Separate job status from URL status** — a job can be `completed` even if individual URLs errored.
5. **Cursor-based pagination** — better than offset for growing result sets during active crawls.
6. **`rejectResourceTypes`** — blocking images/media/fonts is a massive speedup for Playwright. Easy win.

### Where We Differ from Cloudflare

1. **Default `render: false`** — CF defaults true (they own the browser fleet). We default false (speed-first for docs).
2. **`source: "llms_txt"`** — CF doesn't know about llms.txt. This is our differentiator.
3. **File-based output** — CF returns JSON blobs. We write files to disk.
4. **Python-native API** — CF is REST-only. We're a library first, server second.
5. **CLI** — one-off crawls without spinning up a server.
6. **Self-hosted** — no vendor lock-in, no usage limits, no billing.
