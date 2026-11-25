"""Deterministic offline provider for tests, e2e (Playwright) and demos without an API key.

Select with PROVIDER=fake. The reply echoes the last user message. Failures can be injected
by putting a marker anywhere in the last user message:

    [fake:rate_limit]   -> ProviderRateLimited (retry_after=7)
    [fake:unavailable]  -> ProviderUnavailable
    [fake:timeout]      -> ProviderTimeout
    [fake:auth]         -> ProviderAuthError
    [fake:too_large]    -> ProviderRequestTooLarge
    [fake:malformed]    -> ProviderMalformedResponse
    [fake:cut]          -> emits part of the reply, then ProviderStreamInterrupted
    [fake:slow]         -> streams with a longer per-chunk delay (for cancel tests)
    [fake:fail_once]    -> ProviderUnavailable the first time a given message is seen, then succeeds
    [fake:length]       -> completes with finish_reason "length" (reply cut off by max_tokens)

Tests can also queue one-shot failures: `provider.fail_next.append(ProviderUnavailable(...))`.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator

from app.providers.base import (
    ChatRequest,
    ChatResult,
    Finish,
    ProviderAuthError,
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

_MARKER = re.compile(r"\[fake:([a-z_]+)\]")

_FAILURES: dict[str, ProviderError] = {
    "rate_limit": ProviderRateLimited("Fake rate limit.", status_code=429, retry_after=7),
    "unavailable": ProviderUnavailable("Fake outage.", status_code=503),
    "timeout": ProviderTimeout("Fake timeout."),
    "auth": ProviderAuthError("Fake auth failure.", status_code=401),
    "too_large": ProviderRequestTooLarge("Fake too large.", status_code=413),
    "malformed": ProviderMalformedResponse("Fake malformed response."),
}


class FakeProvider:
    name = "fake"

    def __init__(self, chunk_delay_s: float = 0.02, slow_delay_s: float = 0.5) -> None:
        self.chunk_delay_s = chunk_delay_s
        self.slow_delay_s = slow_delay_s
        self.requests: list[ChatRequest] = []  # recorded for test assertions
        # Errors raised (once each, in order) by the next stream() calls, before any output.
        self.fail_next: list[ProviderError] = []
        self._failed_once: set[str] = set()

    async def aclose(self) -> None:
        return None

    @staticmethod
    def _last_user(request: ChatRequest) -> str:
        return next((m.content for m in reversed(request.messages) if m.role == "user"), "")

    def _reply(self, request: ChatRequest) -> str:
        text = _MARKER.sub("", self._last_user(request)).strip()
        return f"(fake reply) You said: {text}" if text else "(fake reply) Hello!"

    def _usage(self, request: ChatRequest, reply: str) -> Usage:
        prompt = sum(len(m.content) for m in request.messages) // 4 + 4 * len(request.messages)
        out = max(1, len(reply) // 4)
        return Usage(input_tokens=prompt, output_tokens=out, total_tokens=prompt + out)

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        if self.fail_next:
            raise self.fail_next.pop(0)
        markers = set(_MARKER.findall(self._last_user(request)))
        if "fail_once" in markers and self._last_user(request) not in self._failed_once:
            self._failed_once.add(self._last_user(request))
            raise ProviderUnavailable("Fake one-time outage.", status_code=503)
        for name, err in _FAILURES.items():
            if name in markers:
                raise type(err)(err.message, status_code=err.status_code, retry_after=err.retry_after)
        reply = self._reply(request)
        words = reply.split(" ")
        delay = self.slow_delay_s if "slow" in markers else self.chunk_delay_s
        for i, word in enumerate(words):
            if "cut" in markers and i == len(words) // 2:
                raise ProviderStreamInterrupted("Fake stream cut after partial output.")
            if delay:
                await asyncio.sleep(delay)
            yield TextDelta(word if i == 0 else " " + word)
        yield UsageEvent(self._usage(request, reply))
        yield Finish(reason="length" if "length" in markers else "stop", attempts=1)

    async def complete(self, request: ChatRequest) -> ChatResult:
        text: list[str] = []
        usage = None
        async for event in self.stream(request):
            if isinstance(event, TextDelta):
                text.append(event.text)
            elif isinstance(event, UsageEvent):
                usage = event.usage
        return ChatResult(text="".join(text), usage=usage, finish_reason="stop", attempts=1)
