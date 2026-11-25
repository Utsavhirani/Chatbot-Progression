"""GroqCloud adapter — direct REST over HTTPX (OpenAI-compatible chat completions endpoint).

Behaviour verified by scripts/probe_groq.py (see docs/providers.md):
- Streaming: `data: {json}` lines terminated by `data: [DONE]`; usage arrives in the final chunk
  as `usage` and/or `x_groq.usage`.
- Reasoning models (gpt-oss) stream extra `reasoning` deltas; they are ignored here.
- 413 = a single request exceeds the per-minute token limit (not retryable even though the
  response carries Retry-After). 429 = limit temporarily exhausted (retryable).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx

from app.core.logging import get_logger
from app.providers.base import (
    ChatRequest,
    ChatResult,
    Finish,
    ProviderAuthError,
    ProviderBadRequest,
    ProviderContextTooLarge,
    ProviderError,
    ProviderMalformedResponse,
    ProviderRateLimited,
    ProviderRequestTooLarge,
    ProviderStreamInterrupted,
    ProviderTimeout,
    ProviderUnavailable,
    StreamEvent,
    TextDelta,
    Usage,
    UsageEvent,
)
from app.providers.retry import RetryPolicy
from app.providers.sse import StreamEndedEarly, iter_sse_json

log = get_logger(__name__)

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


class GroqProvider:
    name = "groq"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        policy: RetryPolicy | None = None,
        connect_timeout_s: float = 5.0,
        read_timeout_s: float = 30.0,
        total_timeout_s: float = 120.0,
        client: httpx.AsyncClient | None = None,
        sleep: Sleep = asyncio.sleep,
        clock: Clock = time.monotonic,
    ) -> None:
        self.policy = policy or RetryPolicy()
        self.total_timeout_s = total_timeout_s
        self._sleep = sleep
        self._clock = clock
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(connect=connect_timeout_s, read=read_timeout_s, write=10.0, pool=5.0),
        )
        self._headers = {"Authorization": f"Bearer {api_key}"}

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ public API

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        deadline = self._clock() + self.total_timeout_s
        attempt = 0
        while True:
            attempt += 1
            state = _AttemptState()
            try:
                async for event in self._stream_once(request, attempt, deadline, state):
                    yield event
                return
            except ProviderError as err:
                err.attempts = attempt
                delay = self.policy.next_delay(
                    err, attempt, emitted_content=state.emitted, remaining_s=deadline - self._clock()
                )
                self._log_failure(err, attempt, delay, streaming=True)
                if delay is None:
                    raise
                await self._sleep(delay)

    async def complete(self, request: ChatRequest) -> ChatResult:
        deadline = self._clock() + self.total_timeout_s
        attempt = 0
        while True:
            attempt += 1
            try:
                return await self._complete_once(request, attempt, deadline)
            except ProviderError as err:
                err.attempts = attempt
                delay = self.policy.next_delay(
                    err, attempt, emitted_content=False, remaining_s=deadline - self._clock()
                )
                self._log_failure(err, attempt, delay, streaming=False)
                if delay is None:
                    raise
                await self._sleep(delay)

    # ------------------------------------------------------------------ one attempt

    async def _stream_once(
        self, request: ChatRequest, attempt: int, deadline: float, state: _AttemptState
    ) -> AsyncIterator[StreamEvent]:
        payload = build_payload(request, stream=True)
        finish_reason: str | None = None
        usage: Usage | None = None
        try:
            async with self._client.stream(
                "POST", "/chat/completions", json=payload, headers=self._headers
            ) as resp:
                if resp.status_code != 200:
                    await resp.aread()
                    raise error_from_response(resp)
                rate_limit = rate_limit_headers(resp)
                async for chunk in iter_sse_json(resp.aiter_lines()):
                    if chunk.get("error"):
                        raise ProviderUnavailable(
                            "Provider reported an error mid-stream.", detail=chunk["error"]
                        )
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        content = delta.get("content")  # `reasoning` deltas are deliberately ignored
                        if content:
                            state.emitted = True
                            yield TextDelta(content)
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
                    raw_usage = chunk.get("usage") or (chunk.get("x_groq") or {}).get("usage")
                    if raw_usage:
                        usage = parse_usage(raw_usage)
                    if self._clock() > deadline:
                        raise ProviderTimeout("Generation exceeded the overall time limit.")
        except StreamEndedEarly as exc:
            raise self._interrupted_or(
                state, ProviderUnavailable("Provider stream ended unexpectedly.")
            ) from exc
        except httpx.TimeoutException as exc:
            raise self._interrupted_or(state, ProviderTimeout("Provider timed out.")) from exc
        except httpx.TransportError as exc:
            raise self._interrupted_or(
                state, ProviderUnavailable(f"Network error talking to provider ({type(exc).__name__}).")
            ) from exc
        except ProviderError as exc:
            if state.emitted and not isinstance(exc, ProviderStreamInterrupted):
                raise self._interrupted_or(state, exc) from exc
            raise

        if usage is not None:
            yield UsageEvent(usage)
        yield Finish(reason=finish_reason, attempts=attempt, rate_limit=rate_limit)

    async def _complete_once(self, request: ChatRequest, attempt: int, deadline: float) -> ChatResult:
        payload = build_payload(request, stream=False)
        timeout = max(0.1, deadline - self._clock())
        try:
            resp = await asyncio.wait_for(
                self._client.post("/chat/completions", json=payload, headers=self._headers), timeout
            )
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise ProviderTimeout("Provider timed out.") from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(f"Network error talking to provider ({type(exc).__name__}).") from exc
        if resp.status_code != 200:
            raise error_from_response(resp)
        try:
            body = resp.json()
            choice = body["choices"][0]
            text = choice["message"].get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ProviderMalformedResponse("Provider returned an unexpected response shape.") from exc
        raw_usage = body.get("usage") or (body.get("x_groq") or {}).get("usage")
        return ChatResult(
            text=text,
            usage=parse_usage(raw_usage) if raw_usage else None,
            finish_reason=choice.get("finish_reason"),
            attempts=attempt,
        )

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _interrupted_or(state: _AttemptState, err: ProviderError) -> ProviderError:
        if state.emitted:
            return ProviderStreamInterrupted(
                f"Stream interrupted after partial output: {err.message}", detail=err.code
            )
        return err

    @staticmethod
    def _log_failure(err: ProviderError, attempt: int, delay: float | None, *, streaming: bool) -> None:
        log.warning(
            "provider.attempt_failed",
            provider="groq",
            code=err.code,
            status=err.status_code,
            attempt=attempt,
            streaming=streaming,
            retry_after=err.retry_after,
            will_retry=delay is not None,
            retry_in_s=round(delay, 2) if delay is not None else None,
        )


class _AttemptState:
    __slots__ = ("emitted",)

    def __init__(self) -> None:
        self.emitted = False


# ---------------------------------------------------------------------- mapping functions


def build_payload(request: ChatRequest, *, stream: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        "max_tokens": request.max_tokens,
        "stream": stream,
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.reasoning_effort:
        payload["reasoning_effort"] = request.reasoning_effort
    if stream:
        payload["stream_options"] = {"include_usage": True}
    return payload


def parse_usage(raw: dict[str, Any]) -> Usage:
    details = raw.get("completion_tokens_details") or {}
    return Usage(
        input_tokens=raw.get("prompt_tokens"),
        output_tokens=raw.get("completion_tokens"),
        total_tokens=raw.get("total_tokens"),
        reasoning_tokens=details.get("reasoning_tokens"),
    )


def rate_limit_headers(resp: httpx.Response) -> dict[str, str]:
    return {k.lower(): v for k, v in resp.headers.items() if k.lower().startswith("x-ratelimit-")}


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _provider_message(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error") or {}
        return str(err.get("message") or "")[:500]
    except (ValueError, AttributeError):
        return resp.text[:500]


def error_from_response(resp: httpx.Response) -> ProviderError:
    status = resp.status_code
    detail = _provider_message(resp)
    kwargs: dict[str, Any] = {"status_code": status, "detail": detail}
    if status in (401, 403):
        return ProviderAuthError("The AI provider rejected our credentials.", **kwargs)
    if status == 413:
        return ProviderRequestTooLarge(
            "This request is larger than the AI provider allows per minute. Shorten the message.", **kwargs
        )
    if status == 429:
        return ProviderRateLimited(
            "The AI provider's rate limit was reached.", retry_after=_retry_after(resp), **kwargs
        )
    if status in (400, 404, 422):
        if "reduce the length" in detail.lower() or "context length" in detail.lower():
            return ProviderContextTooLarge("The conversation is too long for this model.", **kwargs)
        return ProviderBadRequest("The AI provider rejected the request.", **kwargs)
    if status == 408 or status == 498 or status >= 500:
        return ProviderUnavailable(
            "The AI provider is temporarily unavailable.", retry_after=_retry_after(resp), **kwargs
        )
    return ProviderBadRequest(f"Unexpected provider response (HTTP {status}).", **kwargs)
