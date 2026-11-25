# V1 Architecture & Implementation Plan

## Context
`C:\Users\User\Desktop\AI Projects\Chatbot` contains only `ai_business_assistant_project_roadmap.md`. It has no code and no git repo yet. The user wants V1 ("Complete Conversational AI Application", roadmap §5–§9, §44) fully designed before any code is written.

The machine has Python 3.10.11 (EOL), Node 22.14, Docker 29.9, Git 2.39, 7.3 GB RAM and Windows 11.

**Decisions confirmed with the user**
| Area | Choice |
|---|---|
| Auth | Email + password, argon2 hashes, server-side sessions in an httpOnly cookie |
| Database | **One local Docker** `pgvector/pgvector:pg16` container (`docker-compose.yml`): `assistant` for dev and `assistant_test` for pytest. *(This replaced an earlier Supabase choice; see decisions #10.)* |
| Python | **3.12 managed by uv** (venv + lockfile) |
| Frontend | React + Vite + **TypeScript + Tailwind + shadcn/ui + assistant-ui** (ExternalStoreRuntime, so our backend stays the source of truth) |

**Other decisions (defaults, following the roadmap)**
- FastAPI and Pydantic v2.
- SQLAlchemy 2.0 async with asyncpg and Alembic, as the only DB access style.
- HTTPX for direct Groq REST calls, with no SDK.
- SSE for streaming.
- structlog for JSON logs.
- pytest, respx and Playwright for tests.

---

## 1. Repository layout
```
Chatbot/
  CLAUDE.md                 # §3 constraints + §43 working rules (auto-loaded by Claude Code)
  README.md                 # setup/run/test instructions
  .gitignore  .env.example
  docker-compose.yml        # local Postgres (dev + test DBs)
  infra/postgres/init/      # first-start SQL: test DB, citext
  docs/
    ROADMAP.md              # moved + formatting fixed (pandoc-merged lists restored)
    decisions.md            # decision log (table above + later ones)
    providers.md            # Groq capability matrix, filled from REAL probe output
  backend/
    pyproject.toml  uv.lock  alembic.ini
    migrations/             # Alembic
    scripts/probe_groq.py   # live capability probe
    app/
      main.py               # app factory, lifespan, middleware, routers
      core/   config.py (pydantic-settings) · logging.py · errors.py · security.py · ratelimit.py · middleware.py (request-id)
      db/     session.py (async engine/sessionmaker) · models.py
      schemas/ auth.py · conversations.py · chat.py · common.py
      api/    deps.py (db, current_user) · auth.py · conversations.py · chat.py · models.py · health.py
      providers/ base.py · groq.py · fake.py · registry.py · retry.py · sse.py · models.toml
      conversations/ service.py (ownership-scoped CRUD) · context.py (budget builder) · tokens.py
      chat/   service.py (orchestration: idempotency → persist → context → stream → persist → usage)
    tests/  unit/ · integration/ · conftest.py
  frontend/
    package.json  vite.config.ts (proxy /api → :8000)  tailwind / shadcn config
    src/
      api/      client.ts (fetch wrapper, typed) · sse.ts (POST-SSE parser)
      features/auth/          LoginPage, RegisterPage, useSession
      features/chat/          ChatPage, useChatRuntime (assistant-ui ExternalStoreRuntime), ModelSettings
      features/conversations/ thread list adapter, queries (TanStack Query)
      components/ui/          shadcn + assistant-ui generated components
    e2e/  playwright specs
```
Modules are only created when the step that needs them is reached. No empty folders.

## 2. Data model (Postgres, Alembic migration `0001`)
- **users**: `id uuid pk`, `email citext unique`, `password_hash`, `created_at`
- **auth_sessions**: `id uuid`, `token_hash bytea unique` (sha256 of the random cookie token; the raw token is never stored), `user_id fk`, `created_at`, `expires_at`, `last_seen_at`
- **conversations**: `id uuid`, `user_id fk (indexed)`, `title`, `system_prompt null`, `settings jsonb` (provider, model, temperature, max_tokens, stream), `summary text null`, `summary_through_seq int null`, `created_at`, `updated_at`, `deleted_at null` (soft delete)
- **messages**: `id uuid`, `conversation_id fk`, `seq int` (unique per conversation, which gives deterministic ordering), `role` (`user|assistant`), `content text`, `status` (`complete|streaming|partial|failed|cancelled`), `client_message_id uuid null` (unique per conversation, used for idempotency), `reply_to_id null`, `error_code null`, `token_estimate int`, `created_at`
- **llm_calls** (usage accounting): `id`, `user_id`, `conversation_id`, `message_id`, `provider`, `model`, `input_tokens`, `output_tokens`, `total_tokens`, `usage_source` (`provider|estimated`), `ttft_ms`, `latency_ms`, `attempts`, `status`, `error_code`, `request_id`, `created_at`

Database: local Docker Postgres on `localhost:5433`, started with `docker compose up -d`. If the container is down, the readiness check reports `db_unavailable`.

## 3. Backend API
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/register` · `/login` · `/logout` | Sets or clears the `session` cookie (httpOnly, SameSite=Lax, Secure outside dev) |
| GET | `/api/auth/me` | Current user |
| GET/POST | `/api/conversations` | List own conversations (by updated_at desc) / create |
| GET/PATCH/DELETE | `/api/conversations/{id}` | Read, rename, change settings, soft-delete |
| GET | `/api/conversations/{id}/messages` | Ordered by seq |
| POST | `/api/conversations/{id}/messages` | **SSE**. Body `{client_message_id, content}` |
| POST | `/api/conversations/{id}/messages/{assistant_id}/retry` | **SSE**. Regenerates a `failed/partial/cancelled` reply in place (no duplicate) |
| GET | `/api/models` | Allowed models and their verified capabilities |
| GET | `/health/live` · `/health/ready` | Ready checks the DB and that provider config is present |

**SSE event contract:** `user_message` (persisted id/seq) → `assistant_started` (id) → `delta` × N → `usage` → `done`. On failure, `error {code, message, retryable}` is sent instead.

**Error envelope (all JSON errors):** `{error: {code, message, retryable, request_id}}`.
- Codes: `validation_error`, `unauthenticated`, `not_found`, `conflict_in_progress`, `duplicate`, `rate_limited`, `message_too_long`, `provider_auth`, `provider_rate_limited`, `provider_unavailable`, `provider_timeout`, `provider_bad_response`, `db_unavailable`.
- Another user's conversation returns **404**, so the response does not reveal that it exists.

## 4. Provider layer (`app/providers/`)
- **base.py**: internal types `ChatMessage`, `ChatRequest(model, messages, temperature, max_tokens, stream)`, `StreamEvent(delta|usage|finish)`, `Usage`, `ModelCapabilities`. Also `ProviderAdapter` protocol: `stream(req) -> AsyncIterator[StreamEvent]` and `complete(req) -> ChatResult`.
- **Error hierarchy** `ProviderError(retryable: bool)`:
  - `ProviderAuthError` (401/403, not retried)
  - `ProviderBadRequest` (400/404/422, not retried)
  - `ProviderRateLimited` (429, carries `retry_after`)
  - `ProviderUnavailable` (5xx/503/overload)
  - `ProviderTimeout`
  - `ProviderMalformedResponse`
- **Probe findings (docs/providers.md):**
  - Groq returns **413** for a single request that exceeds the TPM limit. This maps to `ProviderRequestTooLarge`, which is **not retried**.
  - The adapter ignores `reasoning` deltas from gpt-oss models.
  - It sends `reasoning_effort` only to models flagged as reasoning.
  - Usage is read from `usage`, falling back to `x_groq.usage`.
- **groq.py**: `POST {GROQ_BASE_URL}/openai/v1/chat/completions` through one shared `httpx.AsyncClient`.
  - Timeouts: connect 5s, read 30s between chunks, total deadline 120s.
  - It maps internal ↔ Groq JSON and parses the SSE `data:` lines and `[DONE]`.
  - It extracts usage from the final chunk (the exact field is confirmed by the probe).
- **retry.py**: at most 3 attempts, exponential backoff with full jitter (base 0.5s, cap 8s).
  - `Retry-After` is honoured up to the cap.
  - Retries happen **only before the first token is emitted**. After that, a failure marks the message `partial`, with no silent replay.
- **fake.py**: `FakeProvider` with deterministic scripted replies and injectable failures (429, 5xx, timeout, mid-stream cut, malformed). It is selected with `PROVIDER=fake` for tests and e2e.
- **registry.py + models.toml**: the allowlist of models and their capabilities (chat, streaming, tools, JSON mode, vision, context window, max output, rate-limit notes).
  - Values come from the probe, not from assumptions.
  - Request settings are validated against it (e.g. `max_tokens ≤ max_output`).

## 5. Chat orchestration (`chat/service.py`)
1. Authorize: the conversation must belong to `current_user` and not be deleted.
2. Validate content: strip whitespace, reject empty, and enforce `MAX_MESSAGE_CHARS` (default 16k), which returns `message_too_long`.
3. **Idempotency:**
   - If `client_message_id` already exists, return `duplicate` with the existing ids. The frontend then reloads instead of resending.
   - **One active generation per conversation:** if a `streaming` assistant row exists, return `conflict_in_progress`.
   - Both checks are enforced by the unique constraint and a `SELECT … FOR UPDATE` on the conversation row.
4. Persist the user message, then the assistant placeholder (`status=streaming`), and commit.
5. Build the context (§6), then stream from the provider. Deltas are forwarded to SSE and accumulated in memory.
6. On finish: save the content with `status=complete` and write the `llm_calls` row (usage, TTFT, latency, attempts).
7. On provider error: set `failed` + `error_code`, send the SSE `error` event, and write `llm_calls` with the error status.
8. On client disconnect (`request.is_disconnected()` / CancelledError): cancel the upstream request and save the partial text as `cancelled` (or `partial` if the upstream broke).
9. Stale-stream sweeper (at startup and on read): `streaming` rows older than 5 min become `failed`.
10. Auto-title: the first user message is truncated to 60 chars. No extra LLM call is made.

## 6. Context budgeting (`conversations/context.py`, `tokens.py`)
- `budget = min(CONTEXT_BUDGET_TOKENS, model.context_window − max_tokens − safety_margin)`.
  - `CONTEXT_BUDGET_TOKENS` defaults to **3000**, and `max_tokens` defaults to 800. The probe measured 8000 TPM and 7000 ITPM on the free tier.
- Order: system prompt, then the optional summary of older messages, then the most recent messages (added newest-first until the budget is reached, then re-ordered chronologically), then the new user message.
- Only `complete` messages, plus partial assistant text marked as truncated, are included.
- Token estimate: `ceil(chars / 4) + 4` per message. The probe measured about 4.4 chars per token.
  - Provider `usage.prompt_tokens` is logged next to the estimate so the ratio can be calibrated.
  - The estimate is labelled approximate in the docs.
- If the newest user message alone exceeds the budget, the request is rejected with `message_too_long`.
- **Summarization** comes in a later step (V1.5) and is behind a flag. When the dropped history exceeds N tokens, one non-streamed call summarises it and the result is stored in `conversations.summary` / `summary_through_seq`. The first version uses trimming only.

## 7. Security & operations
- **Passwords:** argon2-cffi.
- **Sessions:** 32-byte random token in the cookie, sha256 stored in the DB, 14-day expiry with sliding renewal. Logout deletes the row.
- **CSRF:** SameSite=Lax, plus an `Origin` header check on every non-GET request. In dev, Vite proxies `/api`, so everything is same-origin and no CORS is needed.
- **Ownership:** every service query filters by `user_id`. There is no user_id in any request body.
- **Rate limits:** an in-process token bucket per user for chat (e.g. 20/min) and per IP+email for login (e.g. 5/min).
  - This only works for a single process, which is documented as a known limitation.
  - It returns `rate_limited` with `Retry-After`.
- **Logging:** structlog JSON with `request_id` (middleware, echoed as `X-Request-ID`), `user_id` and `conversation_id`.
  - Message content is not logged unless `LOG_CONTENT=true`.
  - Headers are redacted, and API keys are never logged.
- **Secrets:** `.env` is git-ignored, and `.env.example` lists every variable with placeholder values:
  - `DATABASE_URL`, `TEST_DATABASE_URL`, `PROVIDER`, `GROQ_API_KEY`, `GROQ_BASE_URL`
  - `DEFAULT_MODEL`, `CONTEXT_BUDGET_TOKENS`, `MAX_MESSAGE_CHARS`
  - `SESSION_TTL_DAYS`, `LOG_LEVEL`, `LOG_CONTENT`, `ALLOWED_ORIGINS`

## 8. Frontend
- **Routes:** `/login`, `/register`, `/` (redirects to the latest or a new conversation), `/c/:conversationId`.
- **State:** TanStack Query holds server state (conversations, messages, me). assistant-ui's `useExternalStoreRuntime` is fed from our messages array.
  - `onNew`: generates a `client_message_id` (crypto.randomUUID), POSTs to the SSE endpoint, and appends deltas optimistically.
  - `onCancel`: AbortController.
  - `onReload`: the retry endpoint.
- **Thread list:** assistant-ui ThreadList bound to `/api/conversations` (new, switch, rename, delete).
- **SSE client:** `fetch` POST + ReadableStream parser (EventSource cannot POST). It handles `error` events and network drops.
- **States:** "generating…" indicator, stop button, and an error bubble with **Retry** shown only when `retryable` and the message is `failed/partial/cancelled`. Send is disabled while a generation is active, which also prevents duplicates on the client side.
- **Model settings panel** per conversation: model (from `/api/models`), temperature, max tokens, system prompt.
- Responsive layout: the sidebar collapses to a drawer on mobile.

## 9. Testing
- **Unit (no DB):**
  - token estimator and context builder (budget edges)
  - retry policy (respx: 429 with Retry-After, 503 then success, 401 not retried, timeout)
  - Groq SSE parser (normal, malformed JSON, truncated stream, missing usage)
  - error normalization
- **Integration** (httpx `ASGITransport` against the Docker test DB, with `PROVIDER=fake`):
  - auth flow
  - ownership (user B gets 404 on user A's conversation and messages)
  - idempotent duplicate submit and concurrent submit (409)
  - persistence and ordering
  - full SSE flow
  - interrupted stream, which leaves a `partial` row
  - retry replaces the failed reply
  - long-message rejection
  - near-budget history trimming
  - missing provider config, where ready fails and chat returns a clear error
  - DB down, which returns `db_unavailable` / 503
- **E2E (Playwright, FakeProvider):**
  - register/login → chat → streamed reply → refresh persists
  - new conversation is isolated
  - injected failure → Retry works
  - second user cannot see the first user's threads
- **Live** (`pytest -m live`, needs `GROQ_API_KEY`, opt-in): one real chat and one real stream.
- A `docs/test-matrix.md` table maps each of the 16 roadmap §9 scenarios to a test.

## 10. Increments, each ending runnable and verified
| Step | Deliverable | Exit check |
|---|---|---|
| **0. Setup** ✅ | git init, .gitignore, CLAUDE.md, docs/ (roadmap moved and fixed), Python 3.12 via uv, docker-compose Postgres, `.env` | Python 3.12.16 ✅; DB healthy with both DBs ✅ |
| **0b. Groq probe** ✅ | `scripts/probe_groq.py`: list models; chat, stream, usage fields, tool call, JSON mode, ~4k/8k-token contexts, 429 headers | `docs/providers.md` + `models.toml` filled from real output; default model chosen |
| **1. Provider core** ✅ | FastAPI skeleton, config, logging, health, provider base/groq/fake/retry | unit tests green; live test passes |
| **2. Persistence + auth** | models, Alembic 0001 on local Postgres, auth endpoints, conversations CRUD with ownership | integration tests green |
| **3. Chat orchestration** | SSE chat endpoint, idempotency, cancel, retry, usage rows, context trimming, rate limits | integration tests green; curl demo streams |
| **4. Frontend** | Vite + TS + Tailwind + shadcn + assistant-ui, auth pages, thread list, streaming chat, settings panel | manual demo; Playwright green |
| **5. Hardening** | optional summarization, stale-stream sweeper, README, test matrix, acceptance review against §8 (14 criteria) | every §8 criterion checked and reported (pass / limitation) |

Each step is reported in the roadmap format (Goal / Current state / Plan / Decisions / Implementation / Verification / Limitations / Next step).

## 11. Inputs needed from the user during execution
- A Groq API key, placed in `.env` by the user (never pasted into code). This is needed for Step 0b.
- Docker Desktop running (for the database).

## Verification (end of V1)
- `uv run pytest` (unit + integration) and `npx playwright test` both pass.
- `uv run pytest -m live` passes with a real key.
- Manual run: `uv run uvicorn app.main:app` + `npm run dev`. Register two users, chat with streaming, refresh, check isolation, kill the network mid-stream, then Retry.
- `llm_calls` rows show tokens and latency, and the logs contain no secrets.
