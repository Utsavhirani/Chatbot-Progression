"""Shared FastAPI dependencies."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

import structlog
from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service as auth_service
from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import User
from app.db.session import get_session
from app.providers.base import ProviderAdapter
from app.providers.registry import ModelRegistry

DbSession = Annotated[AsyncSession, Depends(get_session)]


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_registry(request: Request) -> ModelRegistry:
    return request.app.state.registry


def get_provider(request: Request) -> ProviderAdapter:
    provider: ProviderAdapter | None = request.app.state.provider
    if provider is None:
        raise AppError(
            "provider_not_configured",
            "The AI provider is not configured on the server.",
            status_code=503,
        )
    return provider


def set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_days * 86400,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.session_cookie_name, path="/", httponly=True, secure=settings.secure_cookies, samesite="lax"
    )


async def current_user(
    request: Request,
    response: Response,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> User:
    """Resolve the session cookie to a user. The only source of user identity in the API."""
    token = request.cookies.get(settings.session_cookie_name)
    resolved = (
        await auth_service.resolve_session(db, token, timedelta(days=settings.session_ttl_days))
        if token
        else None
    )
    if resolved is None:
        raise AppError("unauthenticated", "Please sign in.", status_code=401)
    user, renewed = resolved
    if renewed:
        set_session_cookie(response, settings, token)
    structlog.contextvars.bind_contextvars(user_id=str(user.id))
    return user


CurrentUser = Annotated[User, Depends(current_user)]
Registry = Annotated[ModelRegistry, Depends(get_registry)]
AppSettings = Annotated[Settings, Depends(get_settings_dep)]
