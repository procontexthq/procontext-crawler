# ProContext Crawler

A self-hosted crawl API for extracting structured documentation from websites. Given an llms.txt URL (or any starting URL), the crawler discovers all linked pages, fetches them (with optional JavaScript rendering via Playwright), and returns clean Markdown, raw HTML, or structured JSON.

Inspired by [Cloudflare's Browser Rendering /crawl endpoint](https://developers.cloudflare.com/browser-rendering/rest-api/crawl-endpoint/), built for the [ProContext](https://github.com/procontexthq/procontext) ecosystem.

## What It Does

- **Crawl from a starting URL** — discovers linked pages up to a configurable depth and page limit
- **Multiple output formats** — Markdown, HTML, JSON (structured data extraction)
- **JavaScript rendering** — Playwright-backed headless browser for dynamic/SPA pages
- **Fast static mode** — skip the browser for static pages (`render: false`)
- **URL filtering** — include/exclude patterns, subdomain control, external link following
- **Async job API** — POST to start, GET to poll, DELETE to cancel
- **robots.txt compliance** — respects crawl directives by default
- **Caching** — configurable TTL to avoid redundant fetches
- **Authentication support** — HTTP Basic, custom headers, cookies for gated docs

## Project Structure

```
src/proctx_crawler/
    __init__.py
    config.py            # Settings (pydantic-settings, YAML + env vars)
    errors.py            # Typed error hierarchy
    logging_config.py    # structlog setup (JSON to stderr)

    api/                 # HTTP API layer (FastAPI)
        __init__.py
        app.py           # FastAPI app, lifespan, routes
        models.py        # Request/response schemas

    core/                # Business logic (no framework imports)
        __init__.py
        crawler.py       # Crawl orchestration (BFS/DFS, depth, limits)
        scheduler.py     # Job lifecycle (create, poll, cancel, cleanup)
        fetcher.py       # HTTP fetcher (httpx, redirect handling, SSRF)
        renderer.py      # Playwright browser rendering
        cache.py         # SQLite page cache (WAL mode)
        robots.py        # robots.txt parser and compliance

    extractors/          # Content extraction pipeline
        __init__.py
        markdown.py      # HTML-to-Markdown conversion
        html.py          # Raw HTML extraction / cleanup
        json_extract.py  # Structured data extraction

    models/              # Shared Pydantic models
        __init__.py
        job.py           # Job, CrawlResult, URL status
        page.py          # Page content, metadata

tests/
    unit/                # Pure logic tests (no I/O)
    integration/         # Full pipeline tests

docs/
    specs/               # Design specifications (write before building)
```

## Quick Start

```bash
# Install dependencies
uv sync --dev

# Run the API server
uv run proctx-crawler

# Run tests
uv run pytest

# Lint + format + type check
uv run ruff check src/ tests/
uv run ruff format src/ tests/
uv run pyright src/
```

## License

MIT
