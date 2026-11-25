"""Application settings, loaded from environment variables and the repo-root .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    # Message content is never logged unless explicitly enabled.
    log_content: bool = False

    # --- LLM provider ---------------------------------------------------
    provider: Literal["groq", "fake"] = "groq"
    groq_api_key: SecretStr | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    # Empty -> use default_model from app/providers/models.toml
    default_model: str = ""

    provider_max_attempts: int = Field(default=3, ge=1, le=5)
    provider_backoff_base_s: float = Field(default=0.5, gt=0)
    provider_backoff_cap_s: float = Field(default=8.0, gt=0)
    provider_connect_timeout_s: float = Field(default=5.0, gt=0)
    # Max silence between streamed chunks.
    provider_read_timeout_s: float = Field(default=30.0, gt=0)
    # Overall deadline for one generation, including retries.
    provider_total_timeout_s: float = Field(default=120.0, gt=0)

    # --- Chat / context (defaults sized for Groq free tier, docs/providers.md) ---
    context_budget_tokens: int = Field(default=3000, ge=256)
    context_safety_margin_tokens: int = Field(default=256, ge=0)
    max_message_chars: int = Field(default=8000, ge=1)
    chat_rate_per_minute: int = Field(default=20, ge=1)
    # A reply still "streaming" after this long is considered abandoned (e.g. server crash).
    stale_stream_after_s: int = Field(default=300, ge=30)

    # --- Database --------------------------------------------------------
    database_url: str = "postgresql+asyncpg://assistant:assistant_dev_pw@127.0.0.1:5433/assistant"
    test_database_url: str = "postgresql+asyncpg://assistant:assistant_dev_pw@127.0.0.1:5433/assistant_test"
    db_connect_timeout_s: float = Field(default=5.0, gt=0)

    # --- Auth / sessions ---------------------------------------------------
    session_cookie_name: str = "session"
    session_ttl_days: int = Field(default=14, ge=1, le=90)
    # Comma-separated browser origins allowed to make state-changing requests (CSRF defence).
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Rate limits (per process; see docs/decisions.md #8) -----------------
    login_rate_per_minute: int = Field(default=5, ge=1)
    register_rate_per_minute: int = Field(default=5, ge=1)

    @property
    def allowed_origin_set(self) -> frozenset[str]:
        return frozenset(o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip())

    @property
    def secure_cookies(self) -> bool:
        return self.env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()
