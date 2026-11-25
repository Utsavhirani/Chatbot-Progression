# AI Business Assistant

A business customer-support assistant that grows over several versions: chat → RAG → evaluation → tools → memory → production readiness.
See `docs/ROADMAP.md`. The current milestone is **V1**; its plan is in `docs/v1-architecture.md`, and design decisions are in `docs/decisions.md`.

> Status: **V1, Step 3 done.** The backend is complete for V1: authentication, conversations, and streaming chat with retry, cancellation, context budgeting and usage accounting. Next is Step 4: the React frontend.

## Prerequisites
- Python 3.12 via [uv](https://docs.astral.sh/uv/). On this machine uv is run as `python -m uv`.
- Node 22+ (frontend, later step)
- Docker Desktop (runs the local Postgres)
- A GroqCloud API key

## Setup
```sh
cp .env.example .env          # then fill in GROQ_API_KEY
docker compose up -d          # Postgres on localhost:5433 (dev + test DBs)
cd backend
python -m uv sync
python -m uv run alembic upgrade head   # create/upgrade the dev schema
```

## Probe the LLM provider
This checks the models your Groq account can use and what each one supports (chat, streaming, usage, tools, JSON, context):
```sh
cd backend
python -m uv run python scripts/probe_groq.py --list-only      # list models
python -m uv run python scripts/probe_groq.py --context        # full probe
python -m uv run python scripts/probe_groq.py --models <id> <id>
```
Raw results are written to `backend/scripts/probe_results/`. The summary goes in `docs/providers.md`.

## Run the backend
```sh
cd backend
python -m uv run uvicorn app.main:app --reload     # http://localhost:8000/health/ready, /api/models, /docs
python -m uv run python scripts/chat_cli.py        # streaming terminal chat via Groq (add --fake for offline)
```

## Tests
```sh
cd backend
python -m uv run pytest              # unit + integration tests (needs the DB container; wipes assistant_test only)
python -m uv run pytest -m live      # opt-in: real Groq calls (uses free-tier quota)
python -m uv run ruff check . && python -m uv run ruff format --check .
```

The fake provider (`PROVIDER=fake`) echoes messages. A marker such as `[fake:rate_limit]`, `[fake:cut]` or `[fake:timeout]` in a message makes it simulate that failure (see `app/providers/fake.py`).

## API overview
Interactive docs: http://localhost:8000/docs. Every error uses `{"error": {"code", "message", "retryable", "request_id"}}`.

| Method | Path | Notes |
|---|---|---|
| POST | `/api/auth/register` · `/api/auth/login` · `/api/auth/logout` | Session cookie (httpOnly) |
| GET | `/api/auth/me` | |
| GET/POST | `/api/conversations` | List own / create (`title`, `system_prompt`, `settings`) |
| GET/PATCH/DELETE | `/api/conversations/{id}` | |
| GET | `/api/conversations/{id}/messages` | Ordered history |
| POST | `/api/conversations/{id}/messages` | **SSE.** Body `{client_message_id, content}` |
| POST | `/api/conversations/{id}/messages/{assistant_id}/retry` | **SSE.** Regenerates the latest failed, partial or cancelled reply |
| GET | `/api/models` · `/health/live` · `/health/ready` | |

SSE events: `user_message` → `assistant_started` → `delta`* → `usage` → `done`. On failure the stream ends with an `error` event `{code, message, retryable, retry_after, status}`.
Errors found before streaming starts (validation, 404, `duplicate`, `conflict_in_progress`, `message_too_long`, `rate_limited`, `provider_not_configured`) are plain JSON responses.

Try it with curl:
```sh
curl -c jar -H 'content-type: application/json' -d '{"email":"me@example.com","password":"a-long-password"}' localhost:8000/api/auth/register
curl -b jar -H 'content-type: application/json' -d '{}' localhost:8000/api/conversations          # copy the id
curl -N -b jar -H 'content-type: application/json'   -d '{"client_message_id":"'$(python -c "import uuid;print(uuid.uuid4())")'","content":"Hello!"}'   localhost:8000/api/conversations/<id>/messages
```
