"""Register / login / logout / me."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Request, Response, status

from app.api.deps import AppSettings, CurrentUser, DbSession, clear_session_cookie, set_session_cookie
from app.auth import service
from app.schemas.auth import Credentials, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    body: Credentials, request: Request, response: Response, db: DbSession, settings: AppSettings
) -> UserOut:
    request.app.state.register_limiter.check(f"register:{_client_ip(request)}")
    user = await service.register(db, body.email, body.password)
    token = await service.create_session(db, user, timedelta(days=settings.session_ttl_days))
    set_session_cookie(response, settings, token)
    return UserOut.model_validate(user)


@router.post("/login", response_model=UserOut)
async def login(
    body: Credentials, request: Request, response: Response, db: DbSession, settings: AppSettings
) -> UserOut:
    request.app.state.login_limiter.check(
        f"login:{_client_ip(request)}:{body.email.lower()}", "Too many sign-in attempts. Please wait."
    )
    user = await service.authenticate(db, body.email, body.password)
    token = await service.create_session(db, user, timedelta(days=settings.session_ttl_days))
    set_session_cookie(response, settings, token)
    return UserOut.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, db: DbSession, settings: AppSettings) -> None:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        await service.delete_session(db, token)
    clear_session_cookie(response, settings)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
