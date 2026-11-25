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


@lru_cache
def get_settings() -> Settings:
    return Settings()
