"""Token estimation.

Approximate by design: Groq measured ~4.4 English chars/token (docs/providers.md); we use 4 to
err on the safe (over-estimating) side, plus a per-message overhead for role/formatting tokens.
Real counts from provider usage are stored next to the estimate in llm_calls for calibration.
Calibration 2026-11-25 (qwen3.8-27b): overhead 4 under-estimated short chats (39 vs 47 real,
171 vs 175); 7 per message keeps the estimate at or slightly above the real count.
"""

from __future__ import annotations

import math

CHARS_PER_TOKEN = 4.0
PER_MESSAGE_OVERHEAD = 7


def estimate_text_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def estimate_message_tokens(text: str) -> int:
    return estimate_text_tokens(text) + PER_MESSAGE_OVERHEAD
