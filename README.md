# AI Business Assistant

A customer-support chatbot that grows over several versions: chat → document Q&A (RAG) → evaluation → tools → memory → production readiness. See `docs/ROADMAP.md`.

**Status: V1 complete.** All 14 acceptance criteria pass (`docs/v1-acceptance.md`).
- **Chat:** streaming replies, saved conversations, Stop and Retry, per-conversation model settings.
- **Accounts:** login, with each user seeing only their own conversations.
- **Robustness:** bounded retries, context budgeting with optional summarising, and usage/latency accounting.
- **Stack:** a React UI over a FastAPI backend, using Groq's hosted models over plain REST.

## Quick start (Docker, recommended)
You need [Docker Desktop](https://docs.docker.com/get-docker/) and, for real AI replies, a free [GroqCloud API key](https://console.groq.com/keys).

```sh
./scripts/setup.sh          # macOS / Linux / Git Bash
.\scripts\setup.ps1         # Windows PowerShell  (blocked? powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1)
```

The script:
1. Checks Docker.
2. Creates `.env` with a random database password.
3. Asks for your API key. Press Enter for simulated replies instead.
4. Builds and starts the containers.
5. Waits until they are healthy.
6. Runs a self-check of configuration, database, migrations and the AI provider.

Then open **http://localhost:8080** and create an account.

| | |
|---|---|
| Check everything is OK | `./scripts/setup.sh --check` · `.\scripts\setup.ps1 -Check` |
| Self-check with a real AI call | `docker compose exec api python -m app.doctor --live` |
| Logs / status | `docker compose logs -f api` · `docker compose ps` |
| Update after `git pull` | run the setup script again (rebuilds, migrates, re-checks) |

The containers restart automatically whenever Docker runs. Sharing on your network, HTTPS, backups and troubleshooting are covered in **`docs/sharing.md`**.

```
browser ──► web (nginx :8080) ──/api──► api (FastAPI :8000) ──► Groq REST API
             serves the React app        │
                                          └──► db (PostgreSQL 16 + pgvector)
```

## Local development (without the app containers)
Prerequisites: Python 3.12 + [uv](https://docs.astral.sh/uv/) (on the author's machine run as `python -m uv`), Node 22+, Docker.

```sh
cp .env.example .env                       # add GROQ_API_KEY (or set PROVIDER=fake)
docker compose up -d db                    # Postgres on 127.0.0.1:5433 (dev, test and e2e databases)

cd backend
python -m uv sync
python -m uv run alembic upgrade head
python -m uv run uvicorn app.main:app --reload     # API on :8000 (docs at /docs)

cd frontend
npm install
npm run dev                                         # UI on http://localhost:5173 (proxies /api to :8000)
```
Useful tools:
- `python -m uv run python -m app.doctor`: self-check.
- `python -m uv run python scripts/chat_cli.py`: terminal chat (add `--fake` to run offline).
- `scripts/probe_groq.py`: checks which models your Groq account offers and what each supports (`docs/providers.md`).

## Tests
```sh
cd backend
python -m uv run pytest              # 106 unit + integration tests (needs the db container; wipes assistant_test only)
python -m uv run pytest -m live      # opt-in: real Groq calls (uses quota)
python -m uv run ruff check . && python -m uv run ruff format --check .

cd frontend
npm run typecheck && npm run lint && npm run build
npx playwright install chromium      # first time only
npm run test:e2e                     # 10 browser tests; starts its own backend (fake provider) + UI
```
`docs/test-matrix.md` maps every roadmap test scenario to these tests.

The fake provider (`PROVIDER=fake`) echoes your message. Putting a marker in a message simulates provider behaviour:
- failures: `[fake:rate_limit]`, `[fake:unavailable]`, `[fake:timeout]`, `[fake:cut]`, `[fake:fail_once]`
- other behaviour: `[fake:slow]`, `[fake:length]`

See `app/providers/fake.py` for the full list.

## Configuration
All settings live in `.env`, and `.env.example` documents every variable. The most important ones:

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | — | Groq key (never sent to the browser or logged) |
| `PROVIDER` | `groq` | `fake` = simulated replies, no network |
| `DEFAULT_MODEL` | `qwen/qwen3.8-27b` | Must exist in `backend/app/providers/models.toml` |
| `DEFAULT_SYSTEM_PROMPT` | built-in support prompt | Used for new conversations |
| `CONTEXT_BUDGET_TOKENS` | `3000` | Input-token budget per request (Groq free tier: 8000 tokens/min) |
| `CONTEXT_SUMMARIZATION` | `false` | Summarise trimmed history in the background (extra LLM call) |
| `WEB_PORT` | `8080` | Port of the web UI (Docker) |
| `COOKIE_SECURE` | `false` | Set `true` when serving over HTTPS |

## API overview
Interactive docs: http://localhost:8000/docs (local dev). Every error uses `{"error": {"code", "message", "retryable", "request_id"}}`.

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

SSE events: `user_message` → `assistant_started` → `delta`* → `usage` → `done`. On failure the stream ends with `error {code, message, retryable, retry_after, status}`.

## Documentation
- `docs/ROADMAP.md`: the product roadmap (V1–V6)
- `docs/v1-architecture.md`: V1 design
- `docs/decisions.md`: decision log with reasons
- `docs/providers.md`: verified Groq capabilities and limits
- `docs/v1-acceptance.md`: acceptance review and known limitations
- `docs/test-matrix.md`: test coverage map
- `docs/sharing.md`: sharing, operations and troubleshooting
