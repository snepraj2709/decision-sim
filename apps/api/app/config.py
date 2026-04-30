"""Application settings, loaded from environment.

All env access goes through this module — never `os.getenv` directly in app code.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────
    env: Literal["development", "test", "staging", "production"] = "development"
    log_level: str = "INFO"
    version: str = "0.1.0"
    api_base_url: str = "http://localhost:8000"
    web_base_url: str = "http://localhost:3000"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # ── Database ─────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://dsim:dsim_dev@localhost:5432/dsim"
    database_sync_url: str = "postgresql+psycopg://dsim:dsim_dev@localhost:5432/dsim"

    # ── Redis ────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── LLM providers (Step 2+) ──────────────────────────────────────────
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

    # ── Search providers (Step 2) ────────────────────────────────────────
    tavily_api_key: str | None = None
    exa_api_key: str | None = None

    # ── Feature flags ────────────────────────────────────────────────────
    require_evidence_anchors: bool = True
    min_sources_for_high_confidence: int = 3


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor. Use this everywhere instead of instantiating Settings()."""
    return Settings()
