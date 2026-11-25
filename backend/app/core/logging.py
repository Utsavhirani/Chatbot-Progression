"""Structured JSON logging via structlog.

Request-scoped identifiers (request_id, later user_id / conversation_id) are bound with
structlog.contextvars and appear on every log line. Sensitive keys are redacted.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

# Exact keys whose values must never reach logs.
SENSITIVE_KEYS = frozenset(
    {"api_key", "groq_api_key", "authorization", "password", "cookie", "set-cookie", "session_token", "token"}
)


def _redact(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key in list(event_dict):
        if key.lower() in SENSITIVE_KEYS:
            event_dict[key] = "[REDACTED]"
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    log_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact,
    ]
    structlog.configure(
        processors=[*shared, structlog.processors.format_exc_info, structlog.processors.JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        # Resolve sys.stdout lazily so redirected/replaced streams (tests, reloaders) keep working.
        logger_factory=lambda *_: structlog.PrintLogger(sys.stdout),
        cache_logger_on_first_use=False,
    )
    # Quieten noisy libraries; uvicorn access logs are replaced by our request log.
    logging.basicConfig(level=log_level, stream=sys.stdout, format="%(message)s")
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
