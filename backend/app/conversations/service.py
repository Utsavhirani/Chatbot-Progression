"""Ownership-scoped conversation operations.

Every query filters by the authenticated user's id. A conversation that does not exist, is
deleted, or belongs to someone else is indistinguishable to the caller: 404 not_found.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models import Conversation, Message
from app.providers.registry import ModelRegistry, UnknownModelError
from app.schemas.conversations import ConversationCreate, ConversationUpdate, ModelSettingsIn

DEFAULT_TITLE = "New conversation"
DEFAULT_TEMPERATURE = 0.3
LIST_LIMIT = 100


def _not_found() -> AppError:
    return AppError("not_found", "Conversation not found.", status_code=404)


def resolve_settings(
    registry: ModelRegistry, requested: ModelSettingsIn | None, current: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Merge requested settings over current ones (or model defaults) and validate them."""
    current = current or {}
    req = requested or ModelSettingsIn()
    model_id = req.model or current.get("model") or registry.default_model
    try:
        model = registry.get(model_id)
    except UnknownModelError:
        raise AppError("invalid_model", f"Model {model_id!r} is not available.", status_code=422) from None
    model_changed = model_id != current.get("model")

    max_tokens = (
        req.max_tokens or (None if model_changed else current.get("max_tokens")) or model.default_max_tokens
    )
    if max_tokens > model.max_output_tokens:
        raise AppError(
            "invalid_settings",
            f"max_tokens must be at most {model.max_output_tokens} for {model_id}.",
            status_code=422,
        )
    temperature = (
        req.temperature if req.temperature is not None else current.get("temperature", DEFAULT_TEMPERATURE)
    )
    return {"model": model_id, "temperature": temperature, "max_tokens": max_tokens}


async def list_conversations(db: AsyncSession, user_id: uuid.UUID) -> list[Conversation]:
    result = await db.scalars(
        select(Conversation)
        .where(Conversation.user_id == user_id, Conversation.deleted_at.is_(None))
        .order_by(Conversation.updated_at.desc(), Conversation.id)
        .limit(LIST_LIMIT)
    )
    return list(result)


async def get_owned(
    db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID, *, for_update: bool = False
) -> Conversation:
    stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == user_id,
        Conversation.deleted_at.is_(None),
    )
    if for_update:
        stmt = stmt.with_for_update()
    conversation = await db.scalar(stmt)
    if conversation is None:
        raise _not_found()
    return conversation


async def create(
    db: AsyncSession, registry: ModelRegistry, user_id: uuid.UUID, data: ConversationCreate
) -> Conversation:
    conversation = Conversation(
        user_id=user_id,
        title=data.title or DEFAULT_TITLE,
        system_prompt=data.system_prompt,
        settings=resolve_settings(registry, data.settings),
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def update(
    db: AsyncSession,
    registry: ModelRegistry,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    data: ConversationUpdate,
) -> Conversation:
    conversation = await get_owned(db, user_id, conversation_id)
    fields = data.model_fields_set
    if "title" in fields:
        conversation.title = data.title or DEFAULT_TITLE
    if "system_prompt" in fields:
        conversation.system_prompt = data.system_prompt
    if "settings" in fields and data.settings is not None:
        conversation.settings = resolve_settings(registry, data.settings, conversation.settings)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def soft_delete(db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
    conversation = await get_owned(db, user_id, conversation_id)
    conversation.deleted_at = datetime.now(UTC)
    await db.commit()


async def list_messages(db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID) -> list[Message]:
    await get_owned(db, user_id, conversation_id)
    result = await db.scalars(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.seq)
    )
    return list(result)
