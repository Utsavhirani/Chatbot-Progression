"""GroqProvider behaviour against mocked HTTP (respx). Covers roadmap §9 provider failure scenarios."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from app.providers.base import (
    ChatMessage,
    ChatRequest,
    Finish,
    ProviderAuthError,
    ProviderBadRequest,
    ProviderContextTooLarge,
    ProviderMalformedResponse,
    ProviderRateLimited,
    ProviderRequestTooLarge,
    ProviderStreamInterrupted,
    ProviderTimeout,
    ProviderUnavailable,
    TextDelta,
    UsageEvent,
)
from app.providers.groq import GroqProvider, build_payload
from app.providers.retry import RetryPolicy

BASE = "https://groq.test/openai/v1"
URL = f"{BASE}/chat/completions"

REQ = ChatRequest(
    model="qwen/qwen3.8-27b",
    messages=[ChatMessage("system", "Be brief."), ChatMessage("user", "Hi")],
    max_tokens=100,
    temperature=0.2,
)


def sse(*chunks: dict, done: bool = True) -> bytes:
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks)
    if done:
        body += "data: [DONE]\n\n"
    return body.encode()


def delta(text: str | None = None, finish: str | None = None, **extra) -> dict:
    d = {} if text is None else {"content": text}
    d.update(extra)
    return {"choices": [{"index": 0, "delta": d, "finish_reason": finish}]}


USAGE = {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}

OK_STREAM = sse(
    delta(role="assistant", text=""),
    delta("Hello"),
    delta(" there"),
    {**delta(finish="stop"), "x_groq": {"usage": USAGE}},
)


class Sleeps:
    """Records requested sleeps instead of waiting."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@pytest.fixture
def sleeps() -> Sleeps:
    return Sleeps()


@pytest.fixture
async def provider(sleeps: Sleeps) -> AsyncIterator[GroqProvider]:
    p = GroqProvider(
        api_key="test-key",
        base_url=BASE,
        policy=RetryPolicy(max_attempts=3, base_s=0.5, cap_s=8.0),
        sleep=sleeps,
    )
    yield p
    await p.aclose()


async def collect(provider: GroqProvider, req: ChatRequest = REQ) -> list:
    return [e async for e in provider.stream(req)]


def stream_response(body: bytes, status: int = 200, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status, content=body, headers={"content-type": "text/event-stream", **(headers or {})}
    )


# ------------------------------------------------------------------ happy paths


@respx.mock
async def test_stream_yields_text_usage_and_finish(provider: GroqProvider) -> None:
    route = respx.post(URL).mock(
        return_value=stream_response(OK_STREAM, headers={"x-ratelimit-remaining-tokens": "7900"})
    )
    events = await collect(provider)

    assert [e.text for e in events if isinstance(e, TextDelta)] == ["Hello", " there"]
    usage = next(e for e in events if isinstance(e, UsageEvent)).usage
    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens) == (12, 3, 15)
    finish = events[-1]
    assert isinstance(finish, Finish) and finish.reason == "stop" and finish.attempts == 1
    assert finish.rate_limit == {"x-ratelimit-remaining-tokens": "7900"}

    sent = json.loads(route.calls.last.request.content)
    assert sent["stream"] is True and sent["model"] == "qwen/qwen3.8-27b"
    assert route.calls.last.request.headers["authorization"] == "Bearer test-key"


@respx.mock
async def test_stream_ignores_reasoning_deltas_and_reads_top_level_usage(provider: GroqProvider) -> None:
    body = sse(
        delta(reasoning="thinking about it", channel="analysis"),
        delta("Answer"),
        {"choices": [], "usage": {**USAGE, "completion_tokens_details": {"reasoning_tokens": 5}}},
    )
    respx.post(URL).mock(return_value=stream_response(body))
    events = await collect(provider)
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "Answer"
    assert next(e for e in events if isinstance(e, UsageEvent)).usage.reasoning_tokens == 5


async def test_payload_only_includes_reasoning_effort_when_set() -> None:
    assert "reasoning_effort" not in build_payload(REQ, stream=False)
    req = ChatRequest(
        model="openai/gpt-oss-20b", messages=REQ.messages, max_tokens=50, reasoning_effort="low"
    )
    payload = build_payload(req, stream=True)
    assert payload["reasoning_effort"] == "low"
    assert payload["stream_options"] == {"include_usage": True}


@respx.mock
async def test_complete_returns_text_and_usage(provider: GroqProvider) -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": "pong"}, "finish_reason": "stop"}], "usage": USAGE},
        )
    )
    result = await provider.complete(REQ)
    assert result.text == "pong" and result.usage.total_tokens == 15 and result.attempts == 1


# ------------------------------------------------------------------ non-retryable errors


@respx.mock
async def test_invalid_key_is_not_retried(provider: GroqProvider, sleeps: Sleeps) -> None:
    route = respx.post(URL).mock(
        return_value=httpx.Response(
            401, json={"error": {"message": "Invalid API Key", "code": "invalid_api_key"}}
        )
    )
    with pytest.raises(ProviderAuthError) as exc:
        await collect(provider)
    assert route.call_count == 1 and sleeps.calls == []
    assert exc.value.code == "provider_auth"


@respx.mock
async def test_413_request_too_large_is_not_retried_despite_retry_after(provider: GroqProvider) -> None:
    route = respx.post(URL).mock(
        return_value=httpx.Response(
            413,
            headers={"retry-after": "2"},
            json={
                "error": {"message": "Request too large ... (TPM): Limit 8000", "code": "rate_limit_exceeded"}
            },
        )
    )
    with pytest.raises(ProviderRequestTooLarge):
        await collect(provider)
    assert route.call_count == 1


@respx.mock
async def test_context_length_400_maps_to_context_too_large(provider: GroqProvider) -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(
            400, json={"error": {"message": "Please reduce the length of the messages or completion."}}
        )
    )
    with pytest.raises(ProviderContextTooLarge):
        await collect(provider)


@respx.mock
async def test_malformed_request_400_is_bad_request(provider: GroqProvider) -> None:
    route = respx.post(URL).mock(
        return_value=httpx.Response(
            400, json={"error": {"message": "'messages' : minimum number of items is 1"}}
        )
    )
    with pytest.raises(ProviderBadRequest) as exc:
        await collect(provider)
    assert type(exc.value) is ProviderBadRequest and route.call_count == 1


# ------------------------------------------------------------------ retryable errors


@respx.mock
async def test_429_with_short_retry_after_is_retried_then_succeeds(
    provider: GroqProvider, sleeps: Sleeps
) -> None:
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "2"}, json={"error": {"message": "slow down"}}),
            stream_response(OK_STREAM),
        ]
    )
    events = await collect(provider)
    assert route.call_count == 2
    assert sleeps.calls and sleeps.calls[0] >= 2.0  # honoured Retry-After
    assert isinstance(events[-1], Finish) and events[-1].attempts == 2


@respx.mock
async def test_429_with_long_retry_after_fails_fast(provider: GroqProvider, sleeps: Sleeps) -> None:
    route = respx.post(URL).mock(
        return_value=httpx.Response(429, headers={"retry-after": "30"}, json={"error": {"message": "TPM"}})
    )
    with pytest.raises(ProviderRateLimited) as exc:
        await collect(provider)
    assert route.call_count == 1 and sleeps.calls == []
    assert exc.value.retry_after == 30.0


@respx.mock
async def test_5xx_is_retried_with_bounded_attempts(provider: GroqProvider, sleeps: Sleeps) -> None:
    route = respx.post(URL).mock(
        return_value=httpx.Response(503, json={"error": {"message": "over capacity"}})
    )
    with pytest.raises(ProviderUnavailable) as exc:
        await collect(provider)
    assert route.call_count == 3  # max_attempts, never infinite
    assert len(sleeps.calls) == 2
    assert all(0 <= s <= 8.0 for s in sleeps.calls)
    assert exc.value.attempts == 3


@respx.mock
async def test_timeout_is_retried_then_raises_provider_timeout(provider: GroqProvider) -> None:
    route = respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(ProviderTimeout):
        await collect(provider)
    assert route.call_count == 3


@respx.mock
async def test_connection_error_then_success(provider: GroqProvider) -> None:
    route = respx.post(URL).mock(side_effect=[httpx.ConnectError("refused"), stream_response(OK_STREAM)])
    events = await collect(provider)
    assert route.call_count == 2 and isinstance(events[-1], Finish)


# ------------------------------------------------------------------ streaming failures


class _CutStream(httpx.AsyncByteStream):
    """Emits some SSE bytes, then the connection drops."""

    def __init__(self, first: bytes) -> None:
        self.first = first

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self.first
        raise httpx.ReadError("connection reset")


@respx.mock
async def test_stream_cut_after_content_is_interrupted_and_not_retried(provider: GroqProvider) -> None:
    route = respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            stream=_CutStream(sse(delta("Partial"), done=False)),
            headers={"content-type": "text/event-stream"},
        )
    )
    received: list[str] = []
    with pytest.raises(ProviderStreamInterrupted):
        async for event in provider.stream(REQ):
            if isinstance(event, TextDelta):
                received.append(event.text)
    assert received == ["Partial"]
    assert route.call_count == 1  # no silent replay after output was emitted


@respx.mock
async def test_stream_ending_without_done_before_content_is_retried(provider: GroqProvider) -> None:
    route = respx.post(URL).mock(
        side_effect=[stream_response(sse(delta(role="assistant"), done=False)), stream_response(OK_STREAM)]
    )
    events = await collect(provider)
    assert route.call_count == 2 and isinstance(events[-1], Finish)


@respx.mock
async def test_malformed_stream_chunk_raises_bad_response(provider: GroqProvider) -> None:
    respx.post(URL).mock(return_value=stream_response(b"data: {not json\n\n"))
    with pytest.raises(ProviderMalformedResponse):
        await collect(provider)


@respx.mock
async def test_malformed_chunk_after_content_is_interrupted(provider: GroqProvider) -> None:
    respx.post(URL).mock(return_value=stream_response(sse(delta("Hi"), done=False) + b"data: {oops\n\n"))
    with pytest.raises(ProviderStreamInterrupted):
        await collect(provider)


@respx.mock
async def test_complete_with_unexpected_shape_raises_bad_response(provider: GroqProvider) -> None:
    respx.post(URL).mock(return_value=httpx.Response(200, json={"unexpected": True}))
    with pytest.raises(ProviderMalformedResponse):
        await provider.complete(REQ)


@respx.mock
async def test_overall_deadline_stops_retries(sleeps: Sleeps) -> None:
    now = [0.0]
    p = GroqProvider(
        api_key="k",
        base_url=BASE,
        policy=RetryPolicy(max_attempts=5, base_s=0.5, cap_s=8.0),
        total_timeout_s=1.0,
        sleep=sleeps,
        clock=lambda: now[0],
    )
    route = respx.post(URL).mock(
        return_value=httpx.Response(503, headers={"retry-after": "2"}, json={"error": {"message": "x"}})
    )
    with pytest.raises(ProviderUnavailable):
        await collect(p)
    assert route.call_count == 1  # waiting 2s would exceed the 1s deadline
    await p.aclose()
