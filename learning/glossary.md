# Glossary

| Term | Meaning | Chapter |
|---|---|---|
| **Adapter** | Code that translates between our neutral types and one specific external API (e.g. `GroqProvider`) | 05 |
| **Alembic** | Tool that versions database schema changes as migration scripts | 07 |
| **argon2id** | A deliberately slow, memory-hard password hashing algorithm | 08 |
| **ASGI** | The interface between Python async web servers (uvicorn) and frameworks (FastAPI/Starlette) | 06 |
| **assistant-ui** | React library of chat UI primitives; we use its ExternalStoreRuntime | 11 |
| **async / await** | Python and JS syntax that lets a program wait for I/O without blocking other work | 06 |
| **Async generator** | A function that `yield`s values over time and can `await` in between, e.g. `generate()` | 09 |
| **Backoff (exponential)** | Waiting longer after each failed attempt: 0.5 s, 1 s, 2 s… | 05 |
| **Budget (context)** | The maximum input tokens we allow per request (3000) | 10 |
| **Cancel scope / shield** | anyio feature that protects cleanup code from cancellation | 09 |
| **citext** | Postgres case-insensitive text type (used for email) | 07 |
| **Container / image / volume** | Running instance / read-only template / persistent storage, in Docker | 13 |
| **Context window** | Maximum tokens a model can consider in one request | 03 |
| **Cookie flags** | `HttpOnly`, `Secure`, `SameSite`, `Max-Age`: rules for how the browser handles a cookie | 08 |
| **CORS** | Browser rules for cross-origin requests. Avoided entirely by using one origin. | 08 |
| **CSRF** | Cross-site request forgery: another site making your browser act on your behalf | 08 |
| **Delta** | One small piece of streamed reply text | 04 |
| **Dependency injection** | Endpoints declare what they need, and the framework provides it | 06 |
| **Doctor** | Our self-check command (`python -m app.doctor`) | 13 |
| **E2E test** | End-to-end test driving a real browser | 12 |
| **Envelope (error)** | Our uniform error JSON: `{error: {code, message, retryable, request_id}}` | 06 |
| **ExternalStoreRuntime** | assistant-ui mode where *our* code owns the message state | 11 |
| **Fake provider** | Offline stand-in for the AI, controllable with `[fake:…]` markers | 05 |
| **finish_reason** | Why generation stopped: `stop` (natural end) or `length` (hit max_tokens) | 03, 09 |
| **Fixture (pytest)** | A reusable setup function that tests request by name | 12 |
| **Full jitter** | Randomising each retry wait between 0 and the backoff ceiling | 05 |
| **Health check (live/ready)** | "Is the process up?" vs "can it do useful work?" | 06, 13 |
| **HTTPX** | Python HTTP client we use for raw REST calls | 03 |
| **Idempotency key** | Client-generated id making a repeated submission harmless (`client_message_id`) | 09 |
| **IntegrityError** | Database error when a constraint (unique, check, FK) is violated | 09 |
| **JSONB** | Postgres binary JSON column type | 07 |
| **Lifespan** | FastAPI startup/shutdown hook | 06 |
| **Lockfile** | File pinning exact dependency versions (`uv.lock`, `package-lock.json`) | 02 |
| **max_tokens** | Maximum length of the model's reply | 03 |
| **Mermaid** | Text format for diagrams used throughout this guide | README |
| **Middleware** | Code wrapping every request/response | 06 |
| **Migration** | A versioned script that changes the database schema | 07 |
| **Multi-stage build** | Dockerfile with a heavy build stage and a small final stage | 13 |
| **nginx** | Web server and reverse proxy serving the UI and forwarding `/api` | 13 |
| **Optimistic UI** | Showing the user's action immediately, before the server confirms it | 11 |
| **Origin** | Scheme + host + port of a web page, e.g. `http://localhost:8080` | 08 |
| **Partial unique index** | A unique index that only applies to rows matching a condition | 07 |
| **pgvector** | Postgres extension for vector similarity search (needed in V2) | 07 |
| **Probe** | Script that measures a provider's real behaviour before we rely on it | 03 |
| **Prompt injection** | User or document text trying to override the system prompt | 08 |
| **Protocol (Python)** | A structural interface: any object with the right methods fits | 05 |
| **Pydantic** | Library validating data against typed models | 06 |
| **Query key (TanStack)** | The cache identifier for a piece of server data, e.g. `['messages', id]` | 11 |
| **Rate limit / TPM** | Usage caps; TPM = tokens per minute (8000 on the Groq free tier) | 03, 08 |
| **Reasoning tokens** | Hidden "thinking" tokens of reasoning models; they count against max_tokens | 03 |
| **Registry (models)** | Allowlist of usable models with verified capabilities (`models.toml`) | 03 |
| **respx** | Library that mocks HTTPX requests in tests | 12 |
| **Retry-After** | Response header telling the client how long to wait | 05 |
| **Row lock (`FOR UPDATE`)** | Locks a row until the transaction ends, making concurrent work run in order | 07, 09 |
| **SameSite** | Cookie flag controlling whether it's sent on cross-site requests | 08 |
| **SecretStr** | Pydantic type that hides its value when printed | 02 |
| **Server state vs local state** | Cached data owned by the backend vs on-screen UI data | 11 |
| **Session (auth)** | Server-side record linking a cookie token to a user | 08 |
| **Session (DB)** | A SQLAlchemy unit of work holding a connection and pending changes | 07 |
| **Soft delete** | Marking a row deleted (`deleted_at`) instead of removing it | 07 |
| **SPA** | Single-page application: one page, redrawn by JavaScript | 11 |
| **SQLSTATE** | Standard database error code, e.g. `28P01` = invalid password | 13 |
| **SSE** | Server-Sent Events: a text format for streaming events over HTTP | 04 |
| **Status (message)** | `streaming`, `complete`, `partial`, `failed` or `cancelled` | 07, 09 |
| **StrictMode** | React dev mode that mounts components twice to expose effect bugs | 11, 15 |
| **System prompt** | Hidden instructions defining the assistant's behaviour | 03 |
| **Temperature** | Randomness of generation (0 = focused) | 03 |
| **Token** | Unit of text a model reads and writes (~4 characters in English) | 03 |
| **Token bucket** | Rate-limit algorithm: a refilling bucket of allowed requests | 08 |
| **Transaction** | A group of DB changes that all succeed or all fail | 07 |
| **TTFT** | Time to first token: how quickly a reply starts appearing | 07, 09 |
| **Turn** | One user message plus its reply; also our hand-off object between phases | 09 |
| **uv** | Fast Python package, environment and version manager | 02 |
| **uvicorn** | The ASGI server that runs FastAPI | 06 |
| **Vite** | Frontend dev server and bundler | 02, 11 |
