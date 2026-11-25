# V1 acceptance review

Each criterion from roadmap §8, checked on 2026-11-25 against commit-ready code. Every claim below is backed by a test that passed or a check that was actually run; nothing is assumed.

| # | Criterion (§8) | Status | Evidence |
|---|---|---|---|
| 1 | A user can open the application and start a conversation | ✅ Pass | E2E `register, chat with a streamed reply…`. Manual run through the Docker stack on http://localhost:8080 with real Groq. |
| 2 | The assistant responds through a hosted model API | ✅ Pass | Groq REST adapter over HTTPX (no SDK). Live tests `test_live_stream` and `test_live_complete`. `doctor --live` returned `provider.live_chat ok`. Browser chats recorded real usage rows. |
| 3 | Streaming works (or the limitation is documented with a fallback) | ✅ Pass | SSE end to end; through nginx, 101 deltas arrived spread over 218 ms (not buffered). The non-streaming `complete()` path also exists and is tested. |
| 4 | Conversations persist after refresh or restart | ✅ Pass | E2E reload test; `test_history_persists_across_restart`, `test_data_persists_across_app_restart`. Container recreated, data kept (named volume). |
| 5 | Multiple conversations remain separate | ✅ Pass | `test_conversations_stay_separate` (no cross-conversation context); E2E `conversations stay separate…`. |
| 6 | Access to conversations is authorized | ✅ Pass | Session-cookie auth; ownership filter in every query; other users get 404 on every endpoint (`test_other_users_conversations_are_invisible`, E2E isolation test); CSRF origin check (`test_cross_origin_state_change_is_rejected`). |
| 7 | Context is constructed within a deliberate budget | ✅ Pass | `CONTEXT_BUDGET_TOKENS` (3000) and a per-request TPM guard; newest-first trimming (`test_history_near_budget_is_trimmed`). Estimate calibrated against real usage (docs/decisions.md #18). Optional summarisation is tested, and was checked with real Groq. |
| 8 | Invalid input and provider failures produce understandable errors | ✅ Pass | One error envelope; friendly SSE error events with `retryable` / `retry_after`; inline UI errors with Retry (E2E). Six provider failure types are parametrised in integration tests. |
| 9 | Timeouts and transient failures handled without infinite retries | ✅ Pass | At most 3 attempts with full-jitter backoff; Retry-After capped; overall 120 s deadline; never retried after output (`test_5xx_is_retried_with_bounded_attempts`, `test_overall_deadline_stops_retries`). |
| 10 | Usage and latency are recorded when provider data is available | ✅ Pass | `llm_calls` holds input/output/total tokens, estimate, TTFT, latency, attempts, status and request_id, including failed, cancelled and summary calls. Verified with real Groq rows. |
| 11 | Secrets remain server-side and are not committed | ✅ Pass | `.env` is git-ignored (checked with `git check-ignore`); probe output is ignored; API key never sent to the browser or logged (log redaction test); the doctor prints only the key length. Images exclude `.env` (`.dockerignore`). |
| 12 | The app can be started using documented instructions | ✅ Pass | README Quick start: `scripts/setup.sh` / `setup.ps1`. Verified from a **fresh clone with no `.env`**: it built, started, migrated, passed the self-check and completed a chat. |
| 13 | Automated tests cover the important API and conversation workflows | ✅ Pass | 101 backend + 10 E2E + 3 live tests; all 16 §9 scenarios mapped in `docs/test-matrix.md`. |
| 14 | The app can be demonstrated from its frontend (not only Swagger) | ✅ Pass | React UI with streaming, Stop, Retry, settings and mobile layout; E2E screenshots and real-Groq browser runs. |

**Result: all 14 V1 acceptance criteria pass.**

## Known limitations (accepted for V1)
- **Single-process rate limiting:** in-memory token buckets. Running several API workers would need a shared store (V6).
- **Free-tier throughput:** Groq allows about 8000 tokens/min for the whole account, so a few active users will hit `rate_limited`. The app reports it clearly but cannot raise the limit.
- **Closing the tab ends a reply:** closing or reloading the tab mid-reply ends the request; the reply is saved as `cancelled` and can be retried. (Switching conversations inside the app does not cancel.)
- **Retry scope:** only the latest reply can be retried; there is no branching or editing of earlier messages.
- **Summarisation cost:** off by default. When enabled it adds a background LLM call. In a deliberately tight real test it used about 0.8× the chat tokens; with defaults (budget 3000, at least 4 dropped messages) it runs far less often.
- **Accounts:** no password reset, email verification or admin roles. Anyone who can reach the app can register (see docs/sharing.md).
- **Plain HTTP:** the Docker stack serves plain HTTP. Use HTTPS (reverse proxy or tunnel) plus `COOKIE_SECURE=true` before exposing it beyond a trusted network.
- **Bundle size:** the frontend JS bundle is about 900 KB (275 KB gzipped); it has not been split yet.
