"""Tests for Settings configuration loading."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from proctx_crawler.config import Settings, load_settings

if TYPE_CHECKING:
    import pytest


class TestSettings:
    def test_defaults(self) -> None:
        settings = Settings()
        assert settings.server_host == "127.0.0.1"
        assert settings.server_port == 8080
        assert settings.default_limit == 10
        assert settings.default_depth == 1000
        assert settings.job_timeout == 3600
        assert settings.max_concurrent_jobs == 10
        assert settings.max_response_size == 10485760
        assert settings.metadata_retention_days == 7
        assert settings.auth_api_key is None
        assert settings.playwright_headless is True

    def test_output_dir_is_path(self) -> None:
        settings = Settings()
        assert isinstance(settings.output_dir, Path)
        assert settings.output_dir.name == "jobs"

    def test_db_path_is_path(self) -> None:
        settings = Settings()
        assert isinstance(settings.db_path, Path)
        assert settings.db_path.name == "crawler.db"

    def test_load_settings_returns_settings(self) -> None:
        result = load_settings()
        assert isinstance(result, Settings)

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROCTX_CRAWLER__SERVER_PORT", "9090")
        monkeypatch.setenv("PROCTX_CRAWLER__AUTH_API_KEY", "secret-key")
        settings = Settings()
        assert settings.server_port == 9090
        assert settings.auth_api_key == "secret-key"
