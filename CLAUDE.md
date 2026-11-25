# AI Business Assistant

One evolving AI business-assistant app (customer-support chatbot first). Full roadmap: `docs/ROADMAP.md`.
Current milestone: **V1 complete** (`docs/v1-acceptance.md`); next is V2 (RAG) — see `docs/v1-architecture.md` (approved plan) and `docs/decisions.md`.

## Stack
- Backend: Python 3.12 (uv) · FastAPI · Pydantic v2 · SQLAlchemy 2.0 async + asyncpg · Alembic · HTTPX · structlog
- DB: local Docker `pgvector/pgvector:pg16` (`docker compose up -d`, port 5433): `assistant` for dev and `assistant_test` for tests
- Frontend: React + Vite + TypeScript + Tailwind + shadcn/ui + assistant-ui (ExternalStoreRuntime)
- Tests: pytest + respx (provider mocks) · Playwright (e2e with `PROVIDER=fake`)

## Commands
- Full stack: `./scripts/setup.sh` (or `.\scripts\setup.ps1`); UI on :8080. Self-check: `docker compose exec api python -m app.doctor`.
- DB only (local dev/tests): `docker compose up -d db`. Shell into it with `docker exec -it ai-assistant-db-1 psql -U assistant -d assistant`.
- uv is invoked as `python -m uv` on this machine (not on PATH).
- Backend (from `backend/`): `python -m uv run pytest` · `python -m uv run uvicorn app.main:app --reload`
- Live provider tests are opt-in: `python -m uv run pytest -m live` (needs `GROQ_API_KEY`).

## Rules (from roadmap §3 and §43)
- Call LLM providers with direct REST via HTTPX. No provider SDKs, and keep provider details inside `app/providers/`.
- Never assume model IDs, quotas, or capabilities. They must come from the probe (`backend/scripts/probe_groq.py`) and be recorded in `docs/providers.md`.
- Groq free tier allows 8000 TPM. A 413 means the request is too large and is never retried. Ignore `reasoning` deltas (see `docs/providers.md`).
- Retries are bounded, honour `Retry-After`, and never retry after the first streamed token or after side effects.
- The backend authorizes every conversation operation. Other users' resources return 404, and user IDs are never taken from request bodies.
- No secrets in code, logs, or commits. Update `.env.example` whenever config changes.
- Don't add new infrastructure (Redis, LangChain, a vector DB, etc.) without a demonstrated need. Record such decisions in `docs/decisions.md`.
- Work in small, reviewable increments. Keep the app runnable, run the tests, and report real results only. Unverified work is stated as unverified.
- Report substantial work as: Goal / Current state / Plan / Decisions / Implementation / Verification / Limitations / Next step.
