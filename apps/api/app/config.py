"""Application settings, loaded from environment.

All env access goes through this module — never `os.getenv` directly in app code.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", API_DIR / ".env"),
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
    cors_origins_raw: str = Field(
        default="http://localhost:3000",
        validation_alias=AliasChoices("CORS_ORIGINS", "cors_origins"),
    )

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

    @property
    def cors_origins(self) -> list[str]:
        """Return CORS origins from a comma-separated env value.

        `.env.example` uses `CORS_ORIGINS=http://localhost:3000`; keeping the
        public setting as a simple string avoids pydantic-settings treating it
        as JSON before validators can run.
        """
        return [
            origin.strip()
            for origin in self.cors_origins_raw.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor. Use this everywhere instead of instantiating Settings()."""
    return Settings()
