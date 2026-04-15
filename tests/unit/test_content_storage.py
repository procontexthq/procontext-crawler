"""Tests for ContentStorage: writing, reading, manifest generation, and security."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from proctx_crawler.infrastructure.content_storage import ContentStorage, ExtractedContent

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_storage(tmp_path: Path) -> ContentStorage:
    return ContentStorage(output_dir=tmp_path)


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------


class TestWrite:
    @pytest.mark.anyio
    async def test_write_markdown(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path)
        url = "https://example.com/page"
        content = ExtractedContent(markdown="# Hello")
        await storage.write("job1", url, content)

        h = storage.url_hash(url)
        md_path = tmp_path / "job1" / f"{h}.md"
        assert md_path.exists()
        assert md_path.read_text(encoding="utf-8") == "# Hello"

    @pytest.mark.anyio
    async def test_write_html(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path)
        url = "https://example.com/page"
        content = ExtractedContent(html="<h1>Hello</h1>")
        await storage.write("job1", url, content)

        h = storage.url_hash(url)
        html_path = tmp_path / "job1" / f"{h}.html"
        assert html_path.exists()
        assert html_path.read_text(encoding="utf-8") == "<h1>Hello</h1>"

        # markdown file should NOT exist
        md_path = tmp_path / "job1" / f"{h}.md"
        assert not md_path.exists()

    @pytest.mark.anyio
    async def test_write_both(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path)
        url = "https://example.com/page"
        content = ExtractedContent(markdown="# Hello", html="<h1>Hello</h1>")
        await storage.write("job1", url, content)

        h = storage.url_hash(url)
        assert (tmp_path / "job1" / f"{h}.md").exists()
        assert (tmp_path / "job1" / f"{h}.html").exists()

    @pytest.mark.anyio
    async def test_write_neither(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path)
        url = "https://example.com/page"
        content = ExtractedContent()
        await storage.write("job1", url, content)

        h = storage.url_hash(url)
        assert not (tmp_path / "job1" / f"{h}.md").exists()
        assert not (tmp_path / "job1" / f"{h}.html").exists()

    @pytest.mark.anyio
    async def test_directory_creation(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path)
        job_dir = tmp_path / "new-job"
        assert not job_dir.exists()

        await storage.write("new-job", "https://example.com", ExtractedContent(markdown="x"))
        assert job_dir.is_dir()

    @pytest.mark.anyio
    async def test_overwrite(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path)
        url = "https://example.com/page"

        await storage.write("job1", url, ExtractedContent(markdown="first"))
        await storage.write("job1", url, ExtractedContent(markdown="second"))

        h = storage.url_hash(url)
        assert (tmp_path / "job1" / f"{h}.md").read_text(encoding="utf-8") == "second"


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


class TestRead:
    @pytest.mark.anyio
    async def test_read_existing_markdown(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path)
        url = "https://example.com/page"
        await storage.write("job1", url, ExtractedContent(markdown="# Title"))

        result = await storage.read("job1", url, "markdown")
        assert result == "# Title"

    @pytest.mark.anyio
    async def test_read_existing_html(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path)
        url = "https://example.com/page"
        await storage.write("job1", url, ExtractedContent(html="<p>Hi</p>"))

        result = await storage.read("job1", url, "html")
        assert result == "<p>Hi</p>"

    @pytest.mark.anyio
    async def test_read_nonexistent_returns_none(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path)
        result = await storage.read("no-such-job", "https://example.com", "markdown")
        assert result is None


# ---------------------------------------------------------------------------
# url_hash
# ---------------------------------------------------------------------------


class TestUrlHash:
    def test_determinism(self) -> None:
        h1 = ContentStorage.url_hash("https://example.com/page")
        h2 = ContentStorage.url_hash("https://example.com/page")
        assert h1 == h2

    def test_length(self) -> None:
        h = ContentStorage.url_hash("https://example.com/some/deep/path")
        assert len(h) == 16

    def test_hex_only(self) -> None:
        h = ContentStorage.url_hash("https://example.com/page?q=1")
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# job_dir
# ---------------------------------------------------------------------------


class TestJobDir:
    def test_path_structure(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path)
        result = storage.job_dir("abc-123")
        assert result == tmp_path / "abc-123"


# ---------------------------------------------------------------------------
# write_manifest
# ---------------------------------------------------------------------------


class TestWriteManifest:
    @pytest.mark.anyio
    async def test_manifest_structure(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path)
        url = "https://example.com"
        records = [
            {
                "url": "https://example.com/page1",
                "status": "completed",
                "http_status": 200,
                "title": "Page 1",
                "content_hash": "abc123",
            },
        ]

        await storage.write_manifest(
            job_id="job1",
            url=url,
            config_data={"limit": 10},
            total=1,
            finished=1,
            status="completed",
            created_at="2026-03-16T10:00:00+00:00",
            finished_at="2026-03-16T10:05:00+00:00",
            records=records,
        )

        manifest_path = tmp_path / "job1" / "manifest.json"
        assert manifest_path.exists()

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["job_id"] == "job1"
        assert manifest["status"] == "completed"
        assert manifest["url"] == url
        assert manifest["created_at"] == "2026-03-16T10:00:00+00:00"
        assert manifest["finished_at"] == "2026-03-16T10:05:00+00:00"
        assert manifest["config"] == {"limit": 10}
        assert manifest["total"] == 1
        assert manifest["finished"] == 1

        h = storage.url_hash("https://example.com/page1")
        assert h in manifest["pages"]
        page = manifest["pages"][h]
        assert page["url"] == "https://example.com/page1"
        assert page["status"] == "completed"
        assert page["http_status"] == 200
        assert page["title"] == "Page 1"
        assert page["content_hash"] == "abc123"
        assert page["files"]["markdown"] == f"{h}.md"
        assert page["files"]["html"] == f"{h}.html"

    @pytest.mark.anyio
    async def test_manifest_only_includes_completed(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path)
        records = [
            {"url": "https://example.com/ok", "status": "completed", "http_status": 200},
            {"url": "https://example.com/err", "status": "errored", "http_status": 500},
            {"url": "https://example.com/skip", "status": "skipped"},
            {"url": "https://example.com/queued", "status": "queued"},
        ]

        await storage.write_manifest(
            job_id="job2",
            url="https://example.com",
            config_data={},
            total=4,
            finished=2,
            status="completed",
            created_at="2026-03-16T10:00:00+00:00",
            finished_at="2026-03-16T10:05:00+00:00",
            records=records,
        )

        manifest = json.loads((tmp_path / "job2" / "manifest.json").read_text(encoding="utf-8"))
        assert len(manifest["pages"]) == 1
        page_hashes = list(manifest["pages"].keys())
        assert page_hashes[0] == storage.url_hash("https://example.com/ok")

    @pytest.mark.anyio
    async def test_manifest_no_completed_records(self, tmp_path: Path) -> None:
        storage = _make_storage(tmp_path)
        records = [
            {"url": "https://example.com/err", "status": "errored"},
        ]

        await storage.write_manifest(
            job_id="job3",
            url="https://example.com",
            config_data={},
            total=1,
            finished=1,
            status="completed",
            created_at="2026-03-16T10:00:00+00:00",
            finished_at=None,
            records=records,
        )

        manifest = json.loads((tmp_path / "job3" / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["pages"] == {}
        assert manifest["finished_at"] is None


# ---------------------------------------------------------------------------
# Path traversal guard
# ---------------------------------------------------------------------------


class TestPathTraversalGuard:
    @pytest.mark.anyio
    async def test_write_with_traversal_raises(self, tmp_path: Path) -> None:
        """A URL that produces a path outside the output dir is rejected."""
        storage = _make_storage(tmp_path)
        # Directly test the guard method
        import pathlib

        outside = tmp_path.parent / "escaped"
        with pytest.raises(ValueError, match="Path traversal detected"):
            storage._ensure_within_output_dir(pathlib.Path(outside))

    @pytest.mark.anyio
    async def test_read_with_traversal_raises(self, tmp_path: Path) -> None:
        """Reading a path that resolves outside the output dir is rejected."""
        storage = _make_storage(tmp_path)
        import pathlib

        outside = tmp_path.parent / "escaped"
        with pytest.raises(ValueError, match="Path traversal detected"):
            storage._ensure_within_output_dir(pathlib.Path(outside))
