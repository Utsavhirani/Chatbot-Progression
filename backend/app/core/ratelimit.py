"""In-process token-bucket rate limiter (single-process only; see docs/decisions.md #8)."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.core.errors import AppError


@dataclass
class _Bucket:
    tokens: float
    updated: float


class RateLimiter:
    def __init__(
        self,
        capacity: int,
        per_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 10_000,
    ) -> None:
        self.capacity = capacity
        self.refill_per_s = capacity / per_seconds
        self._clock = clock
        self._max_keys = max_keys
        self._buckets: dict[str, _Bucket] = {}

    def hit(self, key: str) -> float | None:
        """Consume one token. Returns None if allowed, else seconds until a token is available."""
        now = self._clock()
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= self._max_keys:
                self._evict(now)
            bucket = self._buckets[key] = _Bucket(tokens=self.capacity, updated=now)
        bucket.tokens = min(self.capacity, bucket.tokens + (now - bucket.updated) * self.refill_per_s)
        bucket.updated = now
        if bucket.tokens >= 1:
            bucket.tokens -= 1
            return None
        return (1 - bucket.tokens) / self.refill_per_s

    def check(self, key: str, message: str = "Too many requests. Please wait and try again.") -> None:
        wait = self.hit(key)
        if wait is not None:
            retry_after = max(1, math.ceil(wait))
            raise AppError(
                "rate_limited",
                message,
                status_code=429,
                retryable=True,
                headers={"Retry-After": str(retry_after)},
            )

    def _evict(self, now: float) -> None:
        full_after = self.capacity / self.refill_per_s
        stale = [k for k, b in self._buckets.items() if now - b.updated >= full_after]
        for k in stale or list(self._buckets)[: len(self._buckets) // 2]:
            del self._buckets[k]
