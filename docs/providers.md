# Provider capability matrix

Everything here was **observed** by `backend/scripts/probe_groq.py` and a follow-up streaming test, on 2026-11-25, on this account's free (`on_demand`) tier.
Limits and models change, so re-run the probe before relying on these numbers.
Raw JSON goes in `backend/scripts/probe_results/`, which is git-ignored because it contains the org ID.

## GroqCloud — chat models

| Model | Chat | Stream | Tools | JSON object | JSON schema | 4k prompt | Notes |
|---|---|---|---|---|---|---|---|
| `qwen/qwen3.8-27b` | ✅ | ✅ TTFT ~0.3–0.6 s | ✅ | ✅ | ✅ | ✅ (recalled fact) | **Default.** No reasoning tokens, concise replies. ITPM limit 7000. |
| `openai/gpt-oss-20b` | ✅ | ✅ TTFT ~0.6–0.8 s | ✅ | ✅ | ✅ | ✅ (sent) | Reasoning model. Streams separate `reasoning` deltas. Use `reasoning_effort: low`. |
| `openai/gpt-oss-120b` | ✅ | ✅ TTFT ~0.9–3 s | ✅ | ✅ | ✅ | ✅ (sent) | Reasoning model, slower and verbose (hit 400 max tokens on a simple support question). |
| `allam-2-7b` | ✅ | ✅ | ❌ 400 | ✅ | ❌ 400 | ❌ (4k context) | Not suitable. 4096 context window. |

Not chat models (excluded): `whisper-large-v3*` (speech-to-text), `canopylabs/orpheus-*` (TTS), `meta-llama/llama-prompt-guard-2-*` (classifier, which could be useful later for prompt-injection checks), `openai/gpt-oss-safeguard-20b` (safety classifier).

The listed context window is 131072 for the qwen and gpt-oss models. **The real limit is the per-minute token budget (below), not the context window.**

## Rate limits observed (response headers)

| Model | Requests (limit header) | Tokens/min | Other |
|---|---|---|---|
| qwen / gpt-oss | 1000 | **8000 TPM** | qwen also enforces **7000 input TPM (ITPM)** |
| allam-2-7b | 7000 | 6000 TPM | — |

Headers: `x-ratelimit-limit-{requests,tokens}`, `x-ratelimit-remaining-{requests,tokens}`, `x-ratelimit-reset-{requests,tokens}` (durations like `1m26.4s` or `787ms`), and `retry-after` (seconds) on errors.

## Protocol details the adapter must handle

- **Endpoint:** `POST https://api.groq.com/openai/v1/chat/completions` with Bearer auth.
- **Streaming:** SSE `data: {json}` lines, ending with `data: [DONE]`.
  - Usage arrives in the final chunk as both `usage` and `x_groq.usage`, **with or without** `stream_options.include_usage`.
  - The adapter reads `usage` first and falls back to `x_groq.usage`.
- **Usage fields:** `prompt_tokens`, `completion_tokens`, `total_tokens`, timing fields (`queue_time`, `total_time`, …), and `completion_tokens_details.reasoning_tokens` for reasoning models.
- **Reasoning models (gpt-oss):**
  - Deltas contain `reasoning` and `channel` keys besides `content`. The adapter must **ignore `reasoning`**; it is never shown or stored as the answer.
  - Reasoning tokens count against `max_tokens`. With `max_tokens=20` the visible content was empty.
  - Send `reasoning_effort: "low"` only to models flagged as reasoning.
- **Errors observed:**

| Situation | HTTP | Body `error.type` / `code` | Our mapping |
|---|---|---|---|
| Invalid key | 401 | `invalid_request_error` / `invalid_api_key` | `ProviderAuthError` (no retry) |
| Malformed request | 400 | `invalid_request_error` | `ProviderBadRequest` (no retry) |
| Feature unsupported (tools / json_schema) | 400 | `invalid_request_error` | `ProviderBadRequest` (capability matrix should prevent it) |
| Prompt longer than the context window | 400 | `invalid_request_error`, "reduce the length" | `ProviderBadRequest` → `context_too_large` |
| **Single request bigger than the TPM limit** | **413** | `tokens` / `rate_limit_exceeded` | **`ProviderRequestTooLarge` (no retry, even though `retry-after` is sent)** |
| TPM/RPM exhausted (expected) | 429 | `rate_limit_exceeded` | `ProviderRateLimited` (retry, honouring `retry-after`) |

## Consequences for V1 design

- `CONTEXT_BUDGET_TOKENS` defaults to **3000**, and `max_tokens` defaults to **800**. That keeps one request at roughly ≤ 4k tokens, so a user can send about 2 messages per minute within 8000 TPM. This is a free-tier constraint; it is shown in the UI as a clear `rate_limited` error with retry time.
- An app-side pre-check rejects a request whose estimated size exceeds the model's per-minute limit, before calling Groq.
- Tokenisation: about **4.4 characters per token** for English prose. The estimator uses `chars / 4` (slightly conservative) plus a per-message overhead, and is calibrated against the `usage` returned.
- The remaining-tokens headers are logged on every call, as the basis for V6 quota tracking.
