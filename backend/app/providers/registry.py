"""Model registry (allowlist + verified capabilities from models.toml) and provider factory."""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.providers.base import ProviderAdapter
from app.providers.fake import FakeProvider
from app.providers.groq import GroqProvider
from app.providers.retry import RetryPolicy

MODELS_FILE = Path(__file__).with_name("models.toml")


class ModelInfo(BaseModel):
    id: str
    provider: str
    display_name: str
    context_window: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    default_max_tokens: int = Field(gt=0)
    chat: bool = True
    streaming: bool = False
    tools: bool = False
    json_object: bool = False
    json_schema: bool = False
    vision: bool = False
    reasoning: bool = False
    reasoning_effort: str | None = None
    tokens_per_minute: int | None = None
    input_tokens_per_minute: int | None = None

    @property
    def per_request_token_ceiling(self) -> int | None:
        """Largest single request the account's per-minute limits can ever accept (input + output)."""
        return self.tokens_per_minute


class UnknownModelError(ValueError):
    pass


class ModelRegistry:
    def __init__(self, models: dict[str, ModelInfo], default_model: str) -> None:
        if default_model not in models:
            raise UnknownModelError(f"Default model {default_model!r} is not in the registry.")
        self._models = models
        self.default_model = default_model

    @classmethod
    def load(cls, path: Path = MODELS_FILE, default_override: str = "") -> ModelRegistry:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        models = {mid: ModelInfo(id=mid, **cfg) for mid, cfg in (data.get("models") or {}).items()}
        return cls(models, default_override or data["default_model"])

    def get(self, model_id: str) -> ModelInfo:
        try:
            return self._models[model_id]
        except KeyError:
            raise UnknownModelError(f"Model {model_id!r} is not available.") from None

    def all(self) -> list[ModelInfo]:
        return list(self._models.values())


def build_provider(settings: Settings) -> ProviderAdapter | None:
    """Return the configured provider, or None if it is not configured (reported by /health/ready)."""
    if settings.provider == "fake":
        return FakeProvider()
    key = settings.groq_api_key.get_secret_value().strip() if settings.groq_api_key else ""
    if not key or key == "replace-me":
        return None
    return GroqProvider(
        api_key=key,
        base_url=settings.groq_base_url,
        policy=RetryPolicy(
            max_attempts=settings.provider_max_attempts,
            base_s=settings.provider_backoff_base_s,
            cap_s=settings.provider_backoff_cap_s,
        ),
        connect_timeout_s=settings.provider_connect_timeout_s,
        read_timeout_s=settings.provider_read_timeout_s,
        total_timeout_s=settings.provider_total_timeout_s,
    )
