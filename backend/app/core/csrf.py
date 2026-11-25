"""CSRF defence for cookie-authenticated requests.

Session cookies are SameSite=Lax (blocks cross-site POSTs carrying the cookie in modern browsers).
In addition, every state-changing request that carries an Origin header must come from the app's
own origin or an explicitly allowed one. Requests without Origin (curl, server-to-server) are
allowed: they cannot ride on a victim's browser cookies.
"""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import error_body

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class OriginCheckMiddleware:
    def __init__(self, app: ASGIApp, allowed_origins: frozenset[str]) -> None:
        self.app = app
        self.allowed = allowed_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        origin = headers.get(b"origin", b"").decode("latin-1").rstrip("/")
        if origin and origin != "null":
            host = headers.get(b"host", b"").decode("latin-1")
            own = f"{scope.get('scheme', 'http')}://{host}"
            if origin != own and origin not in self.allowed:
                await self._reject(send)
                return
        elif origin == "null":
            await self._reject(send)
            return
        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(send: Send) -> None:
        body = json.dumps(error_body("csrf_rejected", "Request origin not allowed.")).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
