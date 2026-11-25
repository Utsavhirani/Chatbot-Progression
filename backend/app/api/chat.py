"""Chat endpoints: send a message / retry a reply, both answered as an SSE stream.

Errors detected before streaming (auth, ownership, validation, duplicates, concurrency, budget,
rate limit, provider not configured) are normal JSON error responses with HTTP status codes.
Errors during generation arrive as an SSE `error` event (HTTP status is already 200 by then).

SSE events: user_message -> assistant_started -> delta* -> usage -> done   |   ... -> error
"""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Request

from app.api.deps import AppSettings, CurrentUser, DbSession, Registry, get_provider
from app.api.sse import SSEResponse
from app.chat.service import ChatService
from app.providers.base import ProviderAdapter
from app.schemas.chat import SendMessageIn

router = APIRouter(prefix="/api/conversations", tags=["chat"])

Provider = Annotated[ProviderAdapter, Depends(get_provider)]


def _service(request: Request, settings: AppSettings, registry: Registry, provider: Provider) -> ChatService:
    return ChatService(
        settings=settings,
        registry=registry,
        provider=provider,
        sessionmaker=request.app.state.db.sessionmaker,
    )


Service = Annotated[ChatService, Depends(_service)]


@router.post(
    "/{conversation_id}/messages",
    response_class=SSEResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "SSE stream of the reply"}},
)
async def send_message(
    conversation_id: uuid.UUID,
    body: SendMessageIn,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    chat: Service,
) -> SSEResponse:
    structlog.contextvars.bind_contextvars(conversation_id=str(conversation_id))
    request.app.state.chat_limiter.check(
        f"chat:{user.id}", "You are sending messages too quickly. Please wait."
    )
    turn = await chat.prepare_new_turn(db, user.id, conversation_id, body.client_message_id, body.content)
    await db.close()  # return the connection to the pool; generation uses its own short sessions
    return SSEResponse(chat.generate(turn))


@router.post(
    "/{conversation_id}/messages/{message_id}/retry",
    response_class=SSEResponse,
    responses={
        200: {"content": {"text/event-stream": {}}, "description": "SSE stream of the regenerated reply"}
    },
)
async def retry_message(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    chat: Service,
) -> SSEResponse:
    structlog.contextvars.bind_contextvars(conversation_id=str(conversation_id))
    request.app.state.chat_limiter.check(
        f"chat:{user.id}", "You are sending messages too quickly. Please wait."
    )
    turn = await chat.prepare_retry(db, user.id, conversation_id, message_id)
    await db.close()
    return SSEResponse(chat.generate(turn))
