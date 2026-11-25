"""Context budgeting (roadmap §6.3) and token estimation."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.conversations.context import INTERRUPTED_NOTE, build_context, compute_budget
from app.conversations.tokens import estimate_message_tokens, estimate_text_tokens
from app.core.errors import AppError


@dataclass
class H:
    role: str
    content: str
    status: str = "complete"


def test_estimates_are_conservative_chars_over_4_plus_overhead() -> None:
    assert estimate_text_tokens("") == 0
    assert estimate_text_tokens("abcd") == 1 and estimate_text_tokens("abcde") == 2
    assert estimate_message_tokens("abcd" * 10) == 17


def test_budget_respects_configured_cap_and_model_window() -> None:
    assert (
        compute_budget(
            configured_budget=3000, context_window=131072, max_output_tokens=800, safety_margin=256
        )
        == 3000
    )
    assert (
        compute_budget(configured_budget=3000, context_window=4096, max_output_tokens=2000, safety_margin=256)
        == 1840
    )
    assert (
        compute_budget(configured_budget=3000, context_window=1000, max_output_tokens=2000, safety_margin=0)
        == 0
    )


def test_everything_fits_in_order_with_system_first() -> None:
    history = [H("user", "q1"), H("assistant", "a1"), H("user", "q2"), H("assistant", "a2")]
    ctx = build_context(system_prompt="Be nice.", history=history, user_message="q3", budget_tokens=1000)
    assert [(m.role, m.content) for m in ctx.messages] == [
        ("system", "Be nice."),
        ("user", "q1"),
        ("assistant", "a1"),
        ("user", "q2"),
        ("assistant", "a2"),
        ("user", "q3"),
    ]
    assert ctx.history_included == 4 and ctx.history_dropped == 0


def test_oldest_history_is_trimmed_first_and_window_starts_with_user() -> None:
    long = "x" * 400  # ~104 tokens each
    history = [H("user", long), H("assistant", long), H("user", long), H("assistant", long)]
    ctx = build_context(system_prompt=None, history=history, user_message="now", budget_tokens=320)
    # Room for ~3 history messages; the oldest kept one would be an orphaned assistant reply -> dropped too.
    roles = [m.role for m in ctx.messages]
    assert roles == ["user", "assistant", "user"]
    assert ctx.messages[-1].content == "now"
    assert ctx.history_dropped == 2
    assert ctx.estimated_tokens <= 320


def test_failed_and_empty_replies_are_skipped_and_partial_is_marked() -> None:
    history = [
        H("user", "q1"),
        H("assistant", "", "failed"),
        H("user", "q2"),
        H("assistant", "half an answer", "partial"),
        H("assistant", "", "streaming"),
    ]
    ctx = build_context(system_prompt=None, history=history, user_message="q3", budget_tokens=1000)
    contents = [m.content for m in ctx.messages]
    assert contents == ["q1", "q2", "half an answer" + INTERRUPTED_NOTE, "q3"]


def test_message_that_cannot_fit_is_rejected_not_truncated() -> None:
    with pytest.raises(AppError) as exc:
        build_context(system_prompt="sys", history=[], user_message="y" * 5000, budget_tokens=500)
    assert exc.value.code == "message_too_long" and exc.value.status_code == 413


def test_summary_is_included_after_system_prompt_and_counted() -> None:
    from app.conversations.context import SUMMARY_PREFIX

    ctx = build_context(
        system_prompt="sys",
        history=[H("user", "recent q")],
        user_message="now",
        budget_tokens=1000,
        summary="S",
    )
    assert [(m.role, m.content) for m in ctx.messages] == [
        ("system", "sys"),
        ("system", SUMMARY_PREFIX + "S"),
        ("user", "recent q"),
        ("user", "now"),
    ]


def test_dropped_through_seq_points_at_newest_dropped_message() -> None:
    @dataclass
    class S(H):
        seq: int = 0

    long = "x" * 400
    history = [
        S("user", long, seq=1),
        S("assistant", long, seq=2),
        S("user", long, seq=3),
        S("assistant", "a", seq=4),
    ]
    ctx = build_context(system_prompt=None, history=history, user_message="q", budget_tokens=130)
    assert ctx.history_dropped == 2 and ctx.dropped_through_seq == 2
    none_dropped = build_context(system_prompt=None, history=history[2:], user_message="q", budget_tokens=500)
    assert none_dropped.dropped_through_seq is None
