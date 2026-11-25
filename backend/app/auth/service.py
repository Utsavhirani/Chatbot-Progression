"""User registration, login and server-side sessions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import (
    hash_password,
    hash_token,
    needs_rehash,
    new_session_token,
    verify_password,
)
from app.db.models import AuthSession, User

# Sliding renewal is written at most this often, to avoid a DB write on every request.
RENEW_INTERVAL = timedelta(hours=1)


def _now() -> datetime:
    return datetime.now(UTC)


async def register(db: AsyncSession, email: str, password: str) -> User:
    user = User(email=email.strip().lower(), password_hash=hash_password(password))
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise AppError("email_taken", "An account with this email already exists.", status_code=409) from None
    return user


async def authenticate(db: AsyncSession, email: str, password: str) -> User:
    user = await db.scalar(select(User).where(User.email == email.strip().lower()))
    if not verify_password(user.password_hash if user else None, password) or user is None:
        raise AppError("invalid_credentials", "Incorrect email or password.", status_code=401)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        await db.commit()
    return user


async def create_session(db: AsyncSession, user: User, ttl: timedelta) -> str:
    """Create a session and return the raw token (to be set as the cookie; never stored)."""
    token = new_session_token()
    now = _now()
    db.add(AuthSession(token_hash=hash_token(token), user_id=user.id, expires_at=now + ttl, last_seen_at=now))
    await db.commit()
    return token


async def resolve_session(db: AsyncSession, token: str, ttl: timedelta) -> tuple[User, bool] | None:
    """Return (user, renewed) for a valid token, or None. Expired sessions are deleted."""
    row = (
        await db.execute(
            select(AuthSession, User)
            .join(User, User.id == AuthSession.user_id)
            .where(AuthSession.token_hash == hash_token(token))
        )
    ).first()
    if row is None:
        return None
    session, user = row
    now = _now()
    if session.expires_at <= now:
        await db.delete(session)
        await db.commit()
        return None
    renewed = False
    if now - session.last_seen_at >= RENEW_INTERVAL:
        session.last_seen_at = now
        session.expires_at = now + ttl
        await db.commit()
        renewed = True
    return user, renewed


async def delete_session(db: AsyncSession, token: str) -> None:
    await db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    await db.commit()
