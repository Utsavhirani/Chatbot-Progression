"""Build the model context within a deliberate token budget (roadmap §6.3).

Order sent to the model:
    system prompt -> [summary of older turns, later] -> recent history (chronological) -> new user message

Policy:
- The system prompt and the new user message are always included; if they alone exceed the
  budget the request is rejected (message_too_long) rather than silently truncated.
- History is added newest-first until the budget is reached, then restored to chronological order.
- Only meaningful history is used: complete messages, and partial assistant replies (marked as
  interrupted). Failed/cancelled-empty replies and in-flight placeholders are skipped.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.conversations.tokens import estimate_message_tokens
from app.core.errors import AppError
from app.providers.base import ChatMessage

INTERRUPTED_NOTE = "\n\n[This earlier reply was interrupted before it finished.]"


class HistoryItem(Protocol):
    role: str
    content: str
    status: str


@dataclass(frozen=True, slots=True)
class BuiltContext:
    messages: list[ChatMessage]
    estimated_tokens: int
    history_included: int
    history_dropped: int


def compute_budget(
    *, configured_budget: int, context_window: int, max_output_tokens: int, safety_margin: int
) -> int:
    """Input-token budget: the configured cap, never more than the model window allows."""
    return max(0, min(configured_budget, context_window - max_output_tokens - safety_margin))


def _usable(item: HistoryItem) -> ChatMessage | None:
    if item.role == "user" and item.content.strip():
        return ChatMessage("user", item.content)
    if item.role == "assistant":
        if item.status == "complete" and item.content.strip():
            return ChatMessage("assistant", item.content)
        if item.status in ("partial", "cancelled") and item.content.strip():
            return ChatMessage("assistant", item.content + INTERRUPTED_NOTE)
    return None


def build_context(
    *,
    system_prompt: str | None,
    history: Sequence[HistoryItem],
    user_message: str,
    budget_tokens: int,
) -> BuiltContext:
    fixed: list[ChatMessage] = []
    if system_prompt:
        fixed.append(ChatMessage("system", system_prompt))
    current = ChatMessage("user", user_message)
    used = sum(estimate_message_tokens(m.content) for m in fixed) + estimate_message_tokens(current.content)
    if used > budget_tokens:
        raise AppError(
            "message_too_long",
            "This message is too long for the assistant to process. Please shorten it.",
            status_code=413,
        )

    candidates = [m for m in (_usable(h) for h in history) if m is not None]
    selected: list[ChatMessage] = []
    for msg in reversed(candidates):  # newest first
        cost = estimate_message_tokens(msg.content)
        if used + cost > budget_tokens:
            break  # stop at the first message that does not fit: keep history contiguous
        selected.append(msg)
        used += cost
    selected.reverse()

    # Don't start the window with an orphaned assistant reply (its question was trimmed away).
    while selected and selected[0].role == "assistant":
        used -= estimate_message_tokens(selected.pop(0).content)

    return BuiltContext(
        messages=[*fixed, *selected, current],
        estimated_tokens=used,
        history_included=len(selected),
        history_dropped=len(candidates) - len(selected),
    )
