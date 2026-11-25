# V1 test matrix

Maps each scenario from roadmap §9 to the automated tests that cover it.

- **Paths:** `backend/tests/...` are pytest tests, `frontend/e2e/chat.spec.ts` holds the Playwright tests, and `live` marks opt-in real-Groq tests.
- **Totals (2026-11-25):** 101 backend tests (unit + integration on real Postgres), 3 live tests and 10 e2e browser tests, all passing.

| # | Scenario (§9) | Unit (mocked HTTP) | Integration (API + DB) | E2E (browser) / other |
|---|---|---|---|---|
| 1 | Normal question and answer | `test_stream_yields_text_usage_and_finish`, `test_complete_returns_text_and_usage` | `test_send_streams_reply_and_persists_everything`, `test_follow_up_includes_history_and_system_prompt` | `register, chat with a streamed reply…`; live: `test_live_stream`, `test_live_complete` |
| 2 | Empty or whitespace-only message | — | `test_empty_message_is_rejected_without_side_effects` (2 cases) | `validation and rejected sends…` (composer ignores empty input) |
| 3 | Very long user message | `test_message_that_cannot_fit_is_rejected_not_truncated` | `test_too_long_message_is_rejected` | `validation and rejected sends…` |
| 4 | Invalid API key | `test_invalid_key_is_not_retried` | `test_provider_failure_becomes_error_event_and_failed_row[auth]` | live: `test_live_invalid_key_is_auth_error`; `python -m app.doctor` (`provider.api_key`) |
| 5 | Provider timeout | `test_timeout_is_retried_then_raises_provider_timeout`, `test_overall_deadline_stops_retries` | `…failed_row[timeout]` | — |
| 6 | Provider 429 / rate limit | `test_429_with_short_retry_after_is_retried_then_succeeds`, `test_429_with_long_retry_after_fails_fast`, `test_413_request_too_large_is_not_retried_despite_retry_after` | `…failed_row[rate_limit]` (retry_after surfaced), `…failed_row[too_large]` | — |
| 7 | Provider 5xx / overload | `test_5xx_is_retried_with_bounded_attempts`, `test_connection_error_then_success` | `…failed_row[unavailable]`, `test_retry_regenerates_failed_reply_in_place` | `a failed reply shows an error and Retry regenerates it` |
| 8 | Malformed provider response | `test_malformed_stream_chunk_raises_bad_response`, `test_complete_with_unexpected_shape_raises_bad_response`, `test_sse_*` | `…failed_row[malformed]` | — |
| 9 | Streaming interruption | `test_stream_cut_after_content_is_interrupted_and_not_retried`, `test_malformed_chunk_after_content_is_interrupted` | `test_stream_interruption_keeps_partial_text`, `test_closing_the_stream_early_saves_partial_reply_as_cancelled`, `test_task_cancellation_still_persists_outcome` | `Stop cancels a streaming reply…`; manual: curl killed mid-stream against real Groq (saved as `cancelled`) |
| 10 | Duplicate message submission | — | `test_duplicate_submission_is_not_processed_twice`, `test_concurrent_sends_produce_exactly_one_generation`, `test_second_message_while_generating_is_rejected`, `test_db_enforces_one_streaming_reply_per_conversation` | composer blocks sends while generating |
| 11 | Refresh during or after a conversation | — | `test_history_persists_across_restart`, `test_data_persists_across_app_restart`, `test_startup_releases_abandoned_streams`, `test_stale_streaming_reply_is_released` | `…history persists after reload`, `navigating away mid-reply does not lose it…`, `Stop…` (reload after cancel) |
| 12 | New conversation isolation | — | `test_conversations_stay_separate` | `conversations stay separate and can be renamed and deleted` |
| 13 | Access to another user's conversation | — | `test_other_users_conversations_are_invisible`, `test_cannot_send_into_another_users_conversation`, `test_retry_rules` (other user gets 404) | `users cannot see each other's conversations` |
| 14 | History near the context limit | `test_oldest_history_is_trimmed_first…`, `test_budget_respects_configured_cap…`, `test_summary_is_included…` | `test_history_near_budget_is_trimmed`, `test_dropped_history_is_summarised_in_background_and_reused` | manual: real Groq summarisation check (facts recalled after trimming) |
| 15 | Missing provider configuration | `test_ready_reports_missing_provider_config`, `test_build_provider_variants` | `test_provider_not_configured_returns_503` | `python -m app.doctor` (`config.groq_api_key`) |
| 16 | Database unavailable | — | `test_db_down_reports_unready_and_api_returns_db_unavailable` | `python -m app.doctor` (`db.connection`); container entrypoint waits for the DB |

## Running them
```sh
docker compose up -d db                            # tests need the database container
cd backend  && python -m uv run pytest              # unit + integration
python -m uv run pytest -m live                    # opt-in, uses Groq quota
cd frontend && npm run test:e2e                     # starts its own backend + UI
```
