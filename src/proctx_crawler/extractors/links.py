"""Link extraction from HTML with URL resolution and deduplication."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

_SKIP_PREFIXES = ("#", "mailto:", "javascript:")
_ALLOWED_SCHEMES = frozenset(("http", "https"))


def extract_links(html: str, base_url: str) -> list[str]:
    """Extract all links from HTML, resolved to absolute URLs.

    - Parse all <a href="..."> elements
    - Skip fragment-only (#section), mailto:, javascript: links
    - Resolve relative URLs to absolute using base_url
    - Only keep http/https URLs
    - Remove fragments for deduplication
    - Deduplicate while preserving order
    """
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = str(a["href"])

        if any(href.startswith(prefix) for prefix in _SKIP_PREFIXES):
            continue

        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)

        if parsed.scheme not in _ALLOWED_SCHEMES:
            continue

        clean = parsed._replace(fragment="").geturl()
        if clean not in seen:
            seen.add(clean)
            links.append(clean)

    return links
