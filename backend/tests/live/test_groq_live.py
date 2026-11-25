"""Opt-in tests against the real Groq API. Run: python -m uv run pytest -m live

Kept tiny to respect free-tier limits (docs/providers.md).
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.providers.base import ChatMessage, ChatRequest, Finish, ProviderAuthError, TextDelta, UsageEvent
from app.providers.groq import GroqProvider
from app.providers.registry import ModelRegistry, build_provider

pytestmark = pytest.mark.live


@pytest.fixture
async def groq() -> GroqProvider:
    provider = build_provider(Settings(provider="groq"))
    if provider is None:
        pytest.skip("GROQ_API_KEY not configured")
    yield provider
    await provider.aclose()


def _request(text: str) -> ChatRequest:
    reg = ModelRegistry.load()
    model = reg.get(reg.default_model)
    return ChatRequest(
        model=model.id,
        messages=[ChatMessage("system", "Answer in one short sentence."), ChatMessage("user", text)],
        max_tokens=model.default_max_tokens,
        temperature=0.2,
        reasoning_effort=model.reasoning_effort if model.reasoning else None,
    )


async def test_live_complete(groq: GroqProvider) -> None:
    result = await groq.complete(_request("Say hello to a customer."))
    assert result.text.strip()
    assert result.usage and result.usage.input_tokens and result.usage.output_tokens


async def test_live_stream(groq: GroqProvider) -> None:
    events = [e async for e in groq.stream(_request("Name one benefit of fast support replies."))]
    text = "".join(e.text for e in events if isinstance(e, TextDelta))
    assert text.strip()
    assert any(isinstance(e, UsageEvent) for e in events)
    assert isinstance(events[-1], Finish) and events[-1].rate_limit  # headers observed


async def test_live_invalid_key_is_auth_error() -> None:
    bad = GroqProvider(api_key="invalid-key-for-test", base_url=Settings().groq_base_url)
    with pytest.raises(ProviderAuthError):
        await bad.complete(_request("hi"))
    await bad.aclose()
