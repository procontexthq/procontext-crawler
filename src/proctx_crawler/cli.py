"""Command-line interface for ProContext Crawler."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

import anyio
import structlog

from proctx_crawler.config import Settings, load_settings
from proctx_crawler.crawler import Crawler
from proctx_crawler.logging_config import configure_logging

if TYPE_CHECKING:
    from collections.abc import Sequence


log: structlog.stdlib.BoundLogger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------


def _add_storage_args(parser: argparse.ArgumentParser) -> None:
    """Attach shared ``--db-path`` and ``--output-dir`` flags to *parser*.

    These override the corresponding :class:`Settings` fields. When omitted,
    the values flow from environment variables (``PROCTX_CRAWLER__*``), then
    ``proctx-crawler.yaml``, then built-in defaults.
    """
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        metavar="PATH",
        help="SQLite metadata store path (overrides PROCTX_CRAWLER__DB_PATH)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        metavar="PATH",
        help="Directory for crawl content (overrides PROCTX_CRAWLER__OUTPUT_DIR)",
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="proctx-crawler",
        description="Self-hosted crawl API for extracting structured documentation from websites.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # -- crawl ---------------------------------------------------------------
    crawl_parser = subparsers.add_parser("crawl", help="Start a multi-page crawl")
    crawl_parser.add_argument("url", help="Starting URL")
    crawl_parser.add_argument("--limit", type=int, default=10, help="Max pages to crawl")
    crawl_parser.add_argument("--depth", type=int, default=1000, help="Max link depth")
    crawl_parser.add_argument(
        "--source",
        choices=["links", "llms_txt"],
        default="links",
        help="Discovery source (default: links)",
    )
    crawl_parser.add_argument(
        "--format",
        action="append",
        choices=["markdown", "html"],
        help="Output format (repeatable, default: markdown)",
    )
    crawl_parser.add_argument(
        "--render", action="store_true", default=False, help="Enable Playwright rendering"
    )
    crawl_parser.add_argument("--include", action="append", help="URL include pattern (repeatable)")
    crawl_parser.add_argument("--exclude", action="append", help="URL exclude pattern (repeatable)")
    crawl_parser.add_argument(
        "--quiet", action="store_true", default=False, help="Suppress progress messages"
    )
    _add_storage_args(crawl_parser)

    # -- markdown ------------------------------------------------------------
    md_parser = subparsers.add_parser("markdown", help="Extract Markdown from a single page")
    md_parser.add_argument("url", help="Target URL")
    md_parser.add_argument(
        "--render", action="store_true", default=False, help="Enable Playwright rendering"
    )
    md_parser.add_argument("--output", help="Write to file instead of stdout")
    _add_storage_args(md_parser)

    # -- content -------------------------------------------------------------
    content_parser = subparsers.add_parser("content", help="Fetch HTML from a single page")
    content_parser.add_argument("url", help="Target URL")
    content_parser.add_argument(
        "--render", action="store_true", default=False, help="Enable Playwright rendering"
    )
    content_parser.add_argument("--output", help="Write to file instead of stdout")
    _add_storage_args(content_parser)

    # -- links ---------------------------------------------------------------
    links_parser = subparsers.add_parser("links", help="Extract links from a single page")
    links_parser.add_argument("url", help="Target URL")
    links_parser.add_argument(
        "--render", action="store_true", default=False, help="Enable Playwright rendering"
    )
    links_parser.add_argument(
        "--external", action="store_true", default=False, help="Include external links"
    )
    _add_storage_args(links_parser)

    # -- serve ---------------------------------------------------------------
    serve_parser = subparsers.add_parser("serve", help="Start the HTTP API server")
    serve_parser.add_argument(
        "--host", default=None, help="Bind address (overrides PROCTX_CRAWLER__SERVER_HOST)"
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Bind port (overrides PROCTX_CRAWLER__SERVER_PORT)",
    )
    _add_storage_args(serve_parser)

    return parser


# ---------------------------------------------------------------------------
# Settings resolution
# ---------------------------------------------------------------------------


def _resolve_settings(args: argparse.Namespace) -> Settings:
    """Load base settings and apply CLI overrides from *args*.

    CLI flags take highest priority, then env vars (via ``load_settings``),
    then YAML, then built-in defaults.
    """
    overrides: dict[str, object] = {}
    if getattr(args, "db_path", None) is not None:
        overrides["db_path"] = args.db_path
    if getattr(args, "output_dir", None) is not None:
        overrides["output_dir"] = args.output_dir
    if getattr(args, "host", None) is not None:
        overrides["server_host"] = args.host
    if getattr(args, "port", None) is not None:
        overrides["server_port"] = args.port

    base = load_settings()
    if not overrides:
        return base
    return base.model_copy(update=overrides)


# ---------------------------------------------------------------------------
# Async command handlers
# ---------------------------------------------------------------------------


async def _run_crawl(args: argparse.Namespace) -> None:
    """Execute the crawl subcommand."""
    settings = _resolve_settings(args)
    raw_formats: list[str] = args.format or ["markdown"]
    formats = cast("list[Literal['markdown', 'html']]", raw_formats)

    options: dict[str, list[str]] | None = None
    if args.include or args.exclude:
        options = {}
        if args.include:
            options["include_patterns"] = args.include
        if args.exclude:
            options["exclude_patterns"] = args.exclude

    if not args.quiet:
        print(f"Starting crawl: {args.url}", file=sys.stderr)  # noqa: T201

    async with Crawler(settings=settings) as crawler:
        result = await crawler.crawl(
            args.url,
            limit=args.limit,
            depth=args.depth,
            source=args.source,
            formats=formats,
            render=args.render,
            options=options,
        )

    if not args.quiet:
        print(  # noqa: T201
            f"Crawl complete: {result.finished}/{result.total} pages",
            file=sys.stderr,
        )

    print(str(settings.output_dir))  # noqa: T201


async def _run_markdown(args: argparse.Namespace) -> None:
    """Execute the markdown subcommand."""
    settings = _resolve_settings(args)
    async with Crawler(settings=settings) as crawler:
        text = await crawler.markdown(args.url, render=args.render)

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)  # noqa: T201


async def _run_content(args: argparse.Namespace) -> None:
    """Execute the content subcommand."""
    settings = _resolve_settings(args)
    async with Crawler(settings=settings) as crawler:
        text = await crawler.content(args.url, render=args.render)

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)  # noqa: T201


async def _run_links(args: argparse.Namespace) -> None:
    """Execute the links subcommand."""
    settings = _resolve_settings(args)
    exclude_external = not args.external

    async with Crawler(settings=settings) as crawler:
        urls = await crawler.links(
            args.url,
            render=args.render,
            exclude_external_links=exclude_external,
        )

    for url in urls:
        print(url)  # noqa: T201


async def _async_command(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate async handler based on the subcommand."""
    handlers: dict[str, object] = {
        "crawl": _run_crawl,
        "markdown": _run_markdown,
        "content": _run_content,
        "links": _run_links,
    }
    handler = handlers[args.command]
    await handler(args)  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Serve (synchronous — uvicorn.run blocks)
# ---------------------------------------------------------------------------


def _run_serve(args: argparse.Namespace) -> None:
    """Start the HTTP API server via uvicorn."""
    # Deferred imports: uvicorn and the API app are only needed when the
    # ``serve`` subcommand is invoked, so we avoid a top-level import that
    # would fail for users who only use the crawl/markdown/content/links
    # subcommands and haven't installed the API layer yet.
    import uvicorn

    from proctx_crawler.api.app import create_app

    settings = _resolve_settings(args)
    app = create_app(settings=settings)
    uvicorn.run(app, host=settings.server_host, port=settings.server_port)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entry point registered as ``proctx-crawler``."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return

    quiet = getattr(args, "quiet", False)
    configure_logging(level="WARNING" if quiet else "INFO")

    if args.command == "serve":
        _run_serve(args)
    else:
        anyio.run(_async_command, args)
