# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `Crawler` class — async context manager exposing `crawl()`, `markdown()`, `content()`, and `links()` as the public Python API.
- HTTP API (FastAPI) with `POST /crawl`, `GET /crawl`, `DELETE /crawl`, `POST /markdown`, `POST /content`, and `POST /links`. Results use a consistent success/error envelope and cursor-based pagination.
- `proctx-crawler` CLI with `crawl`, `markdown`, `content`, `links`, and `serve` subcommands.
- Multi-page BFS crawl engine with configurable page limit, link depth, URL include/exclude patterns (exclude wins), subdomain and external-link filtering, and per-page error isolation.
- Automatic crawl discovery mode — HTML pages discover children from `<a href>` tags, while `llms.txt`, Markdown, and plain-text indexes use robust text URL parsing by default.
- Explicit `links` and `llms_txt` crawl discovery modes for callers that need to override automatic classification.
- Dual fetch paths: static `httpx` fetcher (default, fast) and Playwright Chromium renderer (opt-in via `render: true`) backed by a shared browser pool with crash recovery.
- File-based content storage with per-job `manifest.json` and SHA-256 filenames; SQLite repository (WAL mode) for job and URL metadata.
- Job lifecycle management — `queued → running → completed | cancelled | errored` with cancellation honoured mid-crawl.
- Cooperative job timeout enforcement via `job_timeout`; timed-out jobs cancel queued URLs, update counts, and still write `manifest.json`.
- Configuration via `proctx-crawler.yaml`, `PROCTX_CRAWLER__*` environment variables, or constructor arguments, with platform-aware default paths.
- Optional `Authorization: Bearer` API-key authentication for the HTTP API, enabled by setting `auth_api_key`.

### Changed

- `source` now defaults to `"auto"` in the Python API, HTTP API, and CLI.

### Security

- SSRF protection on the static fetch path: blocks private, loopback, link-local, multicast, reserved, carrier-grade NAT, benchmarking, and IPv4-mapped blocked IP ranges, validates URL schemes, allows NAT64 only for public embedded IPv4 addresses, and re-checks every redirect hop.
- Fetch/render error messages and fetch redirect logs redact URL userinfo, query strings, and fragments.
- Per-response size limit to prevent memory exhaustion from oversized payloads.
