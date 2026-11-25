"""Self-check of configuration, database and AI provider.

Usage:
    python -m app.doctor            # local (from backend/)
    python -m app.doctor --live     # also send one tiny chat request to the provider
    python -m app.doctor --json     # machine-readable output
    docker compose exec api python -m app.doctor

Exit code: 0 = all checks pass (warnings allowed), 1 = at least one check failed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings, get_settings
from app.providers.base import ChatMessage, ChatRequest, ProviderError
from app.providers.registry import ModelRegistry, UnknownModelError, build_provider

BACKEND_DIR = Path(__file__).resolve().parents[1]


@dataclass
class Check:
    name: str
    status: str  # ok | warn | fail | skip
    detail: str


def _ok(name: str, detail: str) -> Check:
    return Check(name, "ok", detail)


def _warn(name: str, detail: str) -> Check:
    return Check(name, "warn", detail)


def _fail(name: str, detail: str) -> Check:
    return Check(name, "fail", detail)


def _redacted_db_url(url: str) -> str:
    try:
        from sqlalchemy.engine import make_url

        return make_url(url).render_as_string(hide_password=True)
    except Exception:
        return "<unparseable>"


# --------------------------------------------------------------------- config


def check_config(settings: Settings) -> list[Check]:
    checks: list[Check] = [_ok("config.env", f"ENV={settings.env}, PROVIDER={settings.provider}")]
    try:
        registry = ModelRegistry.load(default_override=settings.default_model)
        checks.append(
            _ok("config.default_model", f"{registry.default_model} ({len(registry.all())} models allowed)")
        )
    except UnknownModelError as exc:
        checks.append(_fail("config.default_model", f"{exc} Fix DEFAULT_MODEL in .env."))

    if settings.provider == "groq":
        key = settings.groq_api_key.get_secret_value().strip() if settings.groq_api_key else ""
        if not key or key == "replace-me":
            checks.append(
                _fail("config.groq_api_key", "GROQ_API_KEY is missing. Get one at console.groq.com.")
            )
        else:
            checks.append(_ok("config.groq_api_key", f"set ({len(key)} characters)"))
    else:
        checks.append(_warn("config.provider", "PROVIDER=fake: replies are simulated (no real AI)."))

    if settings.env == "prod" and not settings.secure_cookies:
        checks.append(
            _warn(
                "config.cookies",
                "COOKIE_SECURE=false: fine for http://localhost; use HTTPS when sharing publicly.",
            )
        )
    if settings.context_budget_tokens + 800 > 8000 and settings.provider == "groq":
        checks.append(
            _warn(
                "config.context_budget", "CONTEXT_BUDGET_TOKENS is large for the Groq free tier (8000 TPM)."
            )
        )
    return checks


# --------------------------------------------------------------------- database


async def check_database(settings: Settings) -> list[Check]:
    url = settings.database_url
    engine = create_async_engine(url, connect_args={"timeout": settings.db_connect_timeout_s})
    checks: list[Check] = []
    try:
        async with engine.connect() as conn:
            version = (await conn.execute(text("SHOW server_version"))).scalar_one()
            checks.append(_ok("db.connection", f"PostgreSQL {version} at {_redacted_db_url(url)}"))
            exts = set((await conn.execute(text("SELECT name FROM pg_available_extensions"))).scalars())
            missing = {"citext", "vector"} - exts
            if missing:
                checks.append(
                    _warn(
                        "db.extensions", f"not available: {', '.join(sorted(missing))} (vector needed in V2)"
                    )
                )
            else:
                checks.append(_ok("db.extensions", "citext and pgvector available"))
            has_table = (
                await conn.execute(text("SELECT to_regclass('public.alembic_version') IS NOT NULL"))
            ).scalar_one()
            current = (
                (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one_or_none()
                if has_table
                else None
            )
    except Exception as exc:  # report, don't crash
        name = type(exc).__name__
        # SQLAlchemy/asyncpg wrap the driver error several levels deep; walk the whole chain.
        chain, e = [], exc
        while e is not None and len(chain) < 10:
            chain.append(e)
            e = getattr(e, "orig", None) or e.__cause__
        sqlstates = {getattr(x, "sqlstate", None) for x in chain}
        if sqlstates & {"28P01", "28000"}:  # invalid_password / invalid_authorization_specification
            hint = (
                "the database rejected the password. POSTGRES_PASSWORD in .env does not match the existing "
                "database volume (see docs/sharing.md)."
            )
        else:
            hint = "Is the database running? (docker compose up -d db)"
        checks.append(_fail("db.connection", f"cannot connect to {_redacted_db_url(url)} ({name}). {hint}"))
        return checks
    finally:
        await engine.dispose()

    head = _migration_head()
    if current is None:
        checks.append(_fail("db.migrations", "schema not created. Run: alembic upgrade head"))
    elif head and current != head:
        checks.append(
            _fail("db.migrations", f"database at {current}, code expects {head}. Run: alembic upgrade head")
        )
    else:
        checks.append(_ok("db.migrations", f"up to date ({current})"))
    return checks


def _migration_head() -> str | None:
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
        return ScriptDirectory.from_config(cfg).get_current_head()
    except Exception:
        return None


# --------------------------------------------------------------------- provider


async def check_provider(settings: Settings, live: bool) -> list[Check]:
    if settings.provider != "groq":
        return [Check("provider", "skip", "fake provider: nothing to check")]
    key = settings.groq_api_key.get_secret_value().strip() if settings.groq_api_key else ""
    if not key or key == "replace-me":
        return [Check("provider", "skip", "no API key configured")]

    checks: list[Check] = []
    try:
        async with httpx.AsyncClient(base_url=settings.groq_base_url, timeout=10) as client:
            resp = await client.get("/models", headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError as exc:
        return [_fail("provider.reachable", f"cannot reach {settings.groq_base_url} ({type(exc).__name__})")]
    if resp.status_code in (401, 403):
        return [_fail("provider.api_key", "Groq rejected the API key (invalid or revoked).")]
    if resp.status_code != 200:
        return [_fail("provider.reachable", f"Groq returned HTTP {resp.status_code}")]
    checks.append(_ok("provider.api_key", "accepted by Groq"))

    available = {m.get("id") for m in resp.json().get("data", []) if m.get("active", True)}
    registry = ModelRegistry.load(default_override=settings.default_model)
    missing = [m.id for m in registry.all() if m.id not in available]
    if registry.default_model not in available:
        checks.append(
            _fail(
                "provider.models", f"default model {registry.default_model} is not available on this account"
            )
        )
    elif missing:
        checks.append(_warn("provider.models", f"not available on this account: {', '.join(missing)}"))
    else:
        checks.append(_ok("provider.models", f"all {len(registry.all())} configured models available"))

    if live:
        provider = build_provider(settings)
        model = registry.get(registry.default_model)
        try:
            result = await provider.complete(
                ChatRequest(
                    model=model.id,
                    messages=[ChatMessage("user", "Reply with the single word: ok")],
                    max_tokens=20,
                    reasoning_effort=model.reasoning_effort if model.reasoning else None,
                )
            )
            checks.append(
                _ok(
                    "provider.live_chat",
                    f"replied ({result.usage.total_tokens if result.usage else '?'} tokens)",
                )
            )
        except ProviderError as exc:
            checks.append(_fail("provider.live_chat", f"{exc.code}: {exc.message}"))
        finally:
            await provider.aclose()
    return checks


# --------------------------------------------------------------------- runner


async def run(live: bool = False, settings: Settings | None = None) -> list[Check]:
    settings = settings or get_settings()
    checks = check_config(settings)
    checks += await check_database(settings)
    checks += await check_provider(settings, live)
    return checks


SYMBOL = {"ok": "✔", "warn": "!", "fail": "✘", "skip": "-"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check configuration, database and AI provider.")
    parser.add_argument("--live", action="store_true", help="send one tiny chat request to the provider")
    parser.add_argument("--json", action="store_true", help="output JSON")
    args = parser.parse_args()

    checks = asyncio.run(run(live=args.live))
    failed = any(c.status == "fail" for c in checks)
    if args.json:
        print(json.dumps({"ok": not failed, "checks": [asdict(c) for c in checks]}, indent=2))
    else:
        out = sys.stdout
        if hasattr(out, "reconfigure"):
            out.reconfigure(encoding="utf-8", errors="replace")
        width = max(len(c.name) for c in checks)
        for c in checks:
            print(f" {SYMBOL[c.status]} {c.name:<{width}}  {c.detail}")
        print("\nAll checks passed." if not failed else "\nSome checks FAILED. See the details above.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
