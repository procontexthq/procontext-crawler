"""Tests for the CLI module."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

from proctx_crawler.cli import _build_parser, main

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestParser:
    """Verify argparse configuration for all subcommands."""

    def test_no_subcommand_prints_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        """No args prints help and exits with code 0 (returns None)."""
        main([])
        captured = capsys.readouterr()
        assert "proctx-crawler" in captured.out
        # Should mention subcommands
        assert "crawl" in captured.out

    def test_crawl_basic(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["crawl", "https://example.com"])
        assert args.command == "crawl"
        assert args.url == "https://example.com"
        assert args.limit == 10
        assert args.depth == 1000
        assert args.source == "links"
        assert args.format is None  # None means use default ["markdown"]
        assert args.render is False
        assert args.include is None
        assert args.exclude is None
        assert args.output is None
        assert args.quiet is False

    def test_crawl_with_all_options(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            [
                "crawl",
                "https://example.com",
                "--limit",
                "50",
                "--depth",
                "3",
                "--source",
                "llms_txt",
                "--format",
                "markdown",
                "--format",
                "html",
                "--render",
                "--include",
                "**/docs/**",
                "--exclude",
                "**/blog/**",
                "--output",
                "/tmp/out",
                "--quiet",
            ]
        )
        assert args.limit == 50
        assert args.depth == 3
        assert args.source == "llms_txt"
        assert args.format == ["markdown", "html"]
        assert args.render is True
        assert args.include == ["**/docs/**"]
        assert args.exclude == ["**/blog/**"]
        assert args.output == "/tmp/out"
        assert args.quiet is True

    def test_format_default(self) -> None:
        """When --format is not specified, args.format is None (default applied later)."""
        parser = _build_parser()
        args = parser.parse_args(["crawl", "https://example.com"])
        assert args.format is None

    def test_format_repeatable(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            [
                "crawl",
                "https://example.com",
                "--format",
                "markdown",
                "--format",
                "html",
            ]
        )
        assert args.format == ["markdown", "html"]

    def test_markdown_basic(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["markdown", "https://example.com"])
        assert args.command == "markdown"
        assert args.url == "https://example.com"
        assert args.render is False
        assert args.output is None

    def test_markdown_with_options(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            [
                "markdown",
                "https://example.com",
                "--render",
                "--output",
                "out.md",
            ]
        )
        assert args.render is True
        assert args.output == "out.md"

    def test_content_basic(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["content", "https://example.com"])
        assert args.command == "content"
        assert args.url == "https://example.com"
        assert args.render is False
        assert args.output is None

    def test_links_basic(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["links", "https://example.com"])
        assert args.command == "links"
        assert args.url == "https://example.com"
        assert args.render is False
        assert args.external is False

    def test_links_with_external(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["links", "https://example.com", "--external"])
        assert args.external is True

    def test_serve_defaults(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["serve"])
        assert args.command == "serve"
        assert args.host == "127.0.0.1"
        assert args.port == 8080

    def test_serve_custom(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["serve", "--host", "0.0.0.0", "--port", "3000"])
        assert args.host == "0.0.0.0"
        assert args.port == 3000


# ---------------------------------------------------------------------------
# Command execution tests
# ---------------------------------------------------------------------------


class TestCrawlCommand:
    """Test the crawl subcommand execution with mocked Crawler."""

    def test_crawl_executes(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        mock_result = MagicMock()
        mock_result.finished = 5
        mock_result.total = 5

        mock_crawler = AsyncMock()
        mock_crawler.crawl.return_value = mock_result
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        output_dir = str(tmp_path / "crawl-out")

        with (
            patch("proctx_crawler.cli.Crawler", return_value=mock_crawler),
            patch("proctx_crawler.cli.configure_logging"),
        ):
            main(["crawl", "https://example.com", "--output", output_dir, "--quiet"])

        mock_crawler.crawl.assert_awaited_once_with(
            "https://example.com",
            limit=10,
            depth=1000,
            source="links",
            formats=["markdown"],
            render=False,
            options=None,
        )

        captured = capsys.readouterr()
        assert output_dir in captured.out

    def test_crawl_with_patterns(self, tmp_path: Path) -> None:
        """Include/exclude patterns are passed as options dict."""
        mock_result = MagicMock()
        mock_result.finished = 1
        mock_result.total = 1

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

    def test_crawl_include_only(self, tmp_path: Path) -> None:
        """Only --include, no --exclude."""
        mock_result = MagicMock()
        mock_result.finished = 1
        mock_result.total = 1

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
                    "--output",
                    str(tmp_path),
                    "--quiet",
                ]
            )

        call_kwargs = mock_crawler.crawl.call_args[1]
        assert call_kwargs["options"] == {"include_patterns": ["**/docs/**"]}

    def test_crawl_exclude_only(self, tmp_path: Path) -> None:
        """Only --exclude, no --include."""
        mock_result = MagicMock()
        mock_result.finished = 1
        mock_result.total = 1

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
                    "--exclude",
                    "**/blog/**",
                    "--output",
                    str(tmp_path),
                    "--quiet",
                ]
            )

        call_kwargs = mock_crawler.crawl.call_args[1]
        assert call_kwargs["options"] == {"exclude_patterns": ["**/blog/**"]}

    def test_crawl_progress_to_stderr(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Without --quiet, progress messages go to stderr."""
        mock_result = MagicMock()
        mock_result.finished = 2
        mock_result.total = 2

        mock_crawler = AsyncMock()
        mock_crawler.crawl.return_value = mock_result
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("proctx_crawler.cli.Crawler", return_value=mock_crawler),
            patch("proctx_crawler.cli.configure_logging"),
        ):
            main(["crawl", "https://example.com", "--output", "/tmp/test-out"])

        captured = capsys.readouterr()
        assert "Starting crawl" in captured.err
        assert "Crawl complete" in captured.err

    def test_crawl_quiet_suppresses_progress(self, capsys: pytest.CaptureFixture[str]) -> None:
        """With --quiet, no progress messages on stderr."""
        mock_result = MagicMock()
        mock_result.finished = 1
        mock_result.total = 1

        mock_crawler = AsyncMock()
        mock_crawler.crawl.return_value = mock_result
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("proctx_crawler.cli.Crawler", return_value=mock_crawler),
            patch("proctx_crawler.cli.configure_logging"),
        ):
            main(["crawl", "https://example.com", "--output", "/tmp/test-out", "--quiet"])

        captured = capsys.readouterr()
        assert "Starting crawl" not in captured.err
        assert "Crawl complete" not in captured.err


class TestMarkdownCommand:
    """Test the markdown subcommand."""

    def test_markdown_to_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock_crawler = AsyncMock()
        mock_crawler.markdown.return_value = "# Hello World\n\nSome content."
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("proctx_crawler.cli.Crawler", return_value=mock_crawler),
            patch("proctx_crawler.cli.configure_logging"),
        ):
            main(["markdown", "https://example.com"])

        mock_crawler.markdown.assert_awaited_once_with("https://example.com", render=False)

        captured = capsys.readouterr()
        assert "# Hello World" in captured.out
        assert "Some content." in captured.out

    def test_markdown_to_file(self, tmp_path: Path) -> None:
        mock_crawler = AsyncMock()
        mock_crawler.markdown.return_value = "# File Content"
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        out_file = tmp_path / "output.md"

        with (
            patch("proctx_crawler.cli.Crawler", return_value=mock_crawler),
            patch("proctx_crawler.cli.configure_logging"),
        ):
            main(["markdown", "https://example.com", "--output", str(out_file)])

        assert out_file.read_text(encoding="utf-8") == "# File Content"

    def test_markdown_with_render(self) -> None:
        mock_crawler = AsyncMock()
        mock_crawler.markdown.return_value = "rendered content"
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("proctx_crawler.cli.Crawler", return_value=mock_crawler),
            patch("proctx_crawler.cli.configure_logging"),
        ):
            main(["markdown", "https://example.com", "--render"])

        mock_crawler.markdown.assert_awaited_once_with("https://example.com", render=True)


class TestContentCommand:
    """Test the content subcommand."""

    def test_content_to_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock_crawler = AsyncMock()
        mock_crawler.content.return_value = "<html><body>Hello</body></html>"
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

    def test_content_to_file(self, tmp_path: Path) -> None:
        mock_crawler = AsyncMock()
        mock_crawler.content.return_value = "<html><body>Saved</body></html>"
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        out_file = tmp_path / "page.html"

        with (
            patch("proctx_crawler.cli.Crawler", return_value=mock_crawler),
            patch("proctx_crawler.cli.configure_logging"),
        ):
            main(["content", "https://example.com", "--output", str(out_file)])

        assert "<html>" in out_file.read_text(encoding="utf-8")


class TestLinksCommand:
    """Test the links subcommand."""

    def test_links_basic(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock_crawler = AsyncMock()
        mock_crawler.links.return_value = [
            "https://example.com/page1",
            "https://example.com/page2",
        ]
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("proctx_crawler.cli.Crawler", return_value=mock_crawler),
            patch("proctx_crawler.cli.configure_logging"),
        ):
            main(["links", "https://example.com"])

        mock_crawler.links.assert_awaited_once_with(
            "https://example.com",
            render=False,
            exclude_external_links=True,
        )

        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert lines == ["https://example.com/page1", "https://example.com/page2"]

    def test_links_with_external(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--external flag passes exclude_external_links=False."""
        mock_crawler = AsyncMock()
        mock_crawler.links.return_value = [
            "https://example.com/page1",
            "https://other.com/page",
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

    def test_links_without_external(self) -> None:
        """Without --external, exclude_external_links=True."""
        mock_crawler = AsyncMock()
        mock_crawler.links.return_value = []
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("proctx_crawler.cli.Crawler", return_value=mock_crawler),
            patch("proctx_crawler.cli.configure_logging"),
        ):
            main(["links", "https://example.com"])

        mock_crawler.links.assert_awaited_once_with(
            "https://example.com",
            render=False,
            exclude_external_links=True,
        )


class TestServeCommand:
    """Test the serve subcommand."""

    def test_serve_calls_uvicorn(self) -> None:
        """Serve command dispatches to _run_serve with correct host/port."""
        with (
            patch("proctx_crawler.cli.configure_logging"),
            patch("proctx_crawler.cli._run_serve") as mock_serve,
        ):
            main(["serve", "--host", "0.0.0.0", "--port", "3000"])

        mock_serve.assert_called_once()
        call_args = mock_serve.call_args[0][0]
        assert call_args.host == "0.0.0.0"
        assert call_args.port == 3000

    def test_serve_default_host_port(self) -> None:
        """Default serve args use 127.0.0.1:8080."""
        with (
            patch("proctx_crawler.cli.configure_logging"),
            patch("proctx_crawler.cli._run_serve") as mock_serve,
        ):
            main(["serve"])

        mock_serve.assert_called_once()
        call_args = mock_serve.call_args[0][0]
        assert call_args.host == "127.0.0.1"
        assert call_args.port == 8080

    def test_run_serve_calls_uvicorn(self) -> None:
        """_run_serve imports uvicorn and create_app, then calls uvicorn.run."""
        import types

        from proctx_crawler.cli import _run_serve

        mock_app = MagicMock()
        mock_uvicorn = types.ModuleType("uvicorn")
        mock_uvicorn.run = MagicMock()  # type: ignore[attr-defined]

        args = MagicMock(host="0.0.0.0", port=9090)

        with (
            patch.dict("sys.modules", {"uvicorn": mock_uvicorn}),
            patch("proctx_crawler.api.app.create_app", return_value=mock_app),
        ):
            _run_serve(args)

        mock_uvicorn.run.assert_called_once_with(mock_app, host="0.0.0.0", port=9090)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------


class TestLoggingConfig:
    """Verify configure_logging is called with appropriate level."""

    def test_quiet_sets_warning_level(self) -> None:
        mock_crawler = AsyncMock()
        mock_crawler.crawl.return_value = MagicMock(finished=0, total=0)
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("proctx_crawler.cli.Crawler", return_value=mock_crawler),
            patch("proctx_crawler.cli.configure_logging") as mock_log_config,
        ):
            main(["crawl", "https://example.com", "--output", "/tmp/out", "--quiet"])

        mock_log_config.assert_called_once_with(level="WARNING")

    def test_normal_sets_info_level(self) -> None:
        mock_crawler = AsyncMock()
        mock_crawler.crawl.return_value = MagicMock(finished=0, total=0)
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("proctx_crawler.cli.Crawler", return_value=mock_crawler),
            patch("proctx_crawler.cli.configure_logging") as mock_log_config,
        ):
            main(["crawl", "https://example.com", "--output", "/tmp/out"])

        mock_log_config.assert_called_once_with(level="INFO")

    def test_serve_uses_info_level(self) -> None:
        with (
            patch("proctx_crawler.cli.configure_logging") as mock_log_config,
            patch("proctx_crawler.cli._run_serve"),
        ):
            main(["serve"])

        mock_log_config.assert_called_once_with(level="INFO")
