# AI Business Assistant

A business customer-support assistant that grows over several versions: chat → RAG → evaluation → tools → memory → production readiness.
See `docs/ROADMAP.md`. The current milestone is **V1**; its plan is in `docs/v1-architecture.md`, and design decisions are in `docs/decisions.md`.

> Status: **V1, Step 1 done** (provider core). The API has health and models endpoints, and a terminal chat demo is available. Next is Step 2: persistence and authentication.

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
python -m uv run pytest              # unit tests (mocked provider, no network)
python -m uv run pytest -m live      # opt-in: real Groq calls (uses free-tier quota)
python -m uv run ruff check . && python -m uv run ruff format --check .
```

The fake provider (`PROVIDER=fake`) echoes messages. A marker such as `[fake:rate_limit]`, `[fake:cut]` or `[fake:timeout]` in a message makes it simulate that failure (see `app/providers/fake.py`).
