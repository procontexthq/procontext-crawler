"""Tests for URL discovery strategies: seed URL generation and page link filtering."""

from __future__ import annotations

import anyio

from proctx_crawler.core.discovery import discover_page_links, discover_seed_urls, parse_llms_txt

# ---------------------------------------------------------------------------
# parse_llms_txt
# ---------------------------------------------------------------------------


class TestParseLlmsTxt:
    def test_markdown_links_extracted(self) -> None:
        text = """# Documentation
- [Getting Started](https://docs.example.com/start)
- [API Reference](https://docs.example.com/api)
"""
        result = parse_llms_txt(text)
        assert "https://docs.example.com/start" in result
        assert "https://docs.example.com/api" in result

    def test_bare_urls_extracted(self) -> None:
        text = """# Links
https://example.com/page1
https://example.com/page2
"""
        result = parse_llms_txt(text)
        assert "https://example.com/page1" in result
        assert "https://example.com/page2" in result

    def test_mixed_content(self) -> None:
        text = """# llms.txt

## Docs
- [Guide](https://docs.example.com/guide)

## Optional
https://docs.example.com/advanced

Some descriptive text about the project.
"""
        result = parse_llms_txt(text)
        assert "https://docs.example.com/guide" in result
        assert "https://docs.example.com/advanced" in result
        assert len(result) == 2

    def test_empty_file(self) -> None:
        result = parse_llms_txt("")
        assert result == []

    def test_deduplication(self) -> None:
        text = """
- [Page](https://example.com/page)
- [Page Again](https://example.com/page)
https://example.com/page
"""
        result = parse_llms_txt(text)
        assert result.count("https://example.com/page") == 1

    def test_non_http_urls_ignored(self) -> None:
        text = """
ftp://files.example.com/data
- [Link](https://example.com/page)
"""
        result = parse_llms_txt(text)
        assert len(result) == 1
        assert result[0] == "https://example.com/page"

    def test_bare_url_not_duplicated_from_markdown_link(self) -> None:
        """If a URL appears both as a markdown link and bare, it appears once."""
        text = """
- [Docs](https://docs.example.com/guide)
https://docs.example.com/guide
"""
        result = parse_llms_txt(text)
        assert result == ["https://docs.example.com/guide"]

    def test_http_urls_supported(self) -> None:
        text = "http://example.com/insecure"
        result = parse_llms_txt(text)
        assert result == ["http://example.com/insecure"]

    def test_urls_in_descriptive_text(self) -> None:
        text = "Check out https://example.com/page for more info."
        result = parse_llms_txt(text)
        assert "https://example.com/page" in result


# ---------------------------------------------------------------------------
# discover_seed_urls
# ---------------------------------------------------------------------------


class TestDiscoverSeedUrls:
    def test_links_source_returns_url(self) -> None:
        async def _test() -> None:
            result = await discover_seed_urls("https://example.com", "links")
            assert result == ["https://example.com"]

        anyio.run(_test)

    def test_llms_txt_with_html_parses_it(self) -> None:
        async def _test() -> None:
            html = "- [Doc](https://docs.example.com/page)"
            result = await discover_seed_urls("https://example.com/llms.txt", "llms_txt", html=html)
            assert "https://docs.example.com/page" in result

        anyio.run(_test)

    def test_llms_txt_without_html_returns_url(self) -> None:
        async def _test() -> None:
            result = await discover_seed_urls("https://example.com/llms.txt", "llms_txt")
            assert result == ["https://example.com/llms.txt"]

        anyio.run(_test)

    def test_unknown_source_returns_url(self) -> None:
        async def _test() -> None:
            result = await discover_seed_urls("https://example.com", "sitemaps")
            assert result == ["https://example.com"]

        anyio.run(_test)


# ---------------------------------------------------------------------------
# discover_page_links
# ---------------------------------------------------------------------------


START_URL = "https://example.com/docs"


class TestDiscoverPageLinks:
    def test_same_domain_only_by_default(self) -> None:
        html = """
        <a href="https://example.com/docs/page1">Same</a>
        <a href="https://other.com/page">External</a>
        <a href="https://sub.example.com/page">Subdomain</a>
        """
        result = discover_page_links(html, START_URL, start_url=START_URL)
        assert "https://example.com/docs/page1" in result
        assert "https://other.com/page" not in result
        assert "https://sub.example.com/page" not in result

    def test_include_subdomains(self) -> None:
        html = """
        <a href="https://example.com/page">Same</a>
        <a href="https://sub.example.com/page">Subdomain</a>
        <a href="https://other.com/page">External</a>
        """
        result = discover_page_links(
            html,
            START_URL,
            include_subdomains=True,
            start_url=START_URL,
        )
        assert "https://example.com/page" in result
        assert "https://sub.example.com/page" in result
        assert "https://other.com/page" not in result

    def test_include_external_links(self) -> None:
        html = """
        <a href="https://example.com/page">Same</a>
        <a href="https://other.com/page">External</a>
        """
        result = discover_page_links(
            html,
            START_URL,
            include_external_links=True,
            start_url=START_URL,
        )
        assert "https://example.com/page" in result
        assert "https://other.com/page" in result

    def test_include_patterns(self) -> None:
        html = """
        <a href="https://example.com/docs/guide">Guide</a>
        <a href="https://example.com/blog/post">Blog</a>
        """
        result = discover_page_links(
            html,
            START_URL,
            include_patterns=["**/docs/**"],
            start_url=START_URL,
        )
        assert "https://example.com/docs/guide" in result
        assert "https://example.com/blog/post" not in result

    def test_exclude_patterns(self) -> None:
        html = """
        <a href="https://example.com/docs/guide">Guide</a>
        <a href="https://example.com/docs/api/internal">Internal</a>
        """
        result = discover_page_links(
            html,
            START_URL,
            exclude_patterns=["**/api/**"],
            start_url=START_URL,
        )
        assert "https://example.com/docs/guide" in result
        assert "https://example.com/docs/api/internal" not in result

    def test_exclude_wins_over_include(self) -> None:
        html = """
        <a href="https://example.com/docs/api/internal">API Internal</a>
        <a href="https://example.com/docs/guide">Guide</a>
        """
        result = discover_page_links(
            html,
            START_URL,
            include_patterns=["**/docs/**"],
            exclude_patterns=["**/api/**"],
            start_url=START_URL,
        )
        assert "https://example.com/docs/guide" in result
        assert "https://example.com/docs/api/internal" not in result

    def test_empty_html(self) -> None:
        result = discover_page_links("", START_URL, start_url=START_URL)
        assert result == []

    def test_all_links_filtered_returns_empty(self) -> None:
        html = '<a href="https://other.com/page">External</a>'
        result = discover_page_links(html, START_URL, start_url=START_URL)
        assert result == []
