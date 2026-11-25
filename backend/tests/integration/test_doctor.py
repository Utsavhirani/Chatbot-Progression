"""The self-check (`python -m app.doctor`) reports real problems precisely."""

from __future__ import annotations

from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.doctor import check_config, run
from tests.integration.conftest import TEST_DB_URL


def _by_name(checks):
    return {c.name: c for c in checks}


async def test_healthy_setup_passes(migrated_db: str) -> None:
    checks = _by_name(await run(settings=Settings(_env_file=None, provider="fake", database_url=migrated_db)))
    assert checks["db.connection"].status == "ok"
    assert checks["db.extensions"].status == "ok"
    assert checks["db.migrations"].status == "ok"
    assert not any(c.status == "fail" for c in checks.values())


def test_missing_groq_key_fails_and_fake_provider_warns() -> None:
    missing = _by_name(check_config(Settings(_env_file=None, provider="groq", groq_api_key=None)))
    assert missing["config.groq_api_key"].status == "fail"
    fake = _by_name(check_config(Settings(_env_file=None, provider="fake")))
    assert fake["config.provider"].status == "warn"


def test_unknown_default_model_fails() -> None:
    checks = _by_name(check_config(Settings(_env_file=None, provider="fake", default_model="nope")))
    assert checks["config.default_model"].status == "fail"


async def test_wrong_password_is_explained(migrated_db: str) -> None:
    bad = make_url(TEST_DB_URL).set(password="definitely-wrong").render_as_string(hide_password=False)
    checks = _by_name(await run(settings=Settings(_env_file=None, provider="fake", database_url=bad)))
    assert checks["db.connection"].status == "fail"
    assert (
        "password" in checks["db.connection"].detail
        and "definitely-wrong" not in checks["db.connection"].detail
    )


async def test_unreachable_database_fails_fast(migrated_db: str) -> None:
    dead = "postgresql+asyncpg://assistant:x@127.0.0.1:1/assistant"
    checks = _by_name(
        await run(
            settings=Settings(_env_file=None, provider="fake", database_url=dead, db_connect_timeout_s=1)
        )
    )
    assert checks["db.connection"].status == "fail" and "running" in checks["db.connection"].detail
