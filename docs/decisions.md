# Decision log

| # | Date | Decision | Reason | Revisit when |
|---|---|---|---|---|
| 1 | 2026-11-25 | Email + password auth (argon2), server-side sessions in an httpOnly cookie | Real multi-user isolation without a third-party dependency | SSO or an external IdP is required |
| 2 | 2026-11-25 | ~~Hosted Supabase Postgres for dev~~ **Superseded by #10** | — | — |
| 3 | 2026-11-25 | Local Docker `pgvector/pgvector:pg16` for automated tests (`assistant_test` DB) | Fast, isolated, disposable | — |
| 4 | 2026-11-25 | Python 3.12 managed by uv | 3.10 is EOL; uv gives reproducible locked environments | — |
| 5 | 2026-11-25 | Frontend: React + Vite + TS + Tailwind + shadcn/ui + assistant-ui (ExternalStoreRuntime) | Mature AI-chat UI primitives while our backend stays the source of truth. Meta Astryx was considered but is still beta. | Astryx stabilises, or assistant-ui gets in the way |
| 6 | 2026-11-25 | SQLAlchemy 2.0 async + asyncpg + Alembic as the only DB access style | One consistent approach (roadmap §7) | — |
| 7 | 2026-11-25 | SSE (fetch POST + stream) for chat streaming | One-directional token stream; simpler than WebSockets | Bidirectional realtime is needed |
| 8 | 2026-11-25 | In-process token-bucket rate limiting, no Redis | Single-process local app (roadmap §41.7) | More than one backend worker or instance |
| 9 | 2026-11-25 | Context: trim-to-budget first; summarisation later behind a flag | Simple and understandable first (roadmap §6.3) | Trimming measurably loses needed context |
| 10 | 2026-11-25 | **One local Docker Postgres (pgvector/pg16) for dev and tests**: DBs `assistant` and `assistant_test`, port 5433 bound to localhost only, `docker compose up -d` | No manual Supabase setup, no free-tier pausing, fully scriptable. Measured at ~32 MB RAM idle. | A hosted deployment is needed (V6) |
| 11 | 2026-11-25 | Default model `qwen/qwen3.8-27b`; `openai/gpt-oss-20b`/`-120b` selectable | Probe: fastest TTFT, every capability passed, no reasoning-token overhead (docs/providers.md) | Probe results change |
| 12 | 2026-11-25 | Context budget 3000 tokens and max_tokens 800 by default; Groq 413 is treated as non-retryable | Free tier allows 8000 TPM (7000 ITPM for qwen). An oversized single request returns 413 with `retry-after`, but retrying can never succeed. | Paid tier |
