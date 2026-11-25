"""Bounded retry policy: exponential backoff with full jitter, honouring Retry-After (roadmap §3.1, §6.6).

Rules:
- Only errors marked `retryable` are retried, at most `max_attempts` attempts in total.
- Never retry once any content has been emitted to the caller (no silent replay).
- If the provider asks us to wait longer than `cap_s`, fail fast with the Retry-After value
  instead of holding the user's request open.
- Never retry past the overall deadline.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from app.providers.base import ProviderError


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_s: float = 0.5
    cap_s: float = 8.0

    def backoff(self, attempt: int, rng: random.Random | None = None) -> float:
        """Full-jitter delay after failed attempt number `attempt` (1-based)."""
        ceiling = min(self.cap_s, self.base_s * (2 ** (attempt - 1)))
        return (rng or random).uniform(0, ceiling)

    def next_delay(
        self,
        error: ProviderError,
        attempt: int,
        *,
        emitted_content: bool,
        remaining_s: float,
        rng: random.Random | None = None,
    ) -> float | None:
        """Seconds to wait before the next attempt, or None if we must not retry."""
        if emitted_content or not error.retryable or attempt >= self.max_attempts:
            return None
        if error.retry_after is not None and error.retry_after > self.cap_s:
            return None
        delay = self.backoff(attempt, rng)
        if error.retry_after is not None:
            delay = max(delay, error.retry_after)
        if delay >= remaining_s:
            return None
        return delay
