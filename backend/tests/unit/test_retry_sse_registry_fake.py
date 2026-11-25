"""Retry policy, SSE parser, model registry and fake provider."""

from __future__ import annotations

import random
from collections.abc import AsyncIterator

import pytest

from app.core.config import Settings
from app.providers.base import (
    ChatMessage,
    ChatRequest,
    Finish,
    ProviderAuthError,
    ProviderRateLimited,
    ProviderStreamInterrupted,
    ProviderUnavailable,
    TextDelta,
    UsageEvent,
)
from app.providers.fake import FakeProvider
from app.providers.groq import GroqProvider
from app.providers.registry import ModelRegistry, UnknownModelError, build_provider
from app.providers.retry import RetryPolicy
from app.providers.sse import StreamEndedEarly, iter_sse_json

# ------------------------------------------------------------------ retry policy

POLICY = RetryPolicy(max_attempts=3, base_s=0.5, cap_s=8.0)


def test_backoff_is_full_jitter_within_exponential_ceiling() -> None:
    rng = random.Random(1)
    for attempt, ceiling in [(1, 0.5), (2, 1.0), (3, 2.0), (10, 8.0)]:
        samples = [POLICY.backoff(attempt, rng) for _ in range(200)]
        assert all(0 <= s <= ceiling for s in samples)


def test_no_retry_when_not_retryable_or_exhausted_or_content_emitted() -> None:
    assert POLICY.next_delay(ProviderAuthError("x"), 1, emitted_content=False, remaining_s=100) is None
    assert POLICY.next_delay(ProviderUnavailable("x"), 3, emitted_content=False, remaining_s=100) is None
    assert POLICY.next_delay(ProviderUnavailable("x"), 1, emitted_content=True, remaining_s=100) is None


def test_retry_after_is_honoured_up_to_cap() -> None:
    assert (
        POLICY.next_delay(ProviderRateLimited("x", retry_after=3), 1, emitted_content=False, remaining_s=100)
        >= 3
    )
    assert (
        POLICY.next_delay(ProviderRateLimited("x", retry_after=30), 1, emitted_content=False, remaining_s=100)
        is None
    )


def test_no_retry_past_deadline() -> None:
    assert (
        POLICY.next_delay(ProviderRateLimited("x", retry_after=2), 1, emitted_content=False, remaining_s=1)
        is None
    )


# ------------------------------------------------------------------ SSE parser


async def _lines(*items: str) -> AsyncIterator[str]:
    for item in items:
        yield item


async def test_sse_skips_comments_blank_and_non_data_lines() -> None:
    lines = _lines(
        ": keep-alive", "", "event: message", 'data: {"a": 1}', "", "data: [DONE]", 'data: {"b": 2}'
    )
    assert [c async for c in iter_sse_json(lines)] == [{"a": 1}]


async def test_sse_without_done_raises_stream_ended_early() -> None:
    with pytest.raises(StreamEndedEarly):
        [c async for c in iter_sse_json(_lines('data: {"a": 1}'))]


# ------------------------------------------------------------------ registry & factory


def test_registry_loads_verified_models_and_default() -> None:
    reg = ModelRegistry.load()
    assert reg.default_model == "qwen/qwen3.8-27b"
    qwen = reg.get("qwen/qwen3.8-27b")
    assert qwen.streaming and qwen.tools and not qwen.reasoning
    assert reg.get("openai/gpt-oss-20b").reasoning_effort == "low"
    with pytest.raises(UnknownModelError):
        reg.get("allam-2-7b")  # probed and rejected (no tools, 4k context)


def test_registry_rejects_unknown_default_override() -> None:
    with pytest.raises(UnknownModelError):
        ModelRegistry.load(default_override="not-a-model")


def test_build_provider_variants() -> None:
    assert isinstance(build_provider(Settings(_env_file=None, provider="fake")), FakeProvider)
    assert build_provider(Settings(_env_file=None, provider="groq", groq_api_key=None)) is None
    assert build_provider(Settings(_env_file=None, provider="groq", groq_api_key="replace-me")) is None
    assert isinstance(
        build_provider(Settings(_env_file=None, provider="groq", groq_api_key="abc")), GroqProvider
    )


# ------------------------------------------------------------------ fake provider


def _req(text: str) -> ChatRequest:
    return ChatRequest(model="any", messages=[ChatMessage("user", text)], max_tokens=50)


async def test_fake_streams_echo_with_usage() -> None:
    events = [e async for e in FakeProvider(chunk_delay_s=0).stream(_req("hello world"))]
    text = "".join(e.text for e in events if isinstance(e, TextDelta))
    assert text == "(fake reply) You said: hello world"
    assert any(isinstance(e, UsageEvent) for e in events) and isinstance(events[-1], Finish)


async def test_fake_injected_failures() -> None:
    fake = FakeProvider(chunk_delay_s=0)
    with pytest.raises(ProviderRateLimited) as exc:
        [e async for e in fake.stream(_req("hi [fake:rate_limit]"))]
    assert exc.value.retry_after == 7

    received: list[str] = []
    with pytest.raises(ProviderStreamInterrupted):
        async for e in fake.stream(_req("one two three four [fake:cut]")):
            if isinstance(e, TextDelta):
                received.append(e.text)
    assert received  # some partial output came first
