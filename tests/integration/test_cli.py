"""Integration tests for the CLI module.

These tests invoke the CLI main() function directly with argument lists,
mocking the Crawler class to avoid real HTTP calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

from proctx_crawler.cli import main

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


# ---------------------------------------------------------------------------
# No subcommand -> help text
# ---------------------------------------------------------------------------


class TestNoSubcommand:
    """Verify that calling CLI with no subcommand prints help text."""

    def test_no_args_prints_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        main([])
        captured = capsys.readouterr()
        assert "proctx-crawler" in captured.out
        assert "crawl" in captured.out
        assert "markdown" in captured.out
        assert "content" in captured.out
        assert "links" in captured.out
        assert "serve" in captured.out


# ---------------------------------------------------------------------------
# crawl command
# ---------------------------------------------------------------------------


class TestCrawlCommand:
    """Test the crawl subcommand prints output directory."""

    def test_crawl_prints_output_dir(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        mock_result = MagicMock()
        mock_result.finished = 3
        mock_result.total = 3

        mock_crawler = AsyncMock()
        mock_crawler.crawl.return_value = mock_result
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        output_dir = str(tmp_path / "crawl-output")

        with (
            patch("proctx_crawler.cli.Crawler", return_value=mock_crawler),
            patch("proctx_crawler.cli.configure_logging"),
        ):
            main(["crawl", "https://example.com", "--output", output_dir, "--quiet"])

        captured = capsys.readouterr()
        assert output_dir in captured.out

        # Verify Crawler.crawl was actually called
        mock_crawler.crawl.assert_awaited_once()

    def test_crawl_with_include_exclude(self, tmp_path: Path) -> None:
        """Verify include/exclude patterns are forwarded to Crawler.crawl()."""
        mock_result = MagicMock(finished=1, total=1)

        mock_crawler = AsyncMock()
        mock_crawler.crawl.return_value = mock_result
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("proctx_crawler.cli.Crawler", return_value=mock_crawler),
            patch("proctx_crawler.cli.configure_logging"),
        ):
            main(
                [
                    "crawl",
                    "https://example.com",
                    "--include",
                    "**/docs/**",
                    "--exclude",
                    "**/blog/**",
                    "--output",
                    str(tmp_path),
                    "--quiet",
                ]
            )

        call_kwargs = mock_crawler.crawl.call_args[1]
        assert call_kwargs["options"] == {
            "include_patterns": ["**/docs/**"],
            "exclude_patterns": ["**/blog/**"],
        }


# ---------------------------------------------------------------------------
# markdown command
# ---------------------------------------------------------------------------


class TestMarkdownCommand:
    """Test the markdown subcommand."""

    def test_markdown_to_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock_crawler = AsyncMock()
        mock_crawler.markdown.return_value = "# Integration Test\n\nMarkdown output."
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("proctx_crawler.cli.Crawler", return_value=mock_crawler),
            patch("proctx_crawler.cli.configure_logging"),
        ):
            main(["markdown", "https://example.com"])

        mock_crawler.markdown.assert_awaited_once_with("https://example.com", render=False)

        captured = capsys.readouterr()
        assert "# Integration Test" in captured.out
        assert "Markdown output." in captured.out

    def test_markdown_to_file(self, tmp_path: Path) -> None:
        mock_crawler = AsyncMock()
        mock_crawler.markdown.return_value = "# File Output"
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        out_file = tmp_path / "output.md"

        with (
            patch("proctx_crawler.cli.Crawler", return_value=mock_crawler),
            patch("proctx_crawler.cli.configure_logging"),
        ):
            main(["markdown", "https://example.com", "--output", str(out_file)])

        assert out_file.exists()
        assert out_file.read_text(encoding="utf-8") == "# File Output"


# ---------------------------------------------------------------------------
# content command
# ---------------------------------------------------------------------------


class TestContentCommand:
    """Test the content subcommand."""

    def test_content_to_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock_crawler = AsyncMock()
        mock_crawler.content.return_value = "<html><body><p>Content output</p></body></html>"
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("proctx_crawler.cli.Crawler", return_value=mock_crawler),
            patch("proctx_crawler.cli.configure_logging"),
        ):
            main(["content", "https://example.com"])

        mock_crawler.content.assert_awaited_once_with("https://example.com", render=False)

        captured = capsys.readouterr()
        assert "<html>" in captured.out
        assert "Content output" in captured.out


# ---------------------------------------------------------------------------
# links command
# ---------------------------------------------------------------------------


class TestLinksCommand:
    """Test the links subcommand."""

    def test_links_one_per_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock_crawler = AsyncMock()
        mock_crawler.links.return_value = [
            "https://example.com/page1",
            "https://example.com/page2",
            "https://example.com/page3",
        ]
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("proctx_crawler.cli.Crawler", return_value=mock_crawler),
            patch("proctx_crawler.cli.configure_logging"),
        ):
            main(["links", "https://example.com"])

        # Default: exclude_external_links=True (no --external)
        mock_crawler.links.assert_awaited_once_with(
            "https://example.com",
            render=False,
            exclude_external_links=True,
        )

        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert lines == [
            "https://example.com/page1",
            "https://example.com/page2",
            "https://example.com/page3",
        ]

    def test_links_with_external(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--external flag passes exclude_external_links=False."""
        mock_crawler = AsyncMock()
        mock_crawler.links.return_value = [
            "https://example.com/page1",
            "https://other.com/ext",
        ]
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("proctx_crawler.cli.Crawler", return_value=mock_crawler),
            patch("proctx_crawler.cli.configure_logging"),
        ):
            main(["links", "https://example.com", "--external"])

        mock_crawler.links.assert_awaited_once_with(
            "https://example.com",
            render=False,
            exclude_external_links=False,
        )

        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert "https://other.com/ext" in lines


# ---------------------------------------------------------------------------
# serve command
# ---------------------------------------------------------------------------


class TestServeCommand:
    """Test the serve subcommand."""

    def test_serve_calls_uvicorn_with_correct_args(self) -> None:
        with (
            patch("proctx_crawler.cli.configure_logging"),
            patch("proctx_crawler.cli._run_serve") as mock_serve,
        ):
            main(["serve", "--host", "0.0.0.0", "--port", "9000"])

        mock_serve.assert_called_once()
        args = mock_serve.call_args[0][0]
        assert args.host == "0.0.0.0"
        assert args.port == 9000

    def test_serve_defaults(self) -> None:
        """Without flags, host/port fall through to Settings defaults (None on args)."""
        with (
            patch("proctx_crawler.cli.configure_logging"),
            patch("proctx_crawler.cli._run_serve") as mock_serve,
        ):
            main(["serve"])

        args = mock_serve.call_args[0][0]
        assert args.host is None
        assert args.port is None
