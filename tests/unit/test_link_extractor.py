"""Tests for link extraction from HTML."""

from __future__ import annotations

from proctx_crawler.extractors.links import extract_links

BASE = "https://example.com/docs/page"


class TestBasicExtraction:
    def test_absolute_links(self) -> None:
        html = '<a href="https://example.com/other">Link</a>'
        result = extract_links(html, BASE)
        assert result == ["https://example.com/other"]

    def test_multiple_links(self) -> None:
        html = """
        <a href="https://example.com/a">A</a>
        <a href="https://example.com/b">B</a>
        """
        result = extract_links(html, BASE)
        assert result == ["https://example.com/a", "https://example.com/b"]


class TestRelativeUrlResolution:
    def test_relative_path(self) -> None:
        html = '<a href="other">Link</a>'
        result = extract_links(html, BASE)
        assert result == ["https://example.com/docs/other"]

    def test_absolute_path(self) -> None:
        html = '<a href="/root/page">Link</a>'
        result = extract_links(html, BASE)
        assert result == ["https://example.com/root/page"]

    def test_protocol_relative(self) -> None:
        html = '<a href="//other.com/page">Link</a>'
        result = extract_links(html, BASE)
        assert result == ["https://other.com/page"]

    def test_parent_directory(self) -> None:
        html = '<a href="../sibling">Link</a>'
        result = extract_links(html, BASE)
        assert result == ["https://example.com/sibling"]


class TestSkippedLinks:
    def test_fragment_only_skipped(self) -> None:
        html = '<a href="#section">Skip</a>'
        result = extract_links(html, BASE)
        assert result == []

    def test_mailto_skipped(self) -> None:
        html = '<a href="mailto:test@example.com">Email</a>'
        result = extract_links(html, BASE)
        assert result == []

    def test_javascript_skipped(self) -> None:
        html = '<a href="javascript:void(0)">JS</a>'
        result = extract_links(html, BASE)
        assert result == []

    def test_ftp_scheme_filtered(self) -> None:
        html = '<a href="ftp://files.example.com/data">FTP</a>'
        result = extract_links(html, BASE)
        assert result == []


class TestDeduplication:
    def test_duplicate_urls_deduplicated(self) -> None:
        html = """
        <a href="https://example.com/page">Link 1</a>
        <a href="https://example.com/page">Link 2</a>
        """
        result = extract_links(html, BASE)
        assert result == ["https://example.com/page"]

    def test_fragments_removed_for_dedup(self) -> None:
        html = """
        <a href="https://example.com/page#section1">Section 1</a>
        <a href="https://example.com/page#section2">Section 2</a>
        """
        result = extract_links(html, BASE)
        assert result == ["https://example.com/page"]

    def test_order_preserved(self) -> None:
        html = """
        <a href="https://example.com/c">C</a>
        <a href="https://example.com/a">A</a>
        <a href="https://example.com/b">B</a>
        """
        result = extract_links(html, BASE)
        assert result == [
            "https://example.com/c",
            "https://example.com/a",
            "https://example.com/b",
        ]


class TestEdgeCases:
    def test_external_links_included(self) -> None:
        html = '<a href="https://other.com/page">External</a>'
        result = extract_links(html, BASE)
        assert result == ["https://other.com/page"]

    def test_empty_page(self) -> None:
        result = extract_links("", BASE)
        assert result == []

    def test_no_href_attribute(self) -> None:
        html = "<a>No href</a>"
        result = extract_links(html, BASE)
        assert result == []

    def test_empty_href(self) -> None:
        html = '<a href="">Empty</a>'
        result = extract_links(html, BASE)
        # Empty href resolves to base URL
        assert len(result) == 1
        assert result[0].startswith("https://example.com")

    def test_links_with_query_params(self) -> None:
        html = '<a href="https://example.com/page?a=1&b=2">Link</a>'
        result = extract_links(html, BASE)
        assert result == ["https://example.com/page?a=1&b=2"]
