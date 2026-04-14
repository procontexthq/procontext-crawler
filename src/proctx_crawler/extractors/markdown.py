"""HTML-to-Markdown conversion with content selection heuristic."""

from __future__ import annotations

from bs4 import BeautifulSoup
from markdownify import markdownify as md

_NON_CONTENT_TAGS = ["nav", "header", "footer", "aside", "script", "style", "noscript"]


def html_to_markdown(html: str) -> str:
    """Convert HTML to clean Markdown.

    Content selection heuristic:
    1. Remove non-content elements: nav, header, footer, aside, script, style, noscript
    2. Prefer <main> or <article> if present, otherwise use <body>, otherwise full HTML
    3. Convert to Markdown using markdownify with ATX-style headings
    """
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(_NON_CONTENT_TAGS):
        tag.decompose()

    main = soup.find("main") or soup.find("article") or soup.find("body") or soup
    result: str = md(str(main), heading_style="ATX", strip=["img"])
    return result
