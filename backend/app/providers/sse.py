"""Parser for OpenAI-style server-sent event streams (`data: {json}` lines, `data: [DONE]` sentinel)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from app.providers.base import ProviderMalformedResponse


class StreamEndedEarly(Exception):
    """The byte stream closed before the [DONE] sentinel."""


async def iter_sse_json(lines: AsyncIterator[str]) -> AsyncIterator[dict[str, Any]]:
    """Yield each JSON `data:` payload until `[DONE]`.

    Raises ProviderMalformedResponse for undecodable payloads and StreamEndedEarly if the
    stream ends without the sentinel.
    """
    async for raw in lines:
        line = raw.strip()
        if not line or line.startswith(":"):  # blank separator or SSE comment/keep-alive
            continue
        if not line.startswith("data:"):  # `event:` / `id:` / `retry:` fields are unused here
            continue
        data = line[len("data:") :].strip()
        if data == "[DONE]":
            return
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ProviderMalformedResponse("Provider sent an undecodable stream chunk.") from exc
        if not isinstance(payload, dict):
            raise ProviderMalformedResponse("Provider sent a non-object stream chunk.")
        yield payload
    raise StreamEndedEarly
