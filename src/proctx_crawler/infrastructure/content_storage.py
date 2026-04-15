"""Filesystem storage for extracted page content and job manifests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from pathlib import Path

log = structlog.get_logger()


@dataclass
class ExtractedContent:
    """Container for extracted page content."""

    markdown: str | None = None
    html: str | None = None


class ContentStorage:
    """Read and write crawled content files on the local filesystem.

    Each job gets its own directory under *output_dir*.  Individual pages are
    stored as ``<url_hash>.md`` and/or ``<url_hash>.html``.  A
    ``manifest.json`` file maps hashes back to their source URLs.
    """

    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir

    def job_dir(self, job_id: str) -> Path:
        """Return the directory path for a given job."""
        return self._output_dir / job_id

    @staticmethod
    def url_hash(url: str) -> str:
        """Return a truncated SHA-256 hash (16 hex chars) of *url*."""
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Content read / write
    # ------------------------------------------------------------------

    async def write(self, job_id: str, url: str, content: ExtractedContent) -> None:
        """Write content files to disk for a single page.

        Creates the job directory if it does not exist.  Only writes files for
        non-``None`` content fields.
        """
        job_path = self.job_dir(job_id)
        self._ensure_within_output_dir(job_path)
        job_path.mkdir(parents=True, exist_ok=True)
        h = self.url_hash(url)

        if content.markdown is not None:
            target = job_path / f"{h}.md"
            self._ensure_within_output_dir(target)
            target.write_text(content.markdown, encoding="utf-8")

        if content.html is not None:
            target = job_path / f"{h}.html"
            self._ensure_within_output_dir(target)
            target.write_text(content.html, encoding="utf-8")

        log.debug("content_written", job_id=job_id, url=url, url_hash=h)

    async def read(self, job_id: str, url: str, fmt: str) -> str | None:
        """Read a content file from disk.

        Returns ``None`` when the requested file does not exist.
        """
        h = self.url_hash(url)
        ext = ".md" if fmt == "markdown" else ".html"
        path = self.job_dir(job_id) / f"{h}{ext}"
        self._ensure_within_output_dir(path)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    # ------------------------------------------------------------------
    # Manifest
    # ------------------------------------------------------------------

    async def write_manifest(
        self,
        job_id: str,
        url: str,
        config_data: dict[str, Any],
        total: int,
        finished: int,
        status: str,
        created_at: str,
        finished_at: str | None,
        records: list[dict[str, Any]],
    ) -> None:
        """Write ``manifest.json`` mapping url_hash to URL and metadata."""
        job_path = self.job_dir(job_id)
        self._ensure_within_output_dir(job_path)
        job_path.mkdir(parents=True, exist_ok=True)

        pages: dict[str, dict[str, Any]] = {}
        for record in records:
            if record.get("status") == "completed":
                h = self.url_hash(record["url"])
                pages[h] = {
                    "url": record["url"],
                    "status": record["status"],
                    "http_status": record.get("http_status"),
                    "title": record.get("title"),
                    "content_hash": record.get("content_hash"),
                    "files": {
                        "markdown": f"{h}.md",
                        "html": f"{h}.html",
                    },
                }

        manifest: dict[str, Any] = {
            "job_id": job_id,
            "status": status,
            "url": url,
            "created_at": created_at,
            "finished_at": finished_at,
            "config": config_data,
            "total": total,
            "finished": finished,
            "pages": pages,
        }

        path = job_path / "manifest.json"
        self._ensure_within_output_dir(path)
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        log.debug("manifest_written", job_id=job_id, page_count=len(pages))

    # ------------------------------------------------------------------
    # Security helpers
    # ------------------------------------------------------------------

    def _ensure_within_output_dir(self, path: Path) -> None:
        """Raise if *path* resolves outside the output directory (S14)."""
        resolved = path.resolve()
        output_resolved = self._output_dir.resolve()
        resolved_str = str(resolved)
        prefix = str(output_resolved) + "/"
        if resolved != output_resolved and not resolved_str.startswith(prefix):
            msg = f"Path traversal detected: {path} resolves outside {self._output_dir}"
            raise ValueError(msg)
