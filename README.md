# ProContext Crawler

A self-hosted crawl API for extracting structured documentation from websites. Given a starting URL, ProContext Crawler discovers linked pages, fetches them (with optional JavaScript rendering via Playwright), and returns clean Markdown, raw HTML, or a list of links — suitable for feeding into LLMs and documentation pipelines.

Inspired by [Cloudflare's Browser Rendering `/crawl` endpoint](https://developers.cloudflare.com/browser-rendering/rest-api/crawl-endpoint/), built for the [ProContext](https://github.com/procontexthq/procontext) ecosystem.

## Features

- **Multi-page BFS crawl** — discover linked pages up to a configurable depth and page limit
- **Multiple output formats** — Markdown, raw HTML, or link lists
- **Dual fetch paths** — fast static fetch via `httpx` (default) or full JavaScript rendering via Playwright (`render: true`)
- **llms.txt discovery** — seed a crawl from an `llms.txt` index instead of following links
- **URL filtering** — include/exclude glob patterns (exclude wins), subdomain control, external link toggling
- **Async job lifecycle** — POST to start, GET to poll, DELETE to cancel; cursor-based pagination for results
- **Three interfaces** — Python API (`Crawler` async context manager), HTTP API (FastAPI), and CLI (`proctx-crawler …`)
- **Persistence** — SQLite (WAL mode) for job/URL metadata, filesystem for page content plus a per-job `manifest.json`
- **Security** — SSRF protection on the static path (private IP blocking, per-hop redirect re-check), response size limits, optional API-key auth

## Installation

Requires Python 3.12+ and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync --dev

# For Playwright rendering, install the Chromium browser once
uv run playwright install chromium
```

## Quickstart

### CLI

```bash
# Extract a single page as Markdown
uv run proctx-crawler markdown https://example.com/docs

# Fetch raw HTML
uv run proctx-crawler content https://example.com/docs

# List links on a page (use --external to include off-site links)
uv run proctx-crawler links https://example.com/docs

# Crawl a documentation site (depth and page-limit bounded)
uv run proctx-crawler crawl https://example.com/docs \
    --limit 50 --depth 3 \
    --format markdown --format html \
    --include "*/docs/*" --exclude "*/changelog*" \
    --output ./out

# Seed from an llms.txt index instead of link discovery
uv run proctx-crawler crawl https://example.com/llms.txt --source llms_txt

# Start the HTTP API server
uv run proctx-crawler serve --host 127.0.0.1 --port 8080
```

Add `--render` to any subcommand to route through Playwright for JavaScript-heavy pages.

### Python API

```python
import anyio
from proctx_crawler import Crawler


async def main() -> None:
    async with Crawler() as c:
        # Single-page extraction
        md = await c.markdown("https://example.com/docs")
        html = await c.content("https://example.com/docs")
        links = await c.links("https://example.com/docs")

        # Multi-page crawl
        result = await c.crawl(
            "https://example.com/docs",
            limit=50,
            depth=3,
            formats=["markdown"],
            render=False,
            options={
                "include_patterns": ["*/docs/*"],
                "exclude_patterns": ["*/changelog*"],
            },
        )
        print(f"Crawled {result.finished}/{result.total} pages")


anyio.run(main)
```

### HTTP API

```bash
# Start a crawl
curl -X POST http://127.0.0.1:8080/crawl \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com/docs", "crawlOptions": {"limit": 20}}'
# → {"success": true, "result": {"jobId": "...", "status": "queued"}}

# Poll status and paginated results
curl "http://127.0.0.1:8080/crawl?jobId=<id>&limit=50"

# Cancel a running job
curl -X DELETE "http://127.0.0.1:8080/crawl?jobId=<id>"

# Single-page endpoints
curl -X POST http://127.0.0.1:8080/markdown -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com/docs"}'
curl -X POST http://127.0.0.1:8080/content  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com/docs"}'
curl -X POST http://127.0.0.1:8080/links    -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com/docs"}'
```

See [`docs/specs/04-api-reference.md`](docs/specs/04-api-reference.md) for the full request/response schemas and error envelope.

## Configuration

Settings load from (in priority order): constructor arguments, environment variables (`PROCTX_CRAWLER__*`), then `proctx-crawler.yaml` in the working directory.

| Setting | Default | Description |
|---|---|---|
| `output_dir` | `<platformdirs data>/jobs` | Where crawl content is written |
| `db_path` | `<platformdirs data>/crawler.db` | SQLite metadata store |
| `server_host` / `server_port` | `127.0.0.1` / `8080` | API bind address |
| `default_limit` / `default_depth` | `10` / `1000` | Crawl defaults |
| `job_timeout` | `3600` | Max seconds per job |
| `max_concurrent_jobs` | `10` | Concurrency cap |
| `max_response_size` | `10 MB` | Per-response byte ceiling |
| `auth_api_key` | `null` | When set, required as `Authorization: Bearer …` |
| `playwright_headless` | `true` | Run Chromium headless |

Example env var: `PROCTX_CRAWLER__AUTH_API_KEY=secret uv run proctx-crawler serve`.

## Development

```bash
# Tests
uv run pytest

# Tests with coverage (≥90% branch coverage required)
uv run pytest --cov=src/proctx_crawler --cov-fail-under=90

# Lint, format, type check
uv run ruff check src/ tests/
uv run ruff format src/ tests/
uv run pyright src/
```

See [`CLAUDE.md`](CLAUDE.md) and [`.claude/rules/coding-guidelines.md`](.claude/rules/coding-guidelines.md) for contributor guidelines, and [`docs/specs/`](docs/specs/) for the authoritative design documents.

## License

MIT
