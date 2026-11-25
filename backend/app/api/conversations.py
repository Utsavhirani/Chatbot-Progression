"""Conversation CRUD and message history (all ownership-scoped)."""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, status

from app.api.deps import AppSettings, CurrentUser, DbSession, Registry
from app.conversations import service
from app.schemas.conversations import ConversationCreate, ConversationOut, ConversationUpdate, MessageOut

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def _bind(conversation_id: uuid.UUID) -> None:
    structlog.contextvars.bind_contextvars(conversation_id=str(conversation_id))


@router.get("", response_model=list[ConversationOut])
async def list_conversations(user: CurrentUser, db: DbSession) -> list[ConversationOut]:
    return [ConversationOut.model_validate(c) for c in await service.list_conversations(db, user.id)]


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate, user: CurrentUser, db: DbSession, registry: Registry, settings: AppSettings
) -> ConversationOut:
    conversation = await service.create(db, registry, user.id, body, settings.default_system_prompt)
    _bind(conversation.id)
    return ConversationOut.model_validate(conversation)


@router.get("/{conversation_id}", response_model=ConversationOut)
async def get_conversation(conversation_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ConversationOut:
    _bind(conversation_id)
    return ConversationOut.model_validate(await service.get_owned(db, user.id, conversation_id))


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def update_conversation(
    conversation_id: uuid.UUID, body: ConversationUpdate, user: CurrentUser, db: DbSession, registry: Registry
) -> ConversationOut:
    _bind(conversation_id)
    return ConversationOut.model_validate(await service.update(db, registry, user.id, conversation_id, body))


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    _bind(conversation_id)
    await service.soft_delete(db, user.id, conversation_id)


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(conversation_id: uuid.UUID, user: CurrentUser, db: DbSession) -> list[MessageOut]:
    _bind(conversation_id)
    return [MessageOut.model_validate(m) for m in await service.list_messages(db, user.id, conversation_id)]
