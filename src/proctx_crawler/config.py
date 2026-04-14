"""Application configuration loaded from YAML, env vars, and defaults."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import platformdirs
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import YamlConfigSettingsSource

if TYPE_CHECKING:
    from pydantic_settings import PydanticBaseSettingsSource


class Settings(BaseSettings):
    """ProContext Crawler configuration."""

    model_config = SettingsConfigDict(
        env_prefix="PROCTX_CRAWLER__",
        env_nested_delimiter="__",
        yaml_file="proctx-crawler.yaml",
        yaml_file_encoding="utf-8",
    )

    # Storage
    output_dir: Path = Field(
        default_factory=lambda: Path(platformdirs.user_data_dir("proctx-crawler")) / "jobs"
    )
    db_path: Path = Field(
        default_factory=lambda: Path(platformdirs.user_data_dir("proctx-crawler")) / "crawler.db"
    )

    # Server
    server_host: str = "127.0.0.1"
    server_port: int = 8080

    # Crawl defaults
    default_limit: int = 10
    default_depth: int = 1000
    job_timeout: int = 3600
    max_concurrent_jobs: int = 10
    max_response_size: int = 10485760  # 10 MB
    metadata_retention_days: int = 7

    # Auth (optional)
    auth_api_key: str | None = None

    # Playwright
    playwright_headless: bool = True

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Load settings from init args, env vars, and YAML (in priority order)."""
        return (
            init_settings,
            env_settings,
            YamlConfigSettingsSource(settings_cls),
        )


def load_settings() -> Settings:
    """Create a Settings instance from YAML, env vars, and defaults."""
    return Settings()
