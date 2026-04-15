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
- `llms.txt` discovery mode — seed a crawl from an `llms.txt` index instead of following on-page links.
- Dual fetch paths: static `httpx` fetcher (default, fast) and Playwright Chromium renderer (opt-in via `render: true`) backed by a shared browser pool with crash recovery.
- File-based content storage with per-job `manifest.json` and SHA-256 filenames; SQLite repository (WAL mode) for job and URL metadata.
- Job lifecycle management — `queued → running → completed | cancelled | errored` with cancellation honoured mid-crawl and job-timeout enforcement.
- Configuration via `proctx-crawler.yaml`, `PROCTX_CRAWLER__*` environment variables, or constructor arguments, with platform-aware default paths.
- Optional `Authorization: Bearer` API-key authentication for the HTTP API, enabled by setting `auth_api_key`.

### Security

- SSRF protection on the static fetch path: blocks private, loopback, link-local, and carrier-grade NAT IP ranges (IPv4 and IPv6), validates URL schemes, and re-checks every redirect hop.
- Per-response size limit to prevent memory exhaustion from oversized payloads.
