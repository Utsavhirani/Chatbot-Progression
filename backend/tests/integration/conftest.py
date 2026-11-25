"""Integration fixtures: a real Postgres test database (docker compose), migrated once per session.

Requires the local DB container:  docker compose up -d   (from the repo root)
Each test starts with empty tables.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.db.models import Base
from app.main import create_app
from app.providers.fake import FakeProvider

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DB_URL = Settings().test_database_url
_DEFAULT = object()
TABLES = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))


async def _reset_schema() -> None:
    engine = create_async_engine(TEST_DB_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def migrated_db() -> str:
    """Drop and rebuild the test schema via Alembic, exercising the real migration."""
    if "assistant_test" not in TEST_DB_URL:
        pytest.exit(f"Refusing to wipe a non-test database: {TEST_DB_URL}", returncode=2)
    try:
        asyncio.run(_reset_schema())
    except OSError as exc:
        pytest.exit(f"Test database unreachable ({exc}). Start it with: docker compose up -d", returncode=2)
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", TEST_DB_URL)
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
    return TEST_DB_URL


def test_settings(**overrides: object) -> Settings:
    base = {
        "_env_file": None,
        "env": "test",
        "provider": "fake",
        "database_url": TEST_DB_URL,
        "log_level": "WARNING",
        "allowed_origins": "http://localhost:5173",
        "login_rate_per_minute": 1000,
        "register_rate_per_minute": 1000,
        "chat_rate_per_minute": 1000,
    }
    return Settings(**{**base, **overrides})


@pytest.fixture
async def make_app(migrated_db: str) -> AsyncIterator[Callable[..., Awaitable[FastAPI]]]:
    """Factory: build an app (with lifespan started) using test settings and optional overrides."""
    engine = create_async_engine(migrated_db)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    await engine.dispose()

    contexts = []

    async def _make(provider_obj: object = _DEFAULT, **overrides: object) -> FastAPI:
        """`provider_obj=None` lets the app build its provider from settings (e.g. unconfigured Groq)."""
        chosen = FakeProvider(chunk_delay_s=0) if provider_obj is _DEFAULT else provider_obj
        app = create_app(test_settings(**overrides), provider=chosen)
        ctx = app.router.lifespan_context(app)
        await ctx.__aenter__()
        contexts.append(ctx)
        return app

    yield _make
    for ctx in reversed(contexts):
        await ctx.__aexit__(None, None, None)


@pytest.fixture
async def app(make_app: Callable[..., Awaitable[FastAPI]]) -> FastAPI:
    return await make_app()


@pytest.fixture
async def make_client(app: FastAPI) -> AsyncIterator[Callable[[], httpx.AsyncClient]]:
    """Factory for independent clients (separate cookie jars = separate browsers/users)."""
    clients: list[httpx.AsyncClient] = []

    def _make() -> httpx.AsyncClient:
        c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        clients.append(c)
        return c

    yield _make
    for c in clients:
        await c.aclose()


@pytest.fixture
async def client(make_client: Callable[[], httpx.AsyncClient]) -> httpx.AsyncClient:
    return make_client()


async def signup(client: httpx.AsyncClient, email: str, password: str = "correct horse 1") -> dict:
    resp = await client.post("/api/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
async def alice(make_client: Callable[[], httpx.AsyncClient]) -> httpx.AsyncClient:
    c = make_client()
    await signup(c, "alice@example.com")
    return c


@pytest.fixture
async def bob(make_client: Callable[[], httpx.AsyncClient]) -> httpx.AsyncClient:
    c = make_client()
    await signup(c, "bob@example.com")
    return c
