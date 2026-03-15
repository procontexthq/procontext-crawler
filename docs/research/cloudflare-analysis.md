# Cloudflare Browser Rendering — Analysis for ProContext Crawler

> **Purpose**: Map Cloudflare's feature set to our design. What do we adopt, adapt, or skip?
> **Date**: 2026-03-15

---

## Endpoint Mapping

Cloudflare has 9 endpoints. Here's how each maps to our use case.

### Adopt (build our version)

| CF Endpoint | Our Version | Rationale |
|-------------|-------------|-----------|
| `/crawl` | `/crawl` | Core feature. Async job-based multi-page crawl. This is the whole point. |
| `/markdown` | `/markdown` | Single-page Markdown extraction. Useful standalone and as a building block for `/crawl`. |
| `/content` | `/content` | Single-page rendered HTML fetch. Foundation for everything else. |
| `/links` | `/links` | Link extraction from a page. Useful standalone, and it's how the crawler discovers URLs. |

### Adapt (build differently)

| CF Endpoint | Our Approach | Rationale |
|-------------|--------------|-----------|
| `/scrape` | Skip for v0.1, maybe v0.2 | CSS selector extraction is useful but not core to our doc-crawling use case. Can add later. |
| `/json` | Skip for v0.1, maybe v0.3 | AI-powered extraction requires an LLM backend. Out of scope initially. Could be powerful later for structured doc extraction. |

### Skip (not in scope)

| CF Endpoint | Reason |
|-------------|--------|
| `/screenshot` | Not relevant to documentation extraction or RAG. |
| `/pdf` | Not relevant. If someone needs PDFs, they can use other tools. |
| `/snapshot` | MHTML snapshots — niche use case, not worth the complexity. |

---

## Feature-by-Feature Analysis

### Crawl Configuration

| CF Feature | Adopt? | Notes |
|------------|--------|-------|
| `limit` (max pages) | **Yes** | Essential. Default 10, configurable. |
| `depth` (max link hops) | **Yes** | Essential. |
| `source` (`all`/`sitemaps`/`links`) | **Adapt** | We add a fourth source: `llms_txt`. So our options: `all`, `sitemaps`, `links`, `llms_txt`. |
| `formats` (HTML/Markdown/JSON) | **Partial** | HTML + Markdown for v0.1. JSON (AI-powered) later. |
| `render` (boolean) | **Yes** | Static-first, Playwright opt-in. Key speed lever. |
| `maxAge` (cache TTL) | **Later** | Nice to have but not v0.1. We're file-based, caching is simpler. |
| `modifiedSince` | **Later** | Incremental crawling — v0.2 or v0.3. |

### URL Filtering

| CF Feature | Adopt? | Notes |
|------------|--------|-------|
| `includePatterns` | **Yes** | Wildcard URL patterns. Essential for scoping crawls. |
| `excludePatterns` | **Yes** | Exclude always wins over include (same as CF). |
| `includeSubdomains` | **Yes** | Default false. |
| `includeExternalLinks` | **Yes** | Default false. Important safety default. |
| Pattern syntax (`*` vs `**`) | **Yes** | Same semantics: `*` = any except `/`, `**` = any including `/`. |

### Rendering & Navigation

| CF Feature | Adopt? | Notes |
|------------|--------|-------|
| `gotoOptions.waitUntil` | **Yes** | `networkidle0`, `networkidle2`, `domcontentloaded`, `load`. |
| `gotoOptions.timeout` | **Yes** | Navigation timeout. |
| `waitForSelector` | **Yes** | Wait for specific element before extracting. Critical for SPAs. |
| `rejectResourceTypes` | **Yes** | Block images, media, fonts, stylesheets for speed. |
| `rejectRequestPattern` | **Later** | Regex-based request blocking. Nice but not essential for v0.1. |
| `allowResourceTypes` | **Later** | Inverse of reject. |
| `allowRequestPattern` | **Later** | Inverse of reject. |
| `addScriptTag` | **No** | Injecting JS — too niche for a docs crawler. |
| `addStyleTag` | **No** | Injecting CSS — irrelevant for content extraction. |
| `viewport` | **Later** | Default viewport is fine for content extraction. |

### Authentication

| CF Feature | Adopt? | Notes |
|------------|--------|-------|
| `authenticate` (HTTP Basic) | **v0.2** | Some doc sites are gated. |
| `cookies` | **v0.2** | Token-based auth for gated docs. |
| `setExtraHTTPHeaders` | **v0.2** | Custom headers (API keys, auth tokens). |

### Job Lifecycle

| CF Feature | Adopt? | Notes |
|------------|--------|-------|
| POST to start → job ID | **Yes** | Async is the right model for crawling. |
| GET to poll status/results | **Yes** | With pagination for large result sets. |
| DELETE to cancel | **Yes** | Cancel queued URLs, stop crawl. |
| Job status states | **Yes** | `running`, `completed`, `cancelled`, `errored`. Simplify CF's 5 cancellation sub-states. |
| URL record statuses | **Yes** | `queued`, `completed`, `errored`, `skipped`. Drop `disallowed` (we don't do robots.txt in v0.1). |
| Results retention (14 days) | **Adapt** | File-based — results persist until deleted. No auto-expiry needed. |
| 7-day max runtime | **Adopt** | Configurable timeout to prevent zombie jobs. |

### robots.txt

| CF Feature | Adopt? | Notes |
|------------|--------|-------|
| Respect by default | **v0.2** | Good citizenship, but not blocking for v0.1 which targets owned/public doc sites. |
| `crawl-delay` | **v0.2** | Part of robots.txt compliance. |
| Disallowed status | **v0.2** | When we add robots.txt support. |

---

## Key Differences from Cloudflare

| Aspect | Cloudflare | ProContext Crawler |
|--------|-----------|-------------------|
| **Hosting** | Cloudflare's edge network | Self-hosted (local or server) |
| **Browser** | Managed Chrome fleet | Local Playwright (user installs) |
| **Storage** | Cloudflare's infra, 14-day retention | Local filesystem, persists until deleted |
| **Metadata DB** | Cloudflare-managed | SQLite (swappable via Repository pattern) |
| **AI extraction** | Workers AI built-in | Out of scope for v0.1 |
| **llms.txt** | Not supported | First-class URL discovery source |
| **Python API** | N/A (REST only) | Usable as a library, no server needed |
| **CLI** | N/A | `proctx-crawler crawl <url>` for one-off use |
| **Pricing** | Pay-per-use | Free (self-hosted) |
| **Auth to crawler** | CF API token | Optional API key (for HTTP server mode) |
| **Auth to targets** | HTTP Basic, cookies, headers | Same — v0.2 |

---

## What Cloudflare Does Well (learn from)

1. **`render: false` as the speed lever** — a single boolean that skips the entire browser. Simple, effective. We should do exactly this.
2. **Shared parameter set** — all single-page endpoints share the same base params (url/html, auth, cookies, gotoOptions). Reduces cognitive load. Our endpoints should share a common base too.
3. **Pattern matching with clear precedence** — exclude always wins. No ambiguity. Copy this exactly.
4. **Job status granularity** — separate job-level status from URL-level status. A job can be `completed` even if some URLs `errored`. Smart design.
5. **Cursor-based pagination** — for large result sets. Better than offset-based for streaming/growing results.
6. **`rejectResourceTypes`** — blocking images/media/fonts is a massive speedup for content extraction. Easy win.

## What We Can Do Better

1. **llms.txt as a URL source** — Cloudflare doesn't know about llms.txt. For doc sites that publish one, it's a cleaner, faster discovery mechanism than HTML link scraping.
2. **Python-native API** — Cloudflare is REST-only. We offer `crawler = Crawler(); results = await crawler.crawl(url)` for embedding in Python pipelines.
3. **CLI for one-off crawls** — `proctx-crawler crawl https://docs.pydantic.dev/llms.txt --depth 1 --format markdown`. No server needed.
4. **File-based output** — inspectable, git-friendly, easy to pipe into RAG. Cloudflare returns JSON blobs.
5. **Auto-detect JS rendering** — Cloudflare makes you choose `render: true/false`. We can try static first and auto-fallback to Playwright when we detect a JS shell.
