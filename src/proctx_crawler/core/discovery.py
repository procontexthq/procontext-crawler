"""URL discovery strategies: seed URL generation and per-page link filtering."""

from __future__ import annotations

import re

from proctx_crawler.core.url_utils import is_same_domain, is_subdomain, matches_patterns
from proctx_crawler.extractors.links import extract_links

_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^)]+)\)")
_BARE_URL_RE = re.compile(r"https?://[^\s>)\]]+")


async def discover_seed_urls(url: str, source: str, html: str | None = None) -> list[str]:
    """Discover seed URLs based on the source strategy.

    For 'links': return [url] (the starting URL itself is the only seed)
    For 'llms_txt': parse the HTML content as llms.txt format, extract all URLs
    """
    if source == "links":
        return [url]

    if source == "llms_txt":
        if html is None:
            return [url]
        return parse_llms_txt(html)

    return [url]


def parse_llms_txt(text: str) -> list[str]:
    """Parse an llms.txt file and extract all HTTP(S) URLs.

    Two extraction strategies:
    1. Markdown links: [text](url) -- extract URL from parentheses
    2. Bare URLs: lines containing https://... or http://... -- extract URL

    The parser is intentionally lenient. Section headers and descriptive text are ignored.
    All extracted URLs are deduplicated while preserving order.
    """
    urls: list[str] = []
    seen: set[str] = set()

    # First pass: extract markdown link URLs
    markdown_urls: set[str] = set()
    for match in _MARKDOWN_LINK_RE.finditer(text):
        url = match.group(2)
        markdown_urls.add(url)
        if url not in seen:
            seen.add(url)
            urls.append(url)

    # Second pass: extract bare URLs not already captured via markdown links
    for match in _BARE_URL_RE.finditer(text):
        url = match.group(0)
        if url not in seen:
            # Check this bare URL wasn't part of a markdown link already extracted
            # (the regex may match a substring of a markdown link URL)
            seen.add(url)
            urls.append(url)

    return urls


def discover_page_links(
    html: str,
    base_url: str,
    *,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    include_subdomains: bool = False,
    include_external_links: bool = False,
    start_url: str,
) -> list[str]:
    """Extract links from a page and filter them.

    1. Extract all links using extract_links()
    2. Apply domain filtering (same domain, subdomains, external)
    3. Apply pattern matching (include/exclude)
    """
    raw_links = extract_links(html, base_url)
    filtered: list[str] = []

    for link in raw_links:
        # Domain filtering
        if not include_external_links:
            if include_subdomains:
                if not is_subdomain(link, start_url):
                    continue
            else:
                if not is_same_domain(link, start_url):
                    continue

        # Pattern matching
        if not matches_patterns(link, include=include_patterns, exclude=exclude_patterns):
            continue

        filtered.append(link)

    return filtered
