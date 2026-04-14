"""URL normalisation, pattern matching, and domain comparison utilities."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse, urlunparse

# RFC 3986 Section 2.3: unreserved characters that should be decoded
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


def _normalise_percent_encoding(s: str) -> str:
    """Decode unreserved percent-encoded chars, re-encode with uppercase hex."""
    decoded = unquote(s)
    # Re-encode: only encode characters that are NOT unreserved and NOT structural
    # We decode fully then re-encode non-unreserved chars, preserving path structure
    result: list[str] = []
    for char in decoded:
        if char in _UNRESERVED or char in "/:@!$&'()+,;=":
            result.append(char)
        else:
            result.append(quote(char, safe=""))
    return "".join(result)


def normalise_url(url: str) -> str:
    """Normalise a URL for deduplication and comparison.

    Steps:
    1. Lowercase scheme and host
    2. Remove default ports (80 for HTTP, 443 for HTTPS)
    3. Remove trailing slash (except for root path)
    4. Remove fragment
    5. Sort query parameters alphabetically
    6. Remove empty query string
    7. Percent-decode unreserved characters, re-encode with uppercase hex
    """
    parsed = urlparse(url)

    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()

    # Reconstruct netloc: remove default ports
    port = parsed.port
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None

    netloc = hostname
    if port is not None:
        netloc = f"{netloc}:{port}"

    # Normalise path: resolve .. and . segments, remove trailing slash (except root)
    path = parsed.path or "/"
    # Resolve relative path segments
    segments: list[str] = []
    for segment in path.split("/"):
        if segment == "..":
            if segments:
                segments.pop()
        elif segment != ".":
            segments.append(segment)
    path = "/".join(segments) or "/"

    # Remove trailing slash except for root path
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    # Normalise percent encoding in path
    path = _normalise_percent_encoding(path)

    # Sort query parameters and remove empty query
    query_params = parse_qsl(parsed.query, keep_blank_values=True)
    query_params.sort()
    query = urlencode(query_params)

    return urlunparse((scheme, netloc, path, "", query, ""))


def compile_pattern(pattern: str) -> re.Pattern[str]:
    """Convert a wildcard pattern (* and **) to a compiled regex.

    - ``*`` matches any character except ``/``
    - ``**`` matches any character including ``/``

    The pattern is anchored at the end with ``$``.
    """
    parts = pattern.split("**")
    regex_parts: list[str] = []
    for part in parts:
        escaped = re.escape(part).replace(r"\*", "[^/]*")
        regex_parts.append(escaped)
    return re.compile(".*".join(regex_parts) + "$")


def matches_patterns(
    url: str, *, include: list[str] | None = None, exclude: list[str] | None = None
) -> bool:
    """Determine whether a URL should be crawled based on include/exclude patterns.

    Evaluation order (exclude always wins):
    1. If the URL matches any exclude pattern, return False.
    2. If include patterns exist and the URL matches none, return False.
    3. Otherwise return True.
    """
    if exclude and any(compile_pattern(pattern).search(url) for pattern in exclude):
        return False

    if include:
        return any(compile_pattern(pattern).search(url) for pattern in include)

    return True


def is_same_domain(url: str, base_url: str) -> bool:
    """Return True if *url* has the exact same domain as *base_url*."""
    url_host = (urlparse(url).hostname or "").lower()
    base_host = (urlparse(base_url).hostname or "").lower()
    return url_host == base_host


def is_subdomain(url: str, base_url: str) -> bool:
    """Return True if *url*'s domain is a subdomain of or equal to *base_url*'s domain."""
    url_host = (urlparse(url).hostname or "").lower()
    base_host = (urlparse(base_url).hostname or "").lower()
    return url_host == base_host or url_host.endswith(f".{base_host}")


def url_hash(url: str) -> str:
    """Return a truncated SHA-256 hash (16 hex chars) of the URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]
