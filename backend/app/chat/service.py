"""Chat turn orchestration (docs/v1-architecture.md §5).

A turn has two phases:

1. `prepare_*` (inside the request, before streaming starts). Everything that can be rejected
   with a normal JSON error happens here: ownership, validation, idempotency, concurrency, context
   budget. It persists the user message (new turns) and an assistant placeholder with
   status=streaming, then commits.
2. `generate` (an async generator driving the SSE response). It streams provider output to the
   client and ALWAYS finalises the assistant row and an llm_calls usage row: on success, on a
   provider error, and on client disconnect/cancellation (shielded from cancellation).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
import structlog
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.conversations import service as conversations
from app.conversations.context import build_context, compute_budget
from app.conversations.tokens import estimate_message_tokens
from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.models import Conversation, LlmCall, Message
from app.providers.base import (
    ChatMessage,
    ChatRequest,
    Finish,
    ProviderAdapter,
    ProviderError,
    ProviderStreamInterrupted,
    TextDelta,
    Usage,
    UsageEvent,
)
from app.providers.registry import ModelInfo, ModelRegistry

log = get_logger(__name__)

RETRYABLE_STATUSES = ("failed", "partial", "cancelled")
TITLE_MAX_CHARS = 60

# User-facing messages. Provider details stay in logs.
_PUBLIC_ERRORS: dict[str, tuple[str, bool]] = {
    "provider_rate_limited": (
        "The AI service is busy right now (rate limit). Please try again shortly.",
        True,
    ),
    "provider_unavailable": ("The AI service is temporarily unavailable. Please try again.", True),
    "provider_timeout": ("The AI service took too long to respond. Please try again.", True),
    "provider_stream_interrupted": ("The response was interrupted. You can retry it.", True),
    "provider_bad_response": ("The AI service returned an unexpected response. Please try again.", True),
    "provider_bad_request": ("The AI service could not process this request.", False),
    "context_too_large": ("This conversation is too long for the selected model.", False),
    "request_too_large": ("This request is larger than the AI service currently allows. Shorten it.", False),
    "provider_auth": ("The AI service is not configured correctly. Please contact support.", False),
    "provider_not_configured": ("The AI service is not configured on the server.", False),
}


def public_error(err: ProviderError) -> dict[str, Any]:
    message, retryable = _PUBLIC_ERRORS.get(err.code, ("The AI service failed to respond.", err.retryable))
    return {"code": err.code, "message": message, "retryable": retryable, "retry_after": err.retry_after}


@dataclass
class Turn:
    """Everything `generate` needs; plain values only (no live ORM objects across sessions)."""

    user_id: uuid.UUID
    conversation_id: uuid.UUID
    assistant_message_id: uuid.UUID
    assistant_seq: int
    request: ChatRequest
    estimated_input_tokens: int
    history_dropped: int
    user_message: dict[str, Any] | None = None  # present for new turns, not for retries
    # When set, summarise history up to this seq in the background after a successful reply.
    summarize_through_seq: int | None = None
    request_id: str | None = field(
        default_factory=lambda: structlog.contextvars.get_contextvars().get("request_id")
    )


class ChatService:
    def __init__(
        self,
        *,
        settings: Settings,
        registry: ModelRegistry,
        provider: ProviderAdapter,
        sessionmaker: async_sessionmaker[AsyncSession],
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.provider = provider
        self.sessionmaker = sessionmaker

    # ------------------------------------------------------------------ phase 1: prepare

    async def prepare_new_turn(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        client_message_id: uuid.UUID,
        content: str,
    ) -> Turn:
        text = content.strip()
        if not text:
            raise AppError("empty_message", "Please enter a message.", status_code=422)
        if len(text) > self.settings.max_message_chars:
            raise AppError(
                "message_too_long",
                f"Messages are limited to {self.settings.max_message_chars} characters.",
                status_code=413,
            )

        conversation = await conversations.get_owned(db, user_id, conversation_id, for_update=True)
        await self._reject_duplicate(db, conversation_id, client_message_id)
        await self._reject_in_progress(db, conversation_id)

        history = await self._history(db, conversation_id)
        model, request, built = self._build_request(conversation, history, text)

        next_seq = (history[-1].seq if history else 0) + 1
        user_msg = Message(
            conversation_id=conversation_id,
            seq=next_seq,
            role="user",
            content=text,
            status="complete",
            client_message_id=client_message_id,
            token_estimate=estimate_message_tokens(text),
        )
        db.add(user_msg)
        await db.flush()
        assistant = Message(
            conversation_id=conversation_id,
            seq=next_seq + 1,
            role="assistant",
            content="",
            status="streaming",
            reply_to_id=user_msg.id,
        )
        db.add(assistant)
        if next_seq == 1 and conversation.title == conversations.DEFAULT_TITLE:
            conversation.title = _title_from(text)
        conversation.updated_at = func.now()
        await self._commit_guarded(db)

        return Turn(
            user_id=user_id,
            conversation_id=conversation_id,
            assistant_message_id=assistant.id,
            assistant_seq=assistant.seq,
            request=request,
            estimated_input_tokens=built.estimated_tokens,
            history_dropped=built.history_dropped,
            summarize_through_seq=self._summary_target(built),
            user_message={
                "id": str(user_msg.id),
                "seq": user_msg.seq,
                "client_message_id": str(client_message_id),
            },
        )

    async def prepare_retry(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        assistant_message_id: uuid.UUID,
    ) -> Turn:
        conversation = await conversations.get_owned(db, user_id, conversation_id, for_update=True)
        await self._reject_in_progress(db, conversation_id)
        history = await self._history(db, conversation_id)
        target = next((m for m in history if m.id == assistant_message_id and m.role == "assistant"), None)
        if target is None:
            raise AppError("not_found", "Message not found.", status_code=404)
        if target.status not in RETRYABLE_STATUSES:
            raise AppError(
                "not_retryable", "Only failed or interrupted replies can be retried.", status_code=409
            )
        if target.seq != history[-1].seq:
            raise AppError("retry_not_latest", "Only the most recent reply can be retried.", status_code=409)
        question = next((m for m in history if m.id == target.reply_to_id), None)
        if question is None:
            raise AppError(
                "not_retryable", "The original question for this reply is missing.", status_code=409
            )

        prior = [m for m in history if m.seq < question.seq]
        _, request, built = self._build_request(conversation, prior, question.content)

        target.status = "streaming"
        target.content = ""
        target.error_code = None
        conversation.updated_at = func.now()
        await self._commit_guarded(db)

        return Turn(
            user_id=user_id,
            conversation_id=conversation_id,
            assistant_message_id=target.id,
            assistant_seq=target.seq,
            request=request,
            estimated_input_tokens=built.estimated_tokens,
            history_dropped=built.history_dropped,
            summarize_through_seq=self._summary_target(built),
        )

    # ------------------------------------------------------------------ phase 2: generate

    async def generate(self, turn: Turn) -> AsyncIterator[dict[str, Any]]:
        """Yield SSE events ({"event", "data"}) and always persist the outcome."""
        structlog.contextvars.bind_contextvars(
            conversation_id=str(turn.conversation_id), message_id=str(turn.assistant_message_id)
        )
        parts: list[str] = []
        usage: Usage | None = None
        attempts = 1
        finish_reason: str | None = None
        error: ProviderError | None = None
        internal_failure = False
        status = "cancelled"  # unless we reach a definite outcome below
        start = time.perf_counter()
        ttft_ms: int | None = None

        try:
            if turn.user_message:
                yield {"event": "user_message", "data": turn.user_message}
            yield {
                "event": "assistant_started",
                "data": {
                    "id": str(turn.assistant_message_id),
                    "seq": turn.assistant_seq,
                    "model": turn.request.model,
                },
            }
            try:
                async with aclosing(self.provider.stream(turn.request)) as stream:
                    async for event in stream:
                        if isinstance(event, TextDelta):
                            if ttft_ms is None:
                                ttft_ms = _ms_since(start)
                            parts.append(event.text)
                            yield {"event": "delta", "data": {"text": event.text}}
                        elif isinstance(event, UsageEvent):
                            usage = event.usage
                        elif isinstance(event, Finish):
                            attempts = event.attempts
                            finish_reason = event.reason
                            _log_rate_limit(event.rate_limit)
                status = "complete"
            except ProviderError as exc:
                error = exc
                attempts = exc.attempts
                status = "partial" if parts or isinstance(exc, ProviderStreamInterrupted) else "failed"
            except Exception:
                internal_failure = True
                status = "partial" if parts else "failed"
                raise

            if status == "complete":
                yield {
                    "event": "usage",
                    "data": {
                        "input_tokens": usage.input_tokens if usage else None,
                        "output_tokens": usage.output_tokens if usage else None,
                        "estimated_input_tokens": turn.estimated_input_tokens,
                        "ttft_ms": ttft_ms,
                        "latency_ms": _ms_since(start),
                    },
                }
                yield {
                    "event": "done",
                    "data": {
                        "id": str(turn.assistant_message_id),
                        "status": "complete",
                        "finish_reason": finish_reason,
                    },
                }
            else:
                yield {
                    "event": "error",
                    "data": {**public_error(error), "id": str(turn.assistant_message_id), "status": status},
                }
        finally:
            # Runs on success, error, client disconnect (GeneratorExit) and task cancellation.
            # Shielded so a cancelled request still records what happened.
            with anyio.CancelScope(shield=True):
                await self._finalise(
                    turn,
                    content="".join(parts),
                    status=status,
                    error_code=_outcome_code(status, error, internal_failure, finish_reason),
                    usage=usage,
                    attempts=attempts,
                    ttft_ms=ttft_ms,
                    latency_ms=_ms_since(start),
                )
            if status == "complete" and turn.summarize_through_seq is not None:
                self._schedule_summary(turn)

    # ------------------------------------------------------------------ summaries

    def _summary_target(self, built: Any) -> int | None:
        if not self.settings.context_summarization:
            return None
        if built.history_dropped < self.settings.summary_min_new_messages:
            return None
        return built.dropped_through_seq

    def _schedule_summary(self, turn: Turn) -> None:
        task = asyncio.create_task(
            self._summarize(turn.user_id, turn.conversation_id, turn.summarize_through_seq)
        )
        BACKGROUND_TASKS.add(task)
        task.add_done_callback(BACKGROUND_TASKS.discard)

    async def _summarize(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, through_seq: int | None
    ) -> None:
        """Fold messages (previous summary point, through_seq] into the conversation summary."""
        if through_seq is None:
            return
        start = time.perf_counter()
        try:
            async with self.sessionmaker() as db:
                conversation = await db.scalar(
                    select(Conversation).where(
                        Conversation.id == conversation_id, Conversation.user_id == user_id
                    )
                )
                if conversation is None:
                    return
                done_through = conversation.summary_through_seq or 0
                if through_seq <= done_through:
                    return  # already covered (e.g. by a concurrent run)
                rows = list(
                    await db.scalars(
                        select(Message)
                        .where(
                            Message.conversation_id == conversation_id,
                            Message.seq > done_through,
                            Message.seq <= through_seq,
                            Message.status.in_(("complete", "partial", "cancelled")),
                        )
                        .order_by(Message.seq)
                    )
                )
                lines = [
                    ("Customer: " if m.role == "user" else "Assistant: ") + m.content
                    for m in rows
                    if m.content
                ]
                # Keep the summarisation request itself within the context budget.
                transcript = "\n".join(lines)[-max(1000, self.settings.context_budget_tokens * 3) :]
                model = self.registry.get(
                    (conversation.settings or {}).get("model") or self.registry.default_model
                )
                previous = f"Existing summary:\n{conversation.summary}\n\n" if conversation.summary else ""
                result = await self.provider.complete(
                    ChatRequest(
                        model=model.id,
                        messages=[
                            ChatMessage("system", SUMMARY_INSTRUCTIONS),
                            ChatMessage("user", f"{previous}New messages:\n{transcript}"),
                        ],
                        max_tokens=self.settings.summary_max_tokens,
                        temperature=0.2,
                        reasoning_effort=model.reasoning_effort if model.reasoning else None,
                    )
                )
                summary = result.text.strip()
                if summary:
                    await db.execute(
                        update(Conversation)
                        .where(
                            Conversation.id == conversation_id,
                            # optimistic check: never overwrite a newer summary
                            func.coalesce(Conversation.summary_through_seq, 0) == done_through,
                        )
                        .values(summary=summary, summary_through_seq=through_seq)
                    )
                usage = result.usage
                db.add(
                    LlmCall(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        provider=self.provider.name,
                        model=model.id,
                        input_tokens=usage.input_tokens if usage else None,
                        output_tokens=usage.output_tokens if usage else None,
                        total_tokens=usage.total_tokens if usage else None,
                        usage_source="provider" if usage else "none",
                        latency_ms=_ms_since(start),
                        attempts=result.attempts,
                        status="summary",
                    )
                )
                await db.commit()
                log.info(
                    "chat.summary_updated", conversation_id=str(conversation_id), through_seq=through_seq
                )
        except Exception as exc:  # best effort: the next turn simply trims again
            log.warning(
                "chat.summary_failed", conversation_id=str(conversation_id), error_type=type(exc).__name__
            )

    # ------------------------------------------------------------------ helpers

    def _build_request(self, conversation: Conversation, history: list[Message], text: str):
        settings = conversation.settings or {}
        model: ModelInfo = self.registry.get(settings.get("model") or self.registry.default_model)
        max_tokens = int(settings.get("max_tokens") or model.default_max_tokens)
        budget = compute_budget(
            configured_budget=self.settings.context_budget_tokens,
            context_window=model.context_window,
            max_output_tokens=max_tokens,
            safety_margin=self.settings.context_safety_margin_tokens,
        )
        summary = conversation.summary if self.settings.context_summarization else None
        if summary:
            # A summary may never crowd out the current message: cap it at a third of the budget.
            max_chars = int(budget / 3 * 4)
            if len(summary) > max_chars:
                summary = summary[: max(0, max_chars - 1)].rstrip() + "…"
        if summary and conversation.summary_through_seq:
            history = [m for m in history if m.seq > conversation.summary_through_seq]
        built = build_context(
            system_prompt=conversation.system_prompt,
            history=history,
            user_message=text,
            budget_tokens=budget,
            summary=summary,
        )
        # Free-tier guard: one request larger than the per-minute token limit can never succeed.
        ceiling = model.per_request_token_ceiling
        if ceiling and built.estimated_tokens + max_tokens > ceiling:
            raise AppError(
                "request_too_large",
                "This request is larger than the AI service allows per minute. "
                "Shorten it or lower max tokens.",
                status_code=413,
            )
        request = ChatRequest(
            model=model.id,
            messages=built.messages,
            max_tokens=max_tokens,
            temperature=settings.get("temperature"),
            reasoning_effort=model.reasoning_effort if model.reasoning else None,
        )
        return model, request, built

    async def _history(self, db: AsyncSession, conversation_id: uuid.UUID) -> list[Message]:
        return list(
            await db.scalars(
                select(Message).where(Message.conversation_id == conversation_id).order_by(Message.seq)
            )
        )

    async def _reject_duplicate(
        self, db: AsyncSession, conversation_id: uuid.UUID, client_message_id: uuid.UUID
    ) -> None:
        existing = await db.scalar(
            select(Message).where(
                Message.conversation_id == conversation_id, Message.client_message_id == client_message_id
            )
        )
        if existing is None:
            return
        reply = await db.scalar(select(Message).where(Message.reply_to_id == existing.id))
        raise AppError(
            "duplicate",
            "This message was already sent.",
            status_code=409,
            details={
                "user_message_id": str(existing.id),
                "assistant_message_id": str(reply.id) if reply else None,
                "assistant_status": reply.status if reply else None,
            },
        )

    async def _reject_in_progress(self, db: AsyncSession, conversation_id: uuid.UUID) -> None:
        active = await db.scalar(
            select(Message).where(Message.conversation_id == conversation_id, Message.status == "streaming")
        )
        if active is None:
            return
        cutoff = datetime.now(UTC) - timedelta(seconds=self.settings.stale_stream_after_s)
        if active.updated_at < cutoff:
            # Abandoned (e.g. the server died mid-stream): release the lock instead of blocking forever.
            active.status = "failed"
            active.error_code = "abandoned"
            await db.flush()
            log.warning("chat.stale_stream_released", message_id=str(active.id))
            return
        raise AppError(
            "conflict_in_progress",
            "A reply is still being generated in this conversation.",
            status_code=409,
            retryable=True,
        )

    @staticmethod
    async def _commit_guarded(db: AsyncSession) -> None:
        try:
            await db.commit()
        except IntegrityError:
            # Lost a race with a concurrent request (unique seq / one-streaming / client id).
            await db.rollback()
            raise AppError(
                "conflict_in_progress",
                "Another request for this conversation is in progress.",
                status_code=409,
                retryable=True,
            ) from None

    async def _finalise(
        self,
        turn: Turn,
        *,
        content: str,
        status: str,
        error_code: str | None,
        usage: Usage | None,
        attempts: int,
        ttft_ms: int | None,
        latency_ms: int,
    ) -> None:
        try:
            async with self.sessionmaker() as db:
                await db.execute(
                    update(Message)
                    .where(Message.id == turn.assistant_message_id)
                    .values(
                        content=content,
                        status=status,
                        error_code=error_code,
                        token_estimate=estimate_message_tokens(content) if content else 0,
                    )
                )
                db.add(
                    LlmCall(
                        user_id=turn.user_id,
                        conversation_id=turn.conversation_id,
                        message_id=turn.assistant_message_id,
                        provider=self.provider.name,
                        model=turn.request.model,
                        input_tokens=usage.input_tokens if usage else None,
                        output_tokens=usage.output_tokens if usage else None,
                        total_tokens=usage.total_tokens if usage else None,
                        estimated_input_tokens=turn.estimated_input_tokens,
                        usage_source="provider" if usage else "none",
                        ttft_ms=ttft_ms,
                        latency_ms=latency_ms,
                        attempts=attempts,
                        status=status,
                        error_code=error_code,
                        request_id=turn.request_id,
                    )
                )
                await db.execute(
                    update(Conversation)
                    .where(Conversation.id == turn.conversation_id)
                    .values(updated_at=func.now())
                )
                await db.commit()
        except Exception:
            # The stale-stream release recovers the row later; never mask the original outcome.
            log.exception("chat.finalise_failed", message_id=str(turn.assistant_message_id))
            return

        event: dict[str, Any] = {
            "status": status,
            "model": turn.request.model,
            "input_tokens": usage.input_tokens if usage else None,
            "output_tokens": usage.output_tokens if usage else None,
            "estimated_input_tokens": turn.estimated_input_tokens,
            "history_dropped": turn.history_dropped,
            "ttft_ms": ttft_ms,
            "latency_ms": latency_ms,
            "attempts": attempts,
            "error_code": error_code,
        }
        if self.settings.log_content:
            event["content"] = content
        (log.info if status == "complete" else log.warning)("chat.turn_finished", **event)


async def release_abandoned_streams(sessionmaker: async_sessionmaker[AsyncSession]) -> int:
    """At startup (single process): any reply still 'streaming' was cut off by a restart."""
    async with sessionmaker() as db:
        result = await db.execute(
            update(Message)
            .where(Message.status == "streaming")
            .values(status="failed", error_code="server_restarted")
        )
        await db.commit()
        return result.rowcount or 0


BACKGROUND_TASKS: set[asyncio.Task[None]] = set()

SUMMARY_INSTRUCTIONS = (
    "You maintain the memory of a customer-support conversation. Update the summary with the new "
    "messages. Keep concrete facts the customer gave (names, order numbers, products, dates, problems, "
    "preferences) and what the assistant already answered or promised. Do not add anything that was not "
    "said. Plain text, at most 150 words."
)


async def drain_background_tasks(timeout_s: float = 10.0) -> None:
    """Give in-flight summaries a chance to finish on shutdown."""
    if BACKGROUND_TASKS:
        await asyncio.wait(list(BACKGROUND_TASKS), timeout=timeout_s)


def _outcome_code(
    status: str, error: ProviderError | None, internal_failure: bool, finish_reason: str | None = None
) -> str | None:
    """Code stored on the message. For complete replies it is a note, e.g. cut off by max_tokens."""
    if status == "complete":
        return "length_limit" if finish_reason == "length" else None
    if error is not None:
        return error.code
    if internal_failure:
        return "internal_error"
    if status == "cancelled":
        return "client_disconnected"
    return None


def _title_from(text: str) -> str:
    first_line = " ".join(text.split())
    return (
        first_line if len(first_line) <= TITLE_MAX_CHARS else first_line[: TITLE_MAX_CHARS - 1].rstrip() + "…"
    )


def _ms_since(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


def _log_rate_limit(headers: dict[str, str]) -> None:
    if headers:
        log.info(
            "provider.rate_limit",
            remaining_tokens=headers.get("x-ratelimit-remaining-tokens"),
            remaining_requests=headers.get("x-ratelimit-remaining-requests"),
            reset_tokens=headers.get("x-ratelimit-reset-tokens"),
        )
