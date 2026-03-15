# Cloudflare Browser Rendering — API Overview

> **Source**: [developers.cloudflare.com/browser-rendering](https://developers.cloudflare.com/browser-rendering/)
> **Captured**: 2026-03-15
> **Purpose**: Reference document for ProContext Crawler design decisions.

---

## What It Is

Headless Chrome on Cloudflare's global network. Two integration methods:
1. **REST API** — stateless HTTP endpoints for screenshots, PDFs, Markdown, scraping, crawling
2. **Workers Bindings** — full Puppeteer/Playwright/Stagehand automation inside Workers

We're only interested in replicating the REST API surface.

---

## REST API Endpoints (9 total)

| Endpoint | Method | Purpose | Response Type |
|----------|--------|---------|---------------|
| `/content` | POST | Fetch fully-rendered HTML (after JS execution) | JSON (`result`: HTML string) |
| `/markdown` | POST | Convert webpage to Markdown | JSON (`result`: Markdown string) |
| `/screenshot` | POST | Capture screenshot | Binary (PNG/JPEG) |
| `/pdf` | POST | Render page as PDF | Binary (PDF) |
| `/scrape` | POST | Extract specific HTML elements by CSS selector | JSON (structured element data) |
| `/json` | POST | AI-powered structured data extraction | JSON (matches prompt/schema) |
| `/links` | POST | Extract all links from a page | JSON (array of URL strings) |
| `/snapshot` | POST | Take a webpage snapshot (MHTML) | Binary |
| `/crawl` | POST/GET/DELETE | Multi-page async crawl | JSON (job + records) |

### Endpoint Categories

**Single-page, synchronous**: `/content`, `/markdown`, `/screenshot`, `/pdf`, `/scrape`, `/json`, `/links`, `/snapshot`
- Request in, result back. No job tracking needed.
- All share a common parameter set (url/html, auth, cookies, gotoOptions, etc.)

**Multi-page, asynchronous**: `/crawl`
- POST starts a job, GET polls status/results, DELETE cancels.
- Configurable depth, limits, URL patterns, output formats.

---

## Shared Parameters (across all endpoints)

Every endpoint accepts either `url` (string) or `html` (string) as the primary input. Plus these optional params:

| Parameter | Type | Description |
|-----------|------|-------------|
| `authenticate` | `{username, password}` | HTTP Basic Auth for the target site |
| `cookies` | array of objects | Cookies to set before loading |
| `setExtraHTTPHeaders` | object | Custom HTTP headers for requests |
| `userAgent` | string | Override User-Agent (does NOT bypass bot detection) |
| `gotoOptions` | object | Page load control: `waitUntil` (`networkidle0`, `networkidle2`), `timeout` |
| `waitForSelector` | `{selector, timeout, visible}` | Wait for a CSS selector before returning |
| `rejectResourceTypes` | array | Block resource types: `image`, `media`, `font`, `stylesheet` |
| `rejectRequestPattern` | array | Block requests matching regex patterns |
| `allowResourceTypes` | array | Only allow specific resource types |
| `allowRequestPattern` | array | Only allow requests matching patterns |
| `addScriptTag` | array | Inject JavaScript before capture |
| `addStyleTag` | array | Inject CSS before capture |
| `viewport` | `{width, height, deviceScaleFactor}` | Browser viewport (default: 1920x1080) |

---

## Authentication

All endpoints require: `Authorization: Bearer <apiToken>` with "Browser Rendering - Edit" permission.

---

## Response Header

All responses include `X-Browser-Ms-Used` header — browser processing time in milliseconds.

---

## Limits

| Constraint | Free Plan | Paid Plan |
|-----------|-----------|-----------|
| Daily browser usage | 10 min/day | Unlimited (pay-per-use) |
| REST API rate | 6/min (1 every 10s) | 600/min (10/s) |
| Concurrent browsers (bindings) | 3/account | 30/account |
| New browsers/min (bindings) | 3/min | 30/min |
| Browser inactivity timeout | 60s | 60s (extendable to 10min) |
| Daily crawl jobs | 5/day | Not specified |
| Max pages per crawl (free) | 100 | 100,000 |
| Crawl job max runtime | 7 days | 7 days |
| Crawl results retention | 14 days | 14 days |
