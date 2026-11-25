"""Readiness and behaviour when the database is unavailable (roadmap §9 'Database unavailable')."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx
from fastapi import FastAPI

# Nothing listens on this port, so connections are refused.
DEAD_DB = "postgresql+asyncpg://assistant:assistant_dev_pw@127.0.0.1:1/assistant_test"


async def test_ready_ok_with_db_and_provider(client: httpx.AsyncClient) -> None:
    body = (await client.get("/health/ready")).json()
    assert body["status"] == "ok" and body["checks"]["database"] == {"ok": True}


async def test_db_down_reports_unready_and_api_returns_db_unavailable(
    make_app: Callable[..., Awaitable[FastAPI]],
) -> None:
    app = await make_app(database_url=DEAD_DB, db_connect_timeout_s=1)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        ready = await c.get("/health/ready")
        assert ready.status_code == 503
        assert ready.json()["checks"]["database"] == {"ok": False, "error": "db_unavailable"}

        live = await c.get("/health/live")
        assert live.status_code == 200  # process is alive even without a DB

        resp = await c.post("/api/auth/login", json={"email": "x@example.com", "password": "whatever-123"})
        assert resp.status_code == 503
        err = resp.json()["error"]
        assert err["code"] == "db_unavailable" and err["retryable"] is True
        assert "assistant_dev_pw" not in resp.text  # no connection details leak
