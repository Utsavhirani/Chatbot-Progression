"""Interactive terminal chat through the provider layer (Step 1 demo; no persistence yet).

Usage (from backend/):
    python -m uv run python scripts/chat_cli.py                   # default model from models.toml
    python -m uv run python scripts/chat_cli.py --model openai/gpt-oss-20b
    python -m uv run python scripts/chat_cli.py --fake            # offline fake provider

Type a message and press Enter; empty line or Ctrl+C to quit.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.providers.base import (  # noqa: E402
    ChatMessage,
    ChatRequest,
    Finish,
    ProviderError,
    TextDelta,
    UsageEvent,
)
from app.providers.registry import ModelRegistry, build_provider  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model")
    parser.add_argument("--fake", action="store_true")
    args = parser.parse_args()

    settings = Settings(provider="fake") if args.fake else Settings()
    configure_logging("WARNING")
    registry = ModelRegistry.load(default_override=settings.default_model)
    model = registry.get(args.model or registry.default_model)
    provider = build_provider(settings)
    if provider is None:
        print("Provider not configured: set GROQ_API_KEY in .env (or use --fake).", file=sys.stderr)
        return 2

    history = [ChatMessage("system", "You are a friendly, concise customer-support assistant.")]
    print(f"Chatting with {model.id} via {provider.name}. Empty line to quit.\n")
    try:
        while True:
            try:
                text = (await asyncio.to_thread(input, "you> ")).strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not text:
                break
            history.append(ChatMessage("user", text))
            request = ChatRequest(
                model=model.id,
                messages=history,
                max_tokens=model.default_max_tokens,
                temperature=0.3,
                reasoning_effort=model.reasoning_effort if model.reasoning else None,
            )
            reply: list[str] = []
            start = time.perf_counter()
            ttft = None
            usage = "usage n/a"
            print("bot> ", end="", flush=True)
            try:
                async for event in provider.stream(request):
                    if isinstance(event, TextDelta):
                        ttft = ttft or time.perf_counter() - start
                        reply.append(event.text)
                        print(event.text, end="", flush=True)
                    elif isinstance(event, UsageEvent):
                        u = event.usage
                        usage = f"in={u.input_tokens} out={u.output_tokens}"
                    elif isinstance(event, Finish):
                        remaining = event.rate_limit.get("x-ratelimit-remaining-tokens", "?")
                        total = time.perf_counter() - start
                        print(
                            f"\n     [{usage}, ttft={ttft or 0:.2f}s, total={total:.2f}s, "
                            f"attempts={event.attempts}, TPM remaining={remaining}]\n"
                        )
                history.append(ChatMessage("assistant", "".join(reply)))
            except ProviderError as err:
                print(f"\n     [error {err.code}: {err.message} retry_after={err.retry_after}]\n")
                history.pop()  # drop the unanswered user turn
    finally:
        await provider.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
