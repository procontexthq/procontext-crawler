# Implementation Plan

> **Status**: Draft v1
> **Last Updated**: 2026-03-16
> **Depends on**: All spec documents in `docs/specs/`

This document defines the execution plan for building ProContext Crawler v0.1. It breaks work into ordered phases with clear dependencies, file mappings, and testing strategy.

---

## Table of Contents

- [1. Current State](#1-current-state)
- [2. v0.1 Scope Recap](#2-v01-scope-recap)
- [3. Module Map](#3-module-map)
- [4. Dependency Graph](#4-dependency-graph)
- [5. Implementation Phases](#5-implementation-phases)
  - [Phase 1: Foundation](#phase-1-foundation)
  - [Phase 2: Fetcher](#phase-2-fetcher)
  - [Phase 3: Extractors](#phase-3-extractors)
  - [Phase 4: Repository Layer](#phase-4-repository-layer)
  - [Phase 5: Content Storage](#phase-5-content-storage)
  - [Phase 6: Crawl Engine](#phase-6-crawl-engine)
  - [Phase 7: Python API](#phase-7-python-api)
  - [Phase 8: HTTP API](#phase-8-http-api)
  - [Phase 9: CLI](#phase-9-cli)
  - [Phase 10: Integration Testing and Polish](#phase-10-integration-testing-and-polish)
- [6. Testing Strategy](#6-testing-strategy)
- [7. v0.1 Definition of Done](#7-v01-definition-of-done)
- [8. Post-v0.1 Roadmap](#8-post-v01-roadmap)

---

## 1. Current State

The project has:

- Project skeleton: `pyproject.toml`, dependencies, dev tooling config (ruff, pyright, pytest)
- Empty package directories: `src/proctx_crawler/{api,core,extractors,models}/`
- Complete spec documents: functional, technical, API reference, security
- Research documents and brain dump
- No implementation code

---

## 2. v0.1 Scope Recap

From the functional spec (Section 4.1):

**Endpoints**: `/crawl` (POST/GET/DELETE), `/markdown`, `/content`, `/links`

**Capabilities**:
- Single-page extraction: Markdown, HTML, links
- Multi-page BFS crawl with link discovery
- llms.txt URL discovery mode
- URL include/exclude pattern matching
- Domain filtering (subdomains, external links)
- Static httpx fetch (default) + Playwright rendering (opt-in)
- File-based content storage
- SQLite-backed job/URL metadata (Repository pattern)
- Python API (`Crawler` class, async context manager)
- HTTP API (FastAPI)
- CLI (`proctx-crawler` commands)

**Security controls (v0.1)**: SSRF protection (static fetcher), response size limits, job timeouts, concurrent job limits, API key auth, SHA-256 filenames.

---

## 3. Module Map

Target file structure after v0.1 implementation:

```
src/proctx_crawler/
    __init__.py                     # Re-exports Crawler class
    crawler.py                      # Crawler class (Python API) — Phase 7
    config.py                       # Settings (pydantic-settings) — Phase 1
    logging_config.py               # structlog setup — Phase 1

    models/
        __init__.py                 # Re-exports all models
        job.py                      # Job, JobStatus — Phase 1
        url_record.py               # UrlRecord, UrlStatus — Phase 1
        input.py                    # CrawlConfig, SinglePageInput, etc. — Phase 1
        output.py                   # SuccessResponse, CrawlResult, etc. — Phase 1
        errors.py                   # ErrorCode, CrawlerError, etc. — Phase 1

    core/
        __init__.py
        fetcher.py                  # Static httpx fetcher — Phase 2
        renderer.py                 # Playwright renderer — Phase 2
        ssrf.py                     # SSRF validation — Phase 2
        engine.py                   # BFS crawl engine — Phase 6
        url_utils.py                # URL normalisation, pattern matching — Phase 1
        discovery.py                # URL discovery strategies (links, llms_txt) — Phase 3
        repository.py               # Repository Protocol — Phase 4

    extractors/
        __init__.py
        markdown.py                 # HTML-to-Markdown — Phase 3
        links.py                    # Link extraction — Phase 3
        content.py                  # Raw HTML extraction — Phase 3

    infrastructure/
        __init__.py
        sqlite_repository.py        # SQLite Repository implementation — Phase 4
        content_storage.py          # Filesystem content storage — Phase 5

    api/
        __init__.py
        app.py                      # FastAPI app, lifespan — Phase 8
        routes.py                   # All HTTP routes — Phase 8

    cli.py                          # CLI entry point (argparse) — Phase 9

tests/
    __init__.py
    unit/
        __init__.py
        test_url_utils.py           # URL normalisation, pattern matching — Phase 1
        test_ssrf.py                # SSRF validation — Phase 2
        test_fetcher.py             # Static fetcher (mocked) — Phase 2
        test_renderer.py            # Playwright renderer (mocked) — Phase 2
        test_markdown_extractor.py  # HTML-to-Markdown — Phase 3
        test_link_extractor.py      # Link extraction — Phase 3
        test_discovery.py           # llms.txt parsing, link discovery — Phase 3
        test_sqlite_repository.py   # SQLite repo — Phase 4
        test_content_storage.py     # Filesystem storage — Phase 5
        test_engine.py              # Crawl engine (mocked fetcher/repo) — Phase 6
        test_crawler.py             # Crawler class — Phase 7
        test_models.py              # Input validation, model serialisation — Phase 1
    integration/
        __init__.py
        test_single_page.py         # End-to-end single-page extraction — Phase 10
        test_crawl.py               # End-to-end multi-page crawl — Phase 10
        test_api.py                 # HTTP API integration — Phase 10
        test_cli.py                 # CLI integration — Phase 10
```

---

## 4. Dependency Graph

Phases must be completed in order where arrows exist. Phases without dependencies can be parallelised.

```
Phase 1: Foundation (models, config, logging, url_utils)
    │
    ├──► Phase 2: Fetcher (httpx, Playwright, SSRF)
    │        │
    │        └──► Phase 3: Extractors (markdown, links, discovery)
    │
    ├──► Phase 4: Repository Layer (Protocol + SQLite)
    │
    └──► Phase 5: Content Storage (filesystem)
              │
              ▼
         Phase 6: Crawl Engine (BFS, depends on 2+3+4+5)
              │
              ▼
         Phase 7: Python API (Crawler class, depends on 6)
              │
              ├──► Phase 8: HTTP API (FastAPI, depends on 7)
              │
              └──► Phase 9: CLI (argparse, depends on 7)
                      │
                      ▼
                 Phase 10: Integration Testing & Polish
```

**Parallelisable work**:
- Phases 2, 4, 5 can start simultaneously (all depend only on Phase 1)
- Phases 8 and 9 can run in parallel (both depend on Phase 7)

---

## 5. Implementation Phases

### Phase 1: Foundation

**Goal**: All data types, configuration, logging, and URL utilities ready. Nothing depends on external I/O yet — this phase is pure logic.

**Files**:

| File | What to Build |
|------|--------------|
| `models/job.py` | `JobStatus` enum, `Job` model |
| `models/url_record.py` | `UrlStatus` enum, `UrlRecord` model |
| `models/input.py` | `CrawlConfig`, `CrawlOptions`, `GotoOptions`, `SinglePageInput` (with `url_or_html` validator) |
| `models/output.py` | `SuccessResponse[T]`, `CrawlResult`, `CrawlRecord`, `RecordMetadata` |
| `models/errors.py` | `ErrorCode` enum, `ErrorDetail`, `ErrorResponse`, `CrawlerError` + subclasses |
| `models/__init__.py` | Re-export all public models |
| `config.py` | `Settings` class with pydantic-settings, `load_settings()` function |
| `logging_config.py` | `configure_logging()` with structlog (stderr, JSON/console toggle) |
| `core/url_utils.py` | `normalise_url()`, `compile_pattern()`, `matches_patterns()`, `is_same_domain()`, `is_subdomain()` |

**Tests**:

| Test File | Coverage |
|-----------|----------|
| `test_models.py` | Model validation, serialisation, `url_or_html` validator edge cases |
| `test_url_utils.py` | URL normalisation (scheme, port, fragment, trailing slash, query sort), pattern compilation, pattern matching (include/exclude precedence), domain checks |

**Definition of done**: All models serialise/deserialise correctly. URL normalisation handles edge cases. Pattern matching follows the exclude-wins-over-include rule. Config loads from defaults, YAML, and env vars.

---

### Phase 2: Fetcher

**Goal**: Can fetch any URL via httpx or Playwright. SSRF protection on the static path.

**Files**:

| File | What to Build |
|------|--------------|
| `core/ssrf.py` | `validate_url_scheme()`, `resolve_and_check_ip()`, `is_private_ip()`. IPv4 and IPv6 blocklists. |
| `core/fetcher.py` | `FetchResult` model, `fetch_static()` with httpx, manual redirect handling with SSRF re-check per hop, response size limit, configurable timeout |
| `core/renderer.py` | `fetch_rendered()` with Playwright, `gotoOptions`, `waitForSelector`, `rejectResourceTypes`, resource blocker route handler |

**Tests**:

| Test File | Coverage |
|-----------|----------|
| `test_ssrf.py` | Private IPs (127.x, 10.x, 172.16.x, 192.168.x, ::1, fc00::, 169.254.x, 100.64.x), public IPs pass, scheme validation, edge cases (IPv6 mapped IPv4) |
| `test_fetcher.py` | Happy path (mocked httpx via respx), redirect following with SSRF re-check, response size limit enforcement, timeout handling, error classification (404, 500, timeout) |
| `test_renderer.py` | Mocked Playwright (or skip if Playwright not installed), resource blocking, wait_for_selector, goto_options |

**Definition of done**: `fetch_static("https://example.com")` returns HTML. SSRF blocks `http://127.0.0.1`. Redirects are followed with re-validation. `fetch_rendered()` works with Playwright headless Chromium.

---

### Phase 3: Extractors

**Goal**: Given HTML, produce Markdown, extract links, and parse llms.txt.

**Files**:

| File | What to Build |
|------|--------------|
| `extractors/markdown.py` | `html_to_markdown()` — BeautifulSoup content selection (main/article/body), strip nav/header/footer/script, markdownify conversion |
| `extractors/links.py` | `extract_links()` — parse `<a href>`, resolve relative URLs, skip fragments/mailto/javascript, deduplicate |
| `extractors/content.py` | `extract_html()` — minimal wrapper, return raw HTML (or Playwright-rendered DOM) |
| `core/discovery.py` | `discover_seed_urls()` — dispatch by source strategy. `parse_llms_txt()` — extract URLs from llms.txt format. `discover_page_links()` — wrapper around link extraction with domain/pattern filtering |

**Tests**:

| Test File | Coverage |
|-----------|----------|
| `test_markdown_extractor.py` | Basic HTML → Markdown, content selection (`<main>`, `<article>`, `<body>` fallback), nav/script stripping, empty page, malformed HTML |
| `test_link_extractor.py` | Relative URL resolution, fragment-only links skipped, mailto/javascript skipped, deduplication, external links, empty page |
| `test_discovery.py` | llms.txt parsing (markdown links, bare URLs, mixed content, empty file), link discovery with domain filtering, pattern filtering integration |

**Definition of done**: `html_to_markdown("<html>...")` returns clean Markdown. `extract_links(html, base_url)` returns deduplicated absolute URLs. `parse_llms_txt(text)` extracts documentation URLs.

---

### Phase 4: Repository Layer

**Goal**: Job and URL metadata persistence via the Repository protocol backed by SQLite.

**Files**:

| File | What to Build |
|------|--------------|
| `core/repository.py` | `Repository` Protocol class with all methods from tech spec Section 7.1 |
| `infrastructure/sqlite_repository.py` | `SQLiteRepository` implementing the Protocol. Schema DDL, WAL mode, foreign keys, all CRUD operations, cursor-based pagination |

**Tests**:

| Test File | Coverage |
|-----------|----------|
| `test_sqlite_repository.py` | Create/get/update job, enqueue URLs, update URL status, mark completed/errored, cancel queued URLs, cursor pagination (multi-page results, empty results, cursor exhaustion), concurrent read/write (WAL mode), job_id foreign key constraint, duplicate URL handling |

**Definition of done**: Full CRUD cycle for jobs and URL records. Cursor pagination returns stable pages. `cancel_queued_urls` bulk-updates correctly. `is_job_cancelled` returns correct state.

---

### Phase 5: Content Storage

**Goal**: Write and read content files to/from disk. Manifest generation.

**Files**:

| File | What to Build |
|------|--------------|
| `infrastructure/content_storage.py` | `ContentStorage` class — `url_hash()`, `write()`, `read()`, `write_manifest()`, `job_dir()` |

**Tests**:

| Test File | Coverage |
|-----------|----------|
| `test_content_storage.py` | Write Markdown, write HTML, write both, read back, url_hash determinism, manifest.json structure, non-existent job/file returns None, directory creation (parents=True) |

**Definition of done**: Write content → read it back identically. Manifest maps hash → URL. Directories are created automatically.

---

### Phase 6: Crawl Engine

**Goal**: The BFS crawl loop that ties fetcher, extractors, repository, and storage together.

**Files**:

| File | What to Build |
|------|--------------|
| `core/engine.py` | `run_crawl()` — BFS loop (deque-based), visited set with normalised URLs, depth tracking, limit enforcement, cancellation check, error isolation, manifest write on completion. `QueueEntry` dataclass. `should_crawl()` filter function. |

**Tests**:

| Test File | Coverage |
|-----------|----------|
| `test_engine.py` | Uses mocked fetcher and in-memory repository. Tests: basic crawl (3 pages, linked), depth limit respected, page limit respected, URL pattern filtering, domain filtering, cancellation mid-crawl, error isolation (one page fails, others continue), llms_txt source (no per-page discovery), visited set prevents re-crawl, empty queue terminates |

**Definition of done**: A mocked crawl of 5 interconnected pages completes with correct records. Limits, filters, and cancellation all work. Errors on individual URLs don't crash the crawl.

---

### Phase 7: Python API

**Goal**: The `Crawler` class — async context manager wrapping all functionality.

**Files**:

| File | What to Build |
|------|--------------|
| `crawler.py` | `Crawler` class with `__aenter__`/`__aexit__`, `crawl()`, `markdown()`, `content()`, `links()`, internal `_fetch()` dispatcher (static vs Playwright) |
| `__init__.py` | Re-export `Crawler` from package root |

**Tests**:

| Test File | Coverage |
|-----------|----------|
| `test_crawler.py` | Context manager lifecycle (init/close), `markdown()` returns string, `content()` returns HTML, `links()` returns URL list, `crawl()` completes and returns CrawlResult, render=True dispatches to Playwright, render=False dispatches to httpx. Uses mocked fetcher (no real network). |

**Definition of done**: `async with Crawler() as c: result = await c.crawl(url)` works end-to-end with mocked network. All single-page methods return expected types.

---

### Phase 8: HTTP API

**Goal**: FastAPI server exposing all v0.1 endpoints.

**Files**:

| File | What to Build |
|------|--------------|
| `api/app.py` | FastAPI app, lifespan (init repo, storage, task group), error handler, optional API key middleware |
| `api/routes.py` | `POST /crawl`, `GET /crawl`, `DELETE /crawl`, `POST /markdown`, `POST /content`, `POST /links` |

**Tests**:

| Test File | Coverage |
|-----------|----------|
| `test_api.py` (integration) | Use `httpx.AsyncClient` with FastAPI `TestClient`. Test each endpoint's happy path and error cases. Test API key enforcement (when configured). Test error envelope format. |

**Definition of done**: All 6 endpoints respond correctly. Error envelope matches spec. API key auth works when configured.

---

### Phase 9: CLI

**Goal**: Command-line interface using argparse.

**Files**:

| File | What to Build |
|------|--------------|
| `cli.py` | `main()` entry point, subcommands: `crawl`, `markdown`, `content`, `links`, `serve`. Argument parsing, output formatting (progress to stderr, content to stdout). |

**Tests**:

| Test File | Coverage |
|-----------|----------|
| `test_cli.py` (integration) | Invoke CLI commands via subprocess or direct function call. Test argument parsing, `--help` output, `serve` starts and binds (then exits), `markdown` writes to stdout. |

**Definition of done**: `proctx-crawler markdown <url>` prints Markdown. `proctx-crawler crawl <url>` writes files and prints output dir. `proctx-crawler serve` starts the server.

---

### Phase 10: Integration Testing and Polish

**Goal**: End-to-end tests with real (local) HTTP servers, final documentation, and release prep.

**Tasks**:

| Task | Description |
|------|-------------|
| **Local test server** | A tiny FastAPI app in `tests/fixtures/` serving static HTML pages with known content and link structure. Used by integration tests instead of hitting real websites. |
| **End-to-end crawl test** | Start a crawl against the local test server, verify output files, job status, and record content. |
| **End-to-end single-page tests** | `/markdown`, `/content`, `/links` against the local test server. |
| **Playwright integration test** | At least one test using real Playwright against the local test server (not mocked). Marked with a pytest marker so it can be skipped in CI without Playwright installed. |
| **README update** | Update README.md with installation, quickstart, usage examples. |
| **Coverage check** | Verify ≥90% branch coverage. Add tests for any uncovered paths. |
| **Linting pass** | `ruff check`, `ruff format`, `pyright` all clean. |
| **CHANGELOG** | Populate `[Unreleased]` section with v0.1 features. |

**Definition of done**: All tests pass. Coverage ≥90%. Linting clean. README has working examples. `proctx-crawler crawl <local-test-url>` produces correct output files.

---

## 6. Testing Strategy

**Philosophy**: Unit tests with mocked I/O for fast feedback during development. Integration tests with a local HTTP server for confidence before release.

| Layer | Approach | External I/O |
|-------|----------|-------------|
| Models, URL utils | Unit tests, pure logic | None |
| SSRF | Unit tests, mock DNS resolution | None |
| Fetcher (static) | Unit tests with `respx` (httpx mock) | None |
| Fetcher (Playwright) | Mocked in unit tests; real Playwright in integration (optional) | Browser (integration only) |
| Extractors | Unit tests with HTML fixtures | None |
| Repository | Unit tests with real SQLite (in-memory `:memory:` or tmp file) | SQLite |
| Content Storage | Unit tests with `tmp_path` fixture | Filesystem (tmp) |
| Crawl Engine | Unit tests with mocked fetcher + in-memory repo | None |
| Python API | Unit tests with mocked fetcher | None |
| HTTP API | Integration tests with `httpx.AsyncClient` + TestClient | FastAPI (in-process) |
| CLI | Integration tests with subprocess or function call | Process |
| End-to-end | Integration tests with local test server | Network (localhost) |

**Test fixtures** (`tests/fixtures/`):

- `simple.html` — basic page with heading, paragraphs, links
- `spa_shell.html` — JS-shell page (empty body, script tags) for auto-detect testing
- `llms_txt.txt` — sample llms.txt file with documentation links
- `linked_pages/` — set of HTML pages linking to each other (for crawl tests)

**Pytest markers**:

- `@pytest.mark.playwright` — requires Playwright browser installed (skipped in basic CI)

---

## 7. v0.1 Definition of Done

All of the following must be true before v0.1 is tagged:

- [ ] All v0.1 endpoints implemented and tested: `/crawl` POST/GET/DELETE, `/markdown`, `/content`, `/links`
- [ ] Python API works: `async with Crawler() as c: result = await c.crawl(url)`
- [ ] CLI works: `proctx-crawler crawl <url>`, `proctx-crawler markdown <url>`, `proctx-crawler serve`
- [ ] BFS crawl with link discovery produces correct output files
- [ ] llms.txt discovery mode parses and crawls listed URLs
- [ ] URL pattern matching (include/exclude, exclude wins)
- [ ] Domain filtering (subdomain, external link controls)
- [ ] Static fetch via httpx (default path)
- [ ] Playwright rendering when `render: true`
- [ ] SSRF protection on static fetch path
- [ ] File-based content storage with manifest.json
- [ ] SQLite repository with WAL mode
- [ ] Job lifecycle: queued → running → completed/cancelled/errored
- [ ] Cursor-based pagination for crawl results
- [ ] Job timeout enforcement
- [ ] Optional API key authentication
- [ ] `ruff check` and `ruff format` clean
- [ ] `pyright` clean (standard mode)
- [ ] `pytest` passes with ≥90% branch coverage
- [ ] `pip-audit` clean
- [ ] README with installation and usage examples
- [ ] CHANGELOG populated

---

## 8. Post-v0.1 Roadmap

A brief sketch. Each will get its own implementation plan when the time comes.

**v0.2 — Enhanced**:
- Auto-detect JS rendering
- robots.txt compliance
- Per-domain rate limiting
- Target site authentication (cookies, headers, Basic auth)
- Page cache with TTL (`maxAge`)
- Incremental crawling (`modifiedSince`)
- Sitemap discovery
- `/scrape` endpoint
- Playwright SSRF protection
- Disk quotas
- Browser pool (shared across crawl pages)
- Concurrent fetching within a crawl job

**v0.3+ — Extended**:
- `/json` endpoint (AI-powered extraction)
- `/screenshot`, `/pdf`, `/snapshot` endpoints
- SSE streaming for crawl progress
- Zip/tar export
- Webhook callbacks
- Request pattern filtering
- Pluggable extractors
