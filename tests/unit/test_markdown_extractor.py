"""Tests for HTML-to-Markdown conversion."""

from __future__ import annotations

from proctx_crawler.extractors.markdown import html_to_markdown


class TestHtmlToMarkdownBasic:
    def test_heading_and_paragraph(self) -> None:
        html = "<h1>Title</h1><p>Hello world.</p>"
        result = html_to_markdown(html)
        assert "# Title" in result
        assert "Hello world." in result

    def test_nested_html_with_lists(self) -> None:
        html = """
        <div>
            <h2>Section</h2>
            <ul>
                <li>Item one</li>
                <li>Item two</li>
            </ul>
        </div>
        """
        result = html_to_markdown(html)
        assert "## Section" in result
        assert "Item one" in result
        assert "Item two" in result

    def test_code_blocks(self) -> None:
        html = "<pre><code>print('hello')</code></pre>"
        result = html_to_markdown(html)
        assert "print('hello')" in result

    def test_links_preserved(self) -> None:
        html = '<p>Visit <a href="https://example.com">Example</a>.</p>'
        result = html_to_markdown(html)
        assert "Example" in result
        assert "https://example.com" in result


class TestContentSelection:
    def test_main_preferred(self) -> None:
        html = """
        <html>
        <body>
            <nav><a href="/">Home</a></nav>
            <main><h1>Main Content</h1><p>Important text.</p></main>
            <footer>Footer stuff</footer>
        </body>
        </html>
        """
        result = html_to_markdown(html)
        assert "Main Content" in result
        assert "Important text." in result
        # nav and footer should be stripped before content selection
        assert "Home" not in result
        assert "Footer stuff" not in result

    def test_article_used_when_no_main(self) -> None:
        html = """
        <html>
        <body>
            <nav><a href="/">Home</a></nav>
            <article><h1>Article Content</h1><p>Article text.</p></article>
            <aside>Sidebar</aside>
        </body>
        </html>
        """
        result = html_to_markdown(html)
        assert "Article Content" in result
        assert "Article text." in result
        assert "Home" not in result
        assert "Sidebar" not in result

    def test_body_fallback(self) -> None:
        html = """
        <html>
        <body>
            <div><h1>Body Content</h1><p>Body text.</p></div>
        </body>
        </html>
        """
        result = html_to_markdown(html)
        assert "Body Content" in result
        assert "Body text." in result

    def test_full_soup_fallback(self) -> None:
        # No <main>, <article>, or <body>
        html = "<h1>Title</h1><p>Paragraph.</p>"
        result = html_to_markdown(html)
        assert "Title" in result
        assert "Paragraph." in result


class TestNonContentStripping:
    def test_nav_stripped(self) -> None:
        html = "<nav><a href='/'>Home</a></nav><p>Content</p>"
        result = html_to_markdown(html)
        assert "Home" not in result
        assert "Content" in result

    def test_script_stripped(self) -> None:
        html = "<script>var x = 1;</script><p>Content</p>"
        result = html_to_markdown(html)
        assert "var x" not in result
        assert "Content" in result

    def test_style_stripped(self) -> None:
        html = "<style>body { color: red; }</style><p>Content</p>"
        result = html_to_markdown(html)
        assert "color: red" not in result
        assert "Content" in result

    def test_header_stripped(self) -> None:
        html = "<header><h1>Site Title</h1></header><main><p>Content</p></main>"
        result = html_to_markdown(html)
        assert "Site Title" not in result
        assert "Content" in result

    def test_footer_stripped(self) -> None:
        html = "<main><p>Content</p></main><footer>Copyright 2024</footer>"
        result = html_to_markdown(html)
        assert "Copyright" not in result
        assert "Content" in result

    def test_aside_stripped(self) -> None:
        html = "<main><p>Content</p></main><aside>Related links</aside>"
        result = html_to_markdown(html)
        assert "Related links" not in result
        assert "Content" in result

    def test_noscript_stripped(self) -> None:
        html = "<noscript>Enable JS</noscript><p>Content</p>"
        result = html_to_markdown(html)
        assert "Enable JS" not in result
        assert "Content" in result


class TestEdgeCases:
    def test_empty_html(self) -> None:
        result = html_to_markdown("")
        # Should not crash, returns empty or whitespace
        assert isinstance(result, str)

    def test_malformed_html(self) -> None:
        html = "<h1>Unclosed heading<p>Paragraph without close<div>Nested"
        result = html_to_markdown(html)
        # BeautifulSoup is lenient; should not crash
        assert "Unclosed heading" in result
        assert "Paragraph without close" in result

    def test_complex_nested_html(self) -> None:
        html = """
        <html>
        <body>
            <nav><ul><li>Nav 1</li><li>Nav 2</li></ul></nav>
            <main>
                <h1>Guide</h1>
                <p>This is a <strong>bold</strong> and <em>italic</em> guide.</p>
                <h2>Code Example</h2>
                <pre><code>def foo():
    return 42</code></pre>
                <h2>Links</h2>
                <ul>
                    <li><a href="https://example.com">Example</a></li>
                    <li><a href="https://docs.example.com">Docs</a></li>
                </ul>
            </main>
            <footer><p>Footer text</p></footer>
        </body>
        </html>
        """
        result = html_to_markdown(html)
        assert "# Guide" in result
        assert "**bold**" in result
        assert "*italic*" in result
        assert "def foo():" in result
        assert "Nav 1" not in result
        assert "Footer text" not in result
