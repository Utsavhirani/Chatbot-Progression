"""Liveness and readiness probes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    """The process is up and serving requests."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """The app can do useful work: database reachable and provider configured."""
    provider = request.app.state.provider
    try:
        await request.app.state.db.ping()
        db_check: dict = {"ok": True}
    except Exception as exc:  # any failure means "not ready"; details only in logs
        log.warning("ready.db_failed", error_type=type(exc).__name__)
        db_check = {"ok": False, "error": "db_unavailable"}
    checks = {
        "database": db_check,
        "provider": {
            "ok": provider is not None,
            "name": getattr(provider, "name", request.app.state.settings.provider),
            **({} if provider is not None else {"error": "provider_not_configured"}),
        },
    }
    ok = all(c["ok"] for c in checks.values())
    return JSONResponse({"status": "ok" if ok else "unavailable", "checks": checks}, 200 if ok else 503)
