"""Provider-independent types and errors.

Application code (chat orchestration, context building) only uses these types. Each provider
adapter translates them to and from its own REST API (roadmap §6.5, §41.1).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Role = Literal["system", "user", "assistant"]


# --- Requests -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class ChatRequest:
    model: str
    messages: list[ChatMessage]
    max_tokens: int
    temperature: float | None = None
    # Only sent to models flagged `reasoning = true` in the registry.
    reasoning_effort: str | None = None


# --- Responses / stream events ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    reasoning_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class UsageEvent:
    usage: Usage


@dataclass(frozen=True, slots=True)
class Finish:
    reason: str | None
    attempts: int
    # Parsed x-ratelimit-* headers of the successful attempt, if the provider sends them.
    rate_limit: dict[str, str] = field(default_factory=dict)


StreamEvent = TextDelta | UsageEvent | Finish


@dataclass(frozen=True, slots=True)
class ChatResult:
    text: str
    usage: Usage | None
    finish_reason: str | None
    attempts: int


# --- Errors -----------------------------------------------------------------------


class ProviderError(Exception):
    """Normalized provider failure. `code` is the public error code; `retryable` drives retry policy."""

    code = "provider_error"
    retryable = False
    http_status = 502

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
        attempts: int = 1,
        detail: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retry_after = retry_after
        self.attempts = attempts
        self.detail = detail


class ProviderNotConfigured(ProviderError):
    code = "provider_not_configured"
    http_status = 503


class ProviderAuthError(ProviderError):
    code = "provider_auth"
    http_status = 502


class ProviderBadRequest(ProviderError):
    code = "provider_bad_request"
    http_status = 502


class ProviderContextTooLarge(ProviderBadRequest):
    code = "context_too_large"
    http_status = 413


class ProviderRequestTooLarge(ProviderError):
    """The single request exceeds the account's per-minute token limit; retrying can never succeed."""

    code = "request_too_large"
    http_status = 413


class ProviderRateLimited(ProviderError):
    code = "provider_rate_limited"
    retryable = True
    http_status = 429


class ProviderUnavailable(ProviderError):
    code = "provider_unavailable"
    retryable = True
    http_status = 503


class ProviderTimeout(ProviderError):
    code = "provider_timeout"
    retryable = True
    http_status = 504


class ProviderMalformedResponse(ProviderError):
    code = "provider_bad_response"
    http_status = 502


class ProviderStreamInterrupted(ProviderError):
    """The stream broke after content was already emitted. Never retried automatically."""

    code = "provider_stream_interrupted"
    http_status = 502


# --- Adapter protocol ---------------------------------------------------------------


class ProviderAdapter(Protocol):
    name: str

    def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        """Yield TextDelta* then optionally UsageEvent, then exactly one Finish. Raises ProviderError."""
        ...

    async def complete(self, request: ChatRequest) -> ChatResult: ...

    async def aclose(self) -> None: ...
