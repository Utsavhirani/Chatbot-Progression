"""App-level behaviour: health, models endpoint, error envelope, request IDs, log redaction."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import pytest
import structlog
from fastapi import FastAPI

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import configure_logging, get_logger
from app.main import create_app
from app.providers.fake import FakeProvider


async def _client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            yield c


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings(_env_file=None, provider="fake"), provider=FakeProvider())

    @app.get("/boom")
    async def boom() -> None:
        raise AppError("conflict_in_progress", "Busy.", status_code=409, retryable=True)

    @app.get("/crash")
    async def crash() -> None:
        raise RuntimeError("secret internals")

    async for c in _client(app):
        yield c


@pytest.fixture
async def unconfigured_client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings(_env_file=None, provider="groq", groq_api_key=None))
    async for c in _client(app):
        yield c


async def test_live_and_ready(client: httpx.AsyncClient) -> None:
    assert (await client.get("/health/live")).json() == {"status": "ok"}
    ready = await client.get("/health/ready")
    assert ready.status_code == 200 and ready.json()["checks"]["provider"] == {"ok": True, "name": "fake"}


async def test_ready_reports_missing_provider_config(unconfigured_client: httpx.AsyncClient) -> None:
    resp = await unconfigured_client.get("/health/ready")
    assert resp.status_code == 503
    assert resp.json()["checks"]["provider"]["error"] == "provider_not_configured"


async def test_models_endpoint_lists_registry_without_secrets(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/models")).json()
    assert body["default_model"] == "qwen/qwen3.8-27b"
    assert {m["id"] for m in body["models"]} >= {"qwen/qwen3.8-27b", "openai/gpt-oss-20b"}
    assert "key" not in json.dumps(body).lower()


async def test_request_id_is_generated_or_propagated(client: httpx.AsyncClient) -> None:
    generated = await client.get("/health/live")
    assert len(generated.headers["x-request-id"]) == 32
    echoed = await client.get("/health/live", headers={"x-request-id": "client-req-12345"})
    assert echoed.headers["x-request-id"] == "client-req-12345"
    bogus = await client.get("/health/live", headers={"x-request-id": "bad id\n<script>"})
    assert bogus.headers["x-request-id"] != "bad id\n<script>"


async def test_app_error_uses_envelope_with_request_id(client: httpx.AsyncClient) -> None:
    resp = await client.get("/boom")
    err = resp.json()["error"]
    assert resp.status_code == 409
    assert err["code"] == "conflict_in_progress" and err["retryable"] is True
    assert err["request_id"] == resp.headers["x-request-id"]


async def test_unknown_route_and_unhandled_error_use_envelope(client: httpx.AsyncClient) -> None:
    assert (await client.get("/nope")).json()["error"]["code"] == "not_found"


async def test_unhandled_exception_returns_generic_500() -> None:
    app = create_app(Settings(_env_file=None, provider="fake"), provider=FakeProvider())

    @app.get("/crash")
    async def crash() -> None:
        raise RuntimeError("secret internals")

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/crash")
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "internal_error"
    assert "secret internals" not in resp.text


def test_logs_redact_sensitive_keys(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    structlog.contextvars.clear_contextvars()
    get_logger("t").info("evt", api_key="sk-live-123", authorization="Bearer x", input_tokens=5)
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["api_key"] == "[REDACTED]" and line["authorization"] == "[REDACTED]"
    assert line["input_tokens"] == 5  # token counts are not secrets
