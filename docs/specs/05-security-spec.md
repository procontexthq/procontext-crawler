# ProContext Crawler: Security Specification

> **Document**: 05-security-spec.md
> **Status**: Draft v1
> **Last Updated**: 2026-03-16
> **Depends on**: 01-functional-spec.md, 02-technical-spec.md

---

## Table of Contents

- [1. Scope and Threat Actors](#1-scope-and-threat-actors)
  - [1.1 What This Document Covers](#11-what-this-document-covers)
  - [1.2 Threat Actors](#12-threat-actors)
- [2. Trust Boundaries](#2-trust-boundaries)
- [3. Threat Model](#3-threat-model)
  - [3.1 SSRF — Server-Side Request Forgery](#31-ssrf--server-side-request-forgery)
  - [3.2 Resource Exhaustion](#32-resource-exhaustion)
  - [3.3 Playwright Sandbox Escape](#33-playwright-sandbox-escape)
  - [3.4 Content Injection](#34-content-injection)
  - [3.5 Credential Leakage](#35-credential-leakage)
  - [3.6 DNS Rebinding](#36-dns-rebinding)
  - [3.7 robots.txt Bypass](#37-robotstxt-bypass)
  - [3.8 Supply Chain](#38-supply-chain)
  - [3.9 Path Traversal via URL Hash](#39-path-traversal-via-url-hash)
- [4. Security Controls](#4-security-controls)
  - [4.1 v0.1 Controls](#41-v01-controls)
  - [4.2 v0.2 Controls](#42-v02-controls)
  - [4.3 v0.3+ Controls](#43-v03-controls)
- [5. Known Limitations and Accepted Risks](#5-known-limitations-and-accepted-risks)
- [6. Data Handling](#6-data-handling)
  - [6.1 Data at Rest](#61-data-at-rest)
  - [6.2 Data in Transit](#62-data-in-transit)
  - [6.3 Credential Storage](#63-credential-storage)
- [7. Dependency Vulnerability Management](#7-dependency-vulnerability-management)

---

## 1. Scope and Threat Actors

### 1.1 What This Document Covers

ProContext Crawler's attack surface is significantly larger than a typical web service because it:

1. **Fetches arbitrary user-supplied URLs** — any URL the user provides is fetched by the server
2. **Runs a headless browser** — Playwright executes JavaScript from untrusted web pages
3. **Writes fetched content to disk** — crawled HTML and Markdown are persisted to the filesystem
4. **Stores job metadata in a database** — SQLite contains URL lists, job state, and configuration

This document identifies threats arising from these characteristics and defines the controls to mitigate them.

### 1.2 Threat Actors

| Actor | Motivation | Access Level |
|-------|-----------|-------------|
| **Malicious API consumer** | Abuse the crawler to scan internal networks, exhaust resources, or exfiltrate data | Authenticated or unauthenticated HTTP access to the API |
| **Malicious target site** | Exploit the crawler/browser to escape the sandbox, inject content, or cause denial of service | Serves content that the crawler fetches |
| **Local attacker** | Access crawled content, credentials, or database on the host machine | File system access to the host |

---

## 2. Trust Boundaries

```
┌──────────────────────────────────────────────────────────────┐
│                    UNTRUSTED ZONE                             │
│                                                              │
│  ┌────────────────────┐    ┌──────────────────────────────┐  │
│  │  API Consumer       │    │  Target Website              │  │
│  │  (sends crawl       │    │  (serves HTML/JS that        │  │
│  │   requests)         │    │   the crawler fetches)       │  │
│  └─────────┬──────────┘    └────────────┬─────────────────┘  │
│            │                             │                    │
└────────────┼─────────────────────────────┼────────────────────┘
             │ HTTP request                │ HTTP response / JS
   ══════════╪═════════════════════════════╪══════════════════
             │  TRUST BOUNDARY 1           │  TRUST BOUNDARY 2
   ══════════╪═════════════════════════════╪══════════════════
             ▼                             ▼
┌──────────────────────────────────────────────────────────────┐
│                    TRUSTED ZONE                               │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ API Layer    │  │ Fetcher      │  │ Playwright        │  │
│  │ (validates   │  │ (httpx,      │  │ (browser sandbox, │  │
│  │  input)      │  │  network)    │  │  executes JS)     │  │
│  └──────────────┘  └──────────────┘  └───────────────────┘  │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐                         │
│  │ Repository   │  │ Content      │                         │
│  │ (SQLite)     │  │ Storage      │                         │
│  │              │  │ (filesystem) │                         │
│  └──────────────┘  └──────────────┘                         │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**Trust Boundary 1 (API input)**: All data from API consumers is untrusted. URLs, patterns, selectors, and configuration values must be validated before use.

**Trust Boundary 2 (Fetched content)**: All content fetched from target websites is untrusted. HTML, JavaScript, redirects, and HTTP headers from targets may be malicious.

---

## 3. Threat Model

### 3.1 SSRF — Server-Side Request Forgery

**Risk**: HIGH

**Attack**: An API consumer provides a URL pointing to an internal service (e.g., `http://169.254.169.254/latest/meta-data/`, `http://localhost:6379/`, `http://[::1]:8080/admin`). The crawler fetches the URL, potentially leaking internal data or triggering actions on internal services.

**Mitigations**:

| Control | Phase | Description |
|---------|-------|-------------|
| **URL scheme validation** | v0.1 | Only `http://` and `https://` schemes are allowed. Reject `file://`, `ftp://`, `gopher://`, `data:`, etc. |
| **Private IP blocking** | v0.1 | Before connecting, resolve the hostname and reject private/reserved IP ranges: `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`, `::1`, `fc00::/7`, `fe80::/10`, `100.64.0.0/10` (CGNAT). |
| **Post-redirect validation** | v0.1 | For httpx, use manual redirect handling (`follow_redirects=False`). After each redirect, re-validate the target URL against the SSRF blocklist before following. |
| **DNS resolution check** | v0.1 | Resolve the hostname to an IP address and check the IP against the blocklist before establishing a connection. This prevents DNS records that resolve to private IPs. |
| **Playwright network interception** | v0.2 | Intercept Playwright's network requests to apply the same SSRF checks. In v0.1, Playwright bypasses the httpx SSRF checks — the browser makes its own connections. |

**Residual risk**: In v0.1, Playwright-based fetches do not have SSRF protection because the browser manages its own network stack. Mitigated by requiring `render: true` to be explicitly set — the default path (static fetch) is SSRF-protected. Full Playwright SSRF protection is a v0.2 priority.

### 3.2 Resource Exhaustion

**Risk**: MEDIUM

**Attack**: A consumer starts many large crawl jobs simultaneously, or targets a site that serves extremely large pages, exhausting CPU, memory, disk space, or network bandwidth.

**Mitigations**:

| Control | Phase | Description |
|---------|-------|-------------|
| **Page limit** | v0.1 | `limit` parameter caps pages per job (default: 10). |
| **Job timeout** | v0.1 | Default 1-hour timeout per job. Configurable. |
| **Response size limit** | v0.1 | Reject HTTP responses larger than 10 MB (configurable). Prevents memory exhaustion from pathologically large pages. |
| **Concurrent job limit** | v0.1 | Maximum number of concurrent crawl jobs (default: 10, configurable). New jobs beyond the limit are queued or rejected. |
| **Disk quota** | v0.2 | Configurable maximum disk usage per job and globally. Jobs exceeding the quota are cancelled. |
| **Per-domain rate limiting** | v0.2 | Configurable delay between requests to the same domain. Prevents overwhelming target sites. |

### 3.3 Playwright Sandbox Escape

**Risk**: LOW (but high impact)

**Attack**: A malicious target page exploits a Chromium vulnerability to escape the browser sandbox and execute code on the host.

**Mitigations**:

| Control | Phase | Description |
|---------|-------|-------------|
| **Headless mode** | v0.1 | Always run Playwright in headless mode. No display server, smaller attack surface. |
| **Chromium auto-update** | v0.1 | Playwright bundles Chromium. Running `playwright install` fetches the latest supported version. Keep Playwright dependency up to date. |
| **Resource blocking** | v0.1 | Block unnecessary resource types (`image`, `media`, `font`, `stylesheet`) to reduce the amount of untrusted content the browser processes. |
| **Context isolation** | v0.1 | Each fetch uses a fresh `BrowserContext` via the browser pool. No cookies, storage, or state leaks between fetches. |
| **Navigation timeout** | v0.1 | Hard timeout (default: 30s) on all Playwright navigations. Prevents pages from holding the browser open indefinitely. |
| **Browser crash recovery** | v0.1 | The browser pool detects a crashed browser via `is_connected()` and relaunches automatically. A lock prevents concurrent relaunches. |

**Residual risk**: Chromium zero-days exist. The crawler runs untrusted JavaScript. This is an inherent risk of browser-based rendering. Users handling highly adversarial targets should run the crawler in a container or VM.

### 3.4 Content Injection

**Risk**: LOW

**Attack**: A target page contains malicious content that, when served by the API or saved to disk, exploits consumers of the crawled output (e.g., XSS in Markdown viewers, prompt injection in LLM pipelines).

**Mitigations**:

| Control | Phase | Description |
|---------|-------|-------------|
| **No direct HTML serving** | v0.1 | The API returns content as JSON strings, not as rendered HTML. Consumers must explicitly parse the content. |
| **Content is data, not code** | v0.1 | Crawled Markdown and HTML are treated as opaque strings. The crawler does not render or execute them after extraction. |
| **Documentation** | v0.1 | Document that crawled content is untrusted and consumers must sanitise it before rendering in browsers or feeding to LLMs. |

**Residual risk**: Content injection is fundamentally a consumer-side concern. The crawler's job is to extract content faithfully. Sanitisation is the consumer's responsibility.

### 3.5 Credential Leakage

**Risk**: MEDIUM

**Attack**: Authentication credentials (API key for the crawler, or target site credentials in v0.2) are leaked through logs, error messages, or the database.

**Mitigations**:

| Control | Phase | Description |
|---------|-------|-------------|
| **No credential logging** | v0.1 | structlog processors strip `Authorization` headers, `api_key`, and `password` fields from log output. |
| **Credentials not stored in DB** | v0.2 | Target site credentials (`authenticate`, `cookies`, `set_extra_http_headers`) are used for the current request only. They are NOT persisted in the job configuration stored in SQLite. |
| **API key comparison** | v0.1 | Use constant-time comparison for API key validation to prevent timing attacks. |
| **Error message sanitisation** | v0.1 | Error responses never include credentials. URL parameters that might contain tokens are stripped from error messages. |

### 3.6 DNS Rebinding

**Risk**: LOW

**Attack**: A malicious DNS server returns a public IP for the initial resolution (passing the SSRF check), then returns a private IP for subsequent connections.

**Mitigations**:

| Control | Phase | Description |
|---------|-------|-------------|
| **Pin resolved IP** | v0.2 | After the initial DNS resolution passes the SSRF check, pin the resolved IP and use it for the connection. Prevent re-resolution. |
| **Short DNS TTL detection** | v0.2 | Warn on DNS records with very short TTLs (< 60s) as potential rebinding indicators. |

**Residual risk**: In v0.1, DNS rebinding is theoretically possible for static fetches. The practical risk is low because the attack requires a custom DNS server and the crawler makes only one connection per URL.

### 3.7 robots.txt Bypass

**Risk**: LOW

**Attack**: The crawler ignores robots.txt directives, potentially violating site owners' wishes or legal agreements.

**Mitigations**:

| Control | Phase | Description |
|---------|-------|-------------|
| **robots.txt compliance** | v0.2 | Fetch and respect robots.txt before crawling each domain. Disallowed URLs get `status: "disallowed"`. |
| **Override flag** | v0.2 | A `respect_robots_txt: false` flag allows users to opt out (e.g., crawling their own sites). |
| **User-Agent identification** | v0.1 | The default User-Agent (`proctx-crawler/<version>`) identifies the crawler to site operators. |

**Residual risk**: v0.1 does not enforce robots.txt. Users are responsible for only crawling sites they are authorised to access. The primary target audience (documentation sites) rarely blocks crawlers.

### 3.8 Supply Chain

**Risk**: MEDIUM

**Attack**: A compromised dependency introduces malicious code into the crawler.

**Mitigations**:

| Control | Phase | Description |
|---------|-------|-------------|
| **Lock file** | v0.1 | `uv.lock` pins all transitive dependencies to exact versions. |
| **pip-audit in CI** | v0.1 | Automated vulnerability scanning of all dependencies on every CI run. |
| **Minimal dependency tree** | v0.1 | Only essential dependencies are included. No utility libraries for things that stdlib handles. |
| **Playwright browser pinning** | v0.1 | Playwright's dependency on Chromium is version-pinned by the Playwright package version. |

### 3.9 Path Traversal via URL Hash

**Risk**: LOW

**Attack**: A crafted URL produces a url_hash that, when used as a filename, writes to an unexpected location on disk.

**Mitigations**:

| Control | Phase | Description |
|---------|-------|-------------|
| **SHA-256 hash** | v0.1 | File names are derived from SHA-256 hashes (hex-encoded), which contain only `[0-9a-f]` characters. No path separators, no special characters. |
| **Fixed filename format** | v0.1 | Files are always `<16-char-hex>.md` or `<16-char-hex>.html`. No user-controlled path components. |
| **Parent directory validation** | v0.1 | Before writing, verify that the resolved file path is within the expected job directory. |

---

## 4. Security Controls

### 4.1 v0.1 Controls

| ID | Control | Component |
|----|---------|-----------|
| S1 | URL scheme validation (HTTP/HTTPS only) | Fetcher |
| S2 | Private IP blocking (pre-connect DNS check) | Fetcher |
| S3 | Post-redirect SSRF validation (static fetcher) | Fetcher |
| S4 | Response size limit (10 MB default) | Fetcher |
| S5 | Page limit per job (default: 10) | Crawl Engine |
| S6 | Job timeout (default: 1 hour) | Job Scheduler |
| S7 | Concurrent job limit (default: 10) | Job Scheduler |
| S8 | Playwright headless mode | Renderer |
| S9 | Fresh browser context per fetch | Renderer |
| S10 | Navigation timeout (30s) | Renderer |
| S11 | Optional API key authentication | API Layer |
| S12 | Constant-time API key comparison | API Layer |
| S13 | No credential logging | Logging |
| S14 | SHA-256 filename hashing | Content Storage |
| S15 | Dependency lock file | Build |
| S16 | pip-audit in CI | Build |
| S17 | Identified User-Agent string | Fetcher |

### 4.2 v0.2 Controls

| ID | Control | Component |
|----|---------|-----------|
| S18 | Playwright network interception for SSRF | Renderer |
| S19 | robots.txt compliance | Crawl Engine |
| S20 | Per-domain rate limiting | Crawl Engine |
| S21 | Disk quota per job | Content Storage |
| S22 | Credentials not persisted in DB | Repository |
| S23 | DNS rebinding prevention (IP pinning) | Fetcher |

### 4.3 v0.3+ Controls

| ID | Control | Component |
|----|---------|-----------|
| S24 | AI model credential handling (per-request only) | AI Extractor |
| S25 | Request pattern filtering | Renderer |

---

## 5. Known Limitations and Accepted Risks

| Limitation | Risk | Acceptance Rationale |
|-----------|------|---------------------|
| **v0.1 Playwright has no SSRF protection** | An attacker who sets `render: true` can fetch internal URLs via the browser | `render` defaults to `false`. The attacker must explicitly opt in. Full mitigation in v0.2. |
| **No robots.txt in v0.1** | The crawler may crawl pages that robots.txt disallows | Primary audience crawls owned documentation sites. Full mitigation in v0.2. |
| **Content injection is a consumer problem** | Crawled content may contain XSS payloads or prompt injections | The crawler extracts content faithfully. Sanitisation is the consumer's responsibility. Documented clearly. |
| **Chromium zero-days** | A browser exploit could compromise the host | Inherent to browser-based rendering. Mitigated by headless mode, context isolation, and keeping Playwright up to date. High-security deployments should containerise. |
| **Single-machine deployment** | A resource exhaustion attack affects the entire service | Not designed for multi-tenant hostile environments. Job limits and timeouts provide reasonable protection. |

---

## 6. Data Handling

### 6.1 Data at Rest

| Data | Location | Protection |
|------|----------|------------|
| Crawled content (Markdown, HTML) | Filesystem: `<output_dir>/<job_id>/` | Standard filesystem permissions. No encryption at rest (user's responsibility). |
| Job metadata, URL queue | SQLite database | Standard filesystem permissions. WAL mode file. |
| Configuration | `proctx-crawler.yaml` or env vars | Standard filesystem permissions. |

**Recommendation**: Deploy with restrictive file permissions (`chmod 700` on data directories). For sensitive deployments, use full-disk encryption.

### 6.2 Data in Transit

| Data Flow | Protection |
|-----------|------------|
| API consumer → Crawler | TLS (HTTPS) when deployed behind a reverse proxy. No built-in TLS — use nginx/caddy/etc. |
| Crawler → Target site | TLS when the target URL is HTTPS. The crawler does not downgrade HTTPS to HTTP. |

**Recommendation**: Deploy behind a reverse proxy with TLS termination for production use.

### 6.3 Credential Storage

| Credential | Storage | Lifetime |
|------------|---------|----------|
| Crawler API key | Environment variable or config file | Process lifetime |
| Target site credentials (v0.2) | In-memory only | Single request |
| AI model API keys (v0.3) | In-memory only | Single request |

Target site credentials and AI model keys are **never** written to the database or logs.

---

## 7. Dependency Vulnerability Management

**Scanning**: `pip-audit` runs in CI on every push. It checks all installed packages against the OSV (Open Source Vulnerabilities) database.

**Process**:

1. `pip-audit` flags a vulnerability in a dependency
2. If a patched version exists: update the dependency constraint and regenerate `uv.lock`
3. If no patch exists: assess the vulnerability's applicability. If it affects a code path the crawler uses, track as a known issue. If not, document and accept the risk.

**Lock file hygiene**: `uv.lock` pins all transitive dependencies. No floating versions in production. `uv sync --dev` is the only way to install — no pip, no manual installs.

**Chromium updates**: Playwright bundles a specific Chromium version. Keeping the Playwright dependency up to date automatically brings in Chromium security patches. The `playwright install` command downloads the browser binary.
