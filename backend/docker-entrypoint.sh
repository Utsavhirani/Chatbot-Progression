#!/bin/sh
# Waits for the database, applies migrations, then starts the API (or any given command).
set -e

echo "[entrypoint] waiting for database..."
python - <<'PY'
import asyncio, sys
from app.core.config import get_settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def wait() -> None:
    engine = create_async_engine(get_settings().database_url, connect_args={"timeout": 3})
    for attempt in range(1, 31):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            await engine.dispose()
            print(f"[entrypoint] database ready (attempt {attempt})")
            return
        except Exception as exc:
            print(f"[entrypoint] database not ready ({type(exc).__name__}), retrying...")
            await asyncio.sleep(2)
    sys.exit("[entrypoint] database unreachable after 60s")

asyncio.run(wait())
PY

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "[entrypoint] applying migrations..."
  alembic upgrade head
fi

exec "$@"
