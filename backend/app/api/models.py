"""Expose the model allowlist and verified capabilities to the frontend (no secrets)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_registry
from app.providers.registry import ModelInfo, ModelRegistry

router = APIRouter(prefix="/api/models", tags=["models"])


class ModelsResponse(BaseModel):
    default_model: str
    models: list[ModelInfo]


@router.get("", response_model=ModelsResponse)
async def list_models(registry: Annotated[ModelRegistry, Depends(get_registry)]) -> ModelsResponse:
    return ModelsResponse(default_model=registry.default_model, models=registry.all())
