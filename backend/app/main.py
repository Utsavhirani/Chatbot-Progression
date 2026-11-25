"""FastAPI application factory.

Run (from backend/):  python -m uv run uvicorn app.main:app --reload
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import auth, chat, conversations, health, models
from app.chat.service import drain_background_tasks, release_abandoned_streams
from app.core.config import Settings, get_settings
from app.core.csrf import OriginCheckMiddleware
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.core.ratelimit import RateLimiter
from app.db.session import Database
from app.providers.base import ProviderAdapter
from app.providers.registry import ModelRegistry, build_provider

log = get_logger(__name__)


def create_app(settings: Settings | None = None, provider: ProviderAdapter | None = None) -> FastAPI:
    """Build the app. Tests may inject `settings` and a ready-made `provider`."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.db = Database(settings)
        try:
            released = await release_abandoned_streams(app.state.db.sessionmaker)
            if released:
                log.warning("chat.abandoned_streams_released", count=released)
        except Exception as exc:  # DB may be down at startup; /health/ready will report it
            log.warning("startup.db_unavailable", error_type=type(exc).__name__)
        app.state.provider = provider if provider is not None else build_provider(settings)
        if app.state.provider is None:
            log.warning("provider.not_configured", provider=settings.provider)
        log.info(
            "app.started",
            env=settings.env,
            provider=getattr(app.state.provider, "name", None),
            default_model=app.state.registry.default_model,
        )
        try:
            yield
        finally:
            await drain_background_tasks()
            if app.state.provider is not None:
                await app.state.provider.aclose()
            await app.state.db.dispose()

    app = FastAPI(title="AI Business Assistant", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.registry = ModelRegistry.load(default_override=settings.default_model)
    app.state.provider = None
    app.state.login_limiter = RateLimiter(settings.login_rate_per_minute, 60)
    app.state.register_limiter = RateLimiter(settings.register_rate_per_minute, 60)
    app.state.chat_limiter = RateLimiter(settings.chat_rate_per_minute, 60)

    # Added last = outermost: request IDs exist even for CSRF rejections.
    app.add_middleware(OriginCheckMiddleware, allowed_origins=settings.allowed_origin_set)
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    for router in (health.router, models.router, auth.router, conversations.router, chat.router):
        app.include_router(router)
    return app


app = create_app()
