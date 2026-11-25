"""Authentication, sessions, CSRF origin check and login rate limiting."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import FastAPI
from sqlalchemy import select, update

from app.core.security import hash_token
from app.db.models import AuthSession, User
from tests.integration.conftest import signup


async def test_register_sets_httponly_session_cookie_and_me_works(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/auth/register", json={"email": "New@Example.com", "password": "pw-12345678"}
    )
    assert resp.status_code == 201
    assert resp.json()["email"] == "new@example.com"  # normalised
    cookie = resp.headers["set-cookie"].lower()
    assert "session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert "password" not in resp.text

    me = await client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["email"] == "new@example.com"


async def test_password_and_token_are_never_stored_in_plaintext(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    await signup(client, "carol@example.com", "plaintext-check-1")
    token = client.cookies["session"]
    async with app.state.db.sessionmaker() as db:
        user = await db.scalar(select(User))
        session = await db.scalar(select(AuthSession))
    assert user.password_hash.startswith("$argon2id$") and "plaintext-check-1" not in user.password_hash
    assert session.token_hash == hash_token(token) and token.encode() != session.token_hash


async def test_duplicate_email_is_rejected_case_insensitively(client: httpx.AsyncClient) -> None:
    await signup(client, "dup@example.com")
    resp = await client.post(
        "/api/auth/register", json={"email": "DUP@example.com", "password": "another-pw-1"}
    )
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "email_taken"


async def test_register_validation(client: httpx.AsyncClient) -> None:
    for body in (
        {"email": "not-an-email", "password": "longenough1"},
        {"email": "a@example.com", "password": "short"},
        {"email": "a@example.com"},
    ):
        resp = await client.post("/api/auth/register", json=body)
        assert resp.status_code == 422 and resp.json()["error"]["code"] == "validation_error"


async def test_login_wrong_password_and_unknown_email_look_identical(
    make_client: Callable[[], httpx.AsyncClient],
) -> None:
    await signup(make_client(), "dave@example.com", "right-password-1")
    c = make_client()
    wrong_pw = await c.post(
        "/api/auth/login", json={"email": "dave@example.com", "password": "wrong-password-1"}
    )
    unknown = await c.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "wrong-password-1"}
    )
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert "set-cookie" not in wrong_pw.headers

    ok = await c.post("/api/auth/login", json={"email": "DAVE@example.com", "password": "right-password-1"})
    assert ok.status_code == 200 and (await c.get("/api/auth/me")).status_code == 200


async def test_unauthenticated_and_forged_cookie_are_rejected(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/auth/me")).json()["error"]["code"] == "unauthenticated"
    client.cookies.set("session", "forged-token-value")
    assert (await client.get("/api/conversations")).status_code == 401


async def test_logout_invalidates_session_server_side(alice: httpx.AsyncClient) -> None:
    stolen = alice.cookies["session"]
    assert (await alice.post("/api/auth/logout")).status_code == 204
    assert (await alice.get("/api/auth/me")).status_code == 401
    # Even if the old token was copied before logout, it no longer works.
    alice.cookies.set("session", stolen)
    assert (await alice.get("/api/auth/me")).status_code == 401


async def test_expired_session_is_rejected_and_deleted(alice: httpx.AsyncClient, app: FastAPI) -> None:
    async with app.state.db.sessionmaker() as db:
        await db.execute(update(AuthSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        await db.commit()
    assert (await alice.get("/api/auth/me")).status_code == 401
    async with app.state.db.sessionmaker() as db:
        assert await db.scalar(select(AuthSession)) is None


async def test_session_is_renewed_on_use_after_interval(alice: httpx.AsyncClient, app: FastAPI) -> None:
    old = datetime.now(UTC) - timedelta(hours=2)
    async with app.state.db.sessionmaker() as db:
        await db.execute(update(AuthSession).values(last_seen_at=old, expires_at=old + timedelta(days=1)))
        await db.commit()
    resp = await alice.get("/api/auth/me")
    assert resp.status_code == 200 and "session=" in resp.headers.get("set-cookie", "")
    async with app.state.db.sessionmaker() as db:
        session = await db.scalar(select(AuthSession))
    assert session.expires_at > datetime.now(UTC) + timedelta(days=13)


async def test_cross_origin_state_change_is_rejected(alice: httpx.AsyncClient) -> None:
    evil = await alice.post("/api/conversations", json={}, headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403 and evil.json()["error"]["code"] == "csrf_rejected"
    allowed = await alice.post("/api/conversations", json={}, headers={"Origin": "http://localhost:5173"})
    assert allowed.status_code == 201
    same_origin = await alice.post("/api/conversations", json={}, headers={"Origin": "http://test"})
    assert same_origin.status_code == 201
    # Reads are not blocked.
    assert (
        await alice.get("/api/conversations", headers={"Origin": "https://evil.example"})
    ).status_code == 200


async def test_login_is_rate_limited(make_app: Callable[..., Awaitable[FastAPI]]) -> None:
    app = await make_app(login_rate_per_minute=3)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        body = {"email": "eve@example.com", "password": "guessing-123"}
        codes = [(await c.post("/api/auth/login", json=body)).status_code for _ in range(4)]
        assert codes == [401, 401, 401, 429]
        limited = await c.post("/api/auth/login", json=body)
        assert limited.json()["error"]["code"] == "rate_limited"
        assert int(limited.headers["retry-after"]) >= 1
