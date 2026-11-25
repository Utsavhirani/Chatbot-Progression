"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from app.core.errors import AppError
from app.providers.base import ProviderAdapter
from app.providers.registry import ModelRegistry


def get_registry(request: Request) -> ModelRegistry:
    return request.app.state.registry


def get_provider(request: Request) -> ProviderAdapter:
    provider: ProviderAdapter | None = request.app.state.provider
    if provider is None:
        raise AppError(
            "provider_not_configured",
            "The AI provider is not configured on the server.",
            status_code=503,
        )
    return provider
