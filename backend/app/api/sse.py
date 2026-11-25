"""Server-sent events response that reacts to client disconnects immediately.

Starlette's StreamingResponse (ASGI spec >= 2.4) only notices a disconnect when the next write
fails, which can be long after the user left while we keep consuming provider quota. This response
listens for `http.disconnect` concurrently and cancels generation as soon as it arrives; the event
generator is always closed explicitly so its cleanup (persisting the outcome) runs.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import anyio
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from app.core.logging import get_logger

log = get_logger(__name__)

SSE_HEADERS = [
    (b"content-type", b"text/event-stream; charset=utf-8"),
    (b"cache-control", b"no-cache, no-transform"),
    (b"x-accel-buffering", b"no"),  # disable proxy buffering (nginx)
]


def format_sse(event: str, data: Any) -> bytes:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode()


class SSEResponse(Response):
    media_type = "text/event-stream"

    def __init__(self, events: AsyncIterator[dict[str, Any]]) -> None:
        super().__init__(content=None, status_code=200)
        self.events = events

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Keep headers added by dependencies (e.g. a renewed session cookie), but our own content headers win.
        own = {name for name, _ in SSE_HEADERS} | {b"content-length"}
        headers = SSE_HEADERS + [(k, v) for k, v in self.raw_headers if k not in own]

        finished = False

        async with anyio.create_task_group() as tg:

            async def stream() -> None:
                nonlocal finished
                try:
                    await send({"type": "http.response.start", "status": 200, "headers": headers})
                    try:
                        async for item in self.events:
                            await send(
                                {
                                    "type": "http.response.body",
                                    "body": format_sse(item["event"], item["data"]),
                                    "more_body": True,
                                }
                            )
                    except Exception:
                        log.exception("sse.generator_failed")
                        body = format_sse(
                            "error",
                            {
                                "code": "internal_error",
                                "message": "An unexpected error occurred.",
                                "retryable": True,
                            },
                        )
                        await send({"type": "http.response.body", "body": body, "more_body": True})
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
                    finished = True
                except OSError:
                    log.info("sse.client_gone_on_send")
                finally:
                    with anyio.CancelScope(shield=True):
                        await self.events.aclose()  # type: ignore[attr-defined]
                    tg.cancel_scope.cancel()

            async def watch_disconnect() -> None:
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        if not finished:
                            log.info("sse.client_disconnected")
                        tg.cancel_scope.cancel()
                        return

            tg.start_soon(stream)
            tg.start_soon(watch_disconnect)
