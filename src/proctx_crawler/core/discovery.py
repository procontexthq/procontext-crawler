"""URL discovery strategies: seed URL generation and per-page link filtering."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt

from proctx_crawler.core.url_utils import (
    is_same_domain,
    is_subdomain,
    matches_patterns,
    normalise_url,
)
from proctx_crawler.extractors.links import extract_links

if TYPE_CHECKING:
    from collections.abc import Callable

SourceMode = Literal["auto", "links", "llms_txt"]

_BARE_URL_RE = re.compile(r"https?://[^\s<>'\"]+")
_ALLOWED_SCHEMES = frozenset({"http", "https"})
_MARKDOWN = MarkdownIt("commonmark")


async def discover_seed_urls(
    url: str,
    source: SourceMode,
    html: str | None = None,
) -> list[str]:
    """Discover seed URLs based on the source strategy.

    For 'links': return [url] (the starting URL itself is the only seed)
    For 'llms_txt': parse the HTML content as llms.txt format, extract all URLs
    """
    if source in {"auto", "links"}:
        return [url]

    if source == "llms_txt":
        if html is None:
            return [url]
        return parse_llms_txt(html)

    msg = f"Unsupported discovery source: {source}"
    raise ValueError(msg)


def parse_llms_txt(text: str) -> list[str]:
    """Parse an llms.txt file and extract all HTTP(S) URLs."""
    return extract_text_urls(text, base_url=None)


def extract_text_urls(text: str, base_url: str | None = None) -> list[str]:
    """Extract crawlable URLs from Markdown/plain text while avoiding code blocks."""
    urls: list[str] = []
    seen: set[str] = set()
    env: dict[str, Any] = {}
    tokens = _MARKDOWN.parse(text, env)

    def add_candidate(candidate: str, *, allow_relative: bool = False) -> None:
        cleaned = _clean_url_candidate(candidate)
        if not cleaned:
            return
        resolved = urljoin(base_url, cleaned) if allow_relative and base_url else cleaned
        parsed = urlparse(resolved)
        if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.hostname:
            return
        fragmentless = parsed._replace(fragment="").geturl()
        normalised = normalise_url(fragmentless)
        if normalised not in seen:
            seen.add(normalised)
            urls.append(fragmentless)

    references = env.get("references")
    if isinstance(references, dict):
        for reference in references.values():
            if isinstance(reference, dict):
                href = reference.get("href")
                if isinstance(href, str):
                    add_candidate(href, allow_relative=True)

    for token in tokens:
        if token.type == "html_block":
            _extract_html_url_candidates(token.content, add_candidate)
            continue

        if token.type != "inline" or token.children is None:
            continue

        for child in token.children:
            if child.type == "link_open":
                href = child.attrGet("href")
                if isinstance(href, str):
                    add_candidate(href, allow_relative=True)
            elif child.type == "html_inline":
                _extract_html_url_candidates(child.content, add_candidate)
            elif child.type == "text":
                for match in _BARE_URL_RE.finditer(child.content):
                    add_candidate(match.group(0))

    return urls


def _extract_html_url_candidates(html: str, add_candidate: Callable[..., None]) -> None:
    """Extract href values from HTML snippets embedded in Markdown."""
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        add_candidate(str(anchor["href"]), allow_relative=True)


def _clean_url_candidate(candidate: str) -> str:
    """Strip punctuation commonly adjacent to prose URLs."""
    value = candidate.strip()
    while value and value[-1] in ".,;:!?":
        value = value[:-1]

    bracket_pairs = {"(": ")", "[": "]", "{": "}"}
    opening = set(bracket_pairs)
    closing = set(bracket_pairs.values())
    reverse_pairs = {close: open_ for open_, close in bracket_pairs.items()}

    while value and value[-1] in closing:
        close_char = value[-1]
        open_char = reverse_pairs[close_char]
        if value.count(close_char) > value.count(open_char):
            value = value[:-1]
        else:
            break

    while value and value[0] in opening:
        open_char = value[0]
        close_char = bracket_pairs[open_char]
        if value.count(open_char) > value.count(close_char):
            value = value[1:]
        else:
            break

    return value


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
