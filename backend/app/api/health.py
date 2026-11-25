"""Liveness and readiness probes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    """The process is up and serving requests."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """The app can do useful work. Database check is added in Step 2."""
    provider = request.app.state.provider
    checks = {
        "provider": {
            "ok": provider is not None,
            "name": getattr(provider, "name", request.app.state.settings.provider),
            **({} if provider is not None else {"error": "provider_not_configured"}),
        },
    }
    ok = all(c["ok"] for c in checks.values())
    return JSONResponse({"status": "ok" if ok else "unavailable", "checks": checks}, 200 if ok else 503)
