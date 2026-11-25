from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_SYSTEM_PROMPT_CHARS = 4000


class ModelSettingsIn(BaseModel):
    """Per-conversation model settings. Unset fields fall back to the model's defaults."""

    model: str | None = Field(default=None, max_length=128)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)


class ModelSettings(BaseModel):
    model: str
    temperature: float
    max_tokens: int


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    system_prompt: str | None = Field(default=None, max_length=MAX_SYSTEM_PROMPT_CHARS)
    settings: ModelSettingsIn | None = None

    @field_validator("title", "system_prompt")
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        return v.strip() or None if v is not None else None


class ConversationUpdate(ConversationCreate):
    """PATCH: only fields present in the body are changed. `system_prompt: null` clears it."""


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    system_prompt: str | None
    settings: ModelSettings
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    seq: int
    role: str
    content: str
    status: str
    error_code: str | None
    client_message_id: uuid.UUID | None
    reply_to_id: uuid.UUID | None
    created_at: datetime
