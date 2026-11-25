"""Probe GroqCloud capabilities via direct REST calls (no SDK).

Records what the account/models ACTUALLY support so that docs/providers.md and
the model registry are based on observation, not assumptions (roadmap §3.1, §44).

Usage (from backend/):
    python -m uv run python scripts/probe_groq.py                 # list models + probe default candidates
    python -m uv run python scripts/probe_groq.py --models a b    # probe specific model IDs
    python -m uv run python scripts/probe_groq.py --context       # also try ~4k / ~8k token prompts
    python -m uv run python scripts/probe_groq.py --list-only     # only list models

Reads GROQ_API_KEY (and optional GROQ_BASE_URL) from the repo-root .env.
Writes raw results to backend/scripts/probe_results/groq-<timestamp>.json.
The API key is never printed or written.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = Path(__file__).resolve().parent / "probe_results"
DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"

# Model IDs whose names indicate they are not general chat models.
NON_CHAT_MARKERS = ("whisper", "tts", "guard", "playai", "orpheus", "distil")

RATE_LIMIT_HEADER_PREFIXES = ("x-ratelimit-", "retry-after")

TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)


def rate_limit_headers(resp: httpx.Response) -> dict[str, str]:
    return {k: v for k, v in resp.headers.items() if k.lower().startswith(RATE_LIMIT_HEADER_PREFIXES)}


def safe_error(resp: httpx.Response) -> dict[str, Any]:
    try:
        body = resp.json()
    except ValueError:
        body = resp.text[:500]
    return {"status": resp.status_code, "body": body, "rate_limit_headers": rate_limit_headers(resp)}


class Probe:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    # ---- models -------------------------------------------------------
    def list_models(self) -> dict[str, Any]:
        resp = self.client.get("/models")
        if resp.status_code != 200:
            return {"ok": False, **safe_error(resp)}
        data = resp.json().get("data", [])
        return {"ok": True, "models": data, "rate_limit_headers": rate_limit_headers(resp)}

    # ---- chat (non-streaming) ---------------------------------------
    def chat(self, model: str) -> dict[str, Any]:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a concise assistant."},
                {"role": "user", "content": "Reply with exactly: pong"},
            ],
            "temperature": 0,
            "max_tokens": 20,
        }
        t0 = time.perf_counter()
        resp = self.client.post("/chat/completions", json=payload)
        latency_ms = round((time.perf_counter() - t0) * 1000)
        if resp.status_code != 200:
            return {"ok": False, "latency_ms": latency_ms, **safe_error(resp)}
        body = resp.json()
        choice = (body.get("choices") or [{}])[0]
        return {
            "ok": True,
            "latency_ms": latency_ms,
            "content": (choice.get("message") or {}).get("content"),
            "finish_reason": choice.get("finish_reason"),
            "usage": body.get("usage"),
            "top_level_keys": sorted(body.keys()),
            "rate_limit_headers": rate_limit_headers(resp),
        }

    # ---- streaming ----------------------------------------------------
    def stream(self, model: str, include_usage_option: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": "Count from 1 to 10, separated by spaces."}],
            "temperature": 0,
            "max_tokens": 60,
            "stream": True,
        }
        if include_usage_option:
            payload["stream_options"] = {"include_usage": True}
        t0 = time.perf_counter()
        ttft_ms = None
        chunks = 0
        text = []
        usage_locations: dict[str, Any] = {}
        finish_reason = None
        saw_done = False
        bad_lines: list[str] = []
        with self.client.stream("POST", "/chat/completions", json=payload) as resp:
            if resp.status_code != 200:
                resp.read()
                return {"ok": False, "stream_options_sent": include_usage_option, **safe_error(resp)}
            content_type = resp.headers.get("content-type")
            for line in resp.iter_lines():
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    bad_lines.append(line[:200])
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    saw_done = True
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    bad_lines.append(data[:200])
                    continue
                chunks += 1
                for choice in obj.get("choices") or []:
                    delta = (choice.get("delta") or {}).get("content")
                    if delta:
                        if ttft_ms is None:
                            ttft_ms = round((time.perf_counter() - t0) * 1000)
                        text.append(delta)
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
                if obj.get("usage"):
                    usage_locations["usage"] = obj["usage"]
                x_groq = obj.get("x_groq") or {}
                if x_groq.get("usage"):
                    usage_locations["x_groq.usage"] = x_groq["usage"]
        return {
            "ok": True,
            "stream_options_sent": include_usage_option,
            "content_type": content_type,
            "ttft_ms": ttft_ms,
            "total_ms": round((time.perf_counter() - t0) * 1000),
            "chunks": chunks,
            "text": "".join(text),
            "finish_reason": finish_reason,
            "saw_done_sentinel": saw_done,
            "usage_found_in": usage_locations,
            "unexpected_lines": bad_lines[:5],
        }

    # ---- tool calling -------------------------------------------------
    def tools(self, model: str) -> dict[str, Any]:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "What are the business hours of the Pune store?"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_business_hours",
                        "description": "Get opening hours for a store location.",
                        "parameters": {
                            "type": "object",
                            "properties": {"location": {"type": "string"}},
                            "required": ["location"],
                        },
                    },
                }
            ],
            "tool_choice": "auto",
            "temperature": 0,
            "max_tokens": 200,
        }
        resp = self.client.post("/chat/completions", json=payload)
        if resp.status_code != 200:
            return {"ok": False, **safe_error(resp)}
        msg = ((resp.json().get("choices") or [{}])[0]).get("message") or {}
        calls = msg.get("tool_calls") or []
        return {
            "ok": True,
            "tool_called": bool(calls),
            "tool_calls": [
                {
                    "name": c.get("function", {}).get("name"),
                    "arguments": c.get("function", {}).get("arguments"),
                }
                for c in calls
            ],
            "content": msg.get("content"),
        }

    # ---- structured output -------------------------------------------
    def json_mode(self, model: str) -> dict[str, Any]:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Respond only with JSON."},
                {"role": "user", "content": 'Return {"product": "widget", "price": 10} as JSON.'},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": 100,
        }
        resp = self.client.post("/chat/completions", json=payload)
        if resp.status_code != 200:
            return {"ok": False, **safe_error(resp)}
        content = (((resp.json().get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
        try:
            json.loads(content)
            valid = True
        except json.JSONDecodeError:
            valid = False
        return {"ok": True, "valid_json": valid, "content": content[:300]}

    def json_schema(self, model: str) -> dict[str, Any]:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Give a product named widget priced 10."}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "product",
                    "schema": {
                        "type": "object",
                        "properties": {"product": {"type": "string"}, "price": {"type": "number"}},
                        "required": ["product", "price"],
                        "additionalProperties": False,
                    },
                },
            },
            "temperature": 0,
            "max_tokens": 100,
        }
        resp = self.client.post("/chat/completions", json=payload)
        if resp.status_code != 200:
            return {"ok": False, **safe_error(resp)}
        content = (((resp.json().get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
        try:
            obj = json.loads(content)
            valid = isinstance(obj, dict) and {"product", "price"} <= obj.keys()
        except json.JSONDecodeError:
            valid = False
        return {"ok": True, "schema_valid": valid, "content": content[:300]}

    # ---- context size -------------------------------------------------
    def context(self, model: str, approx_tokens: int) -> dict[str, Any]:
        # ~4 chars per token of filler; ask a question answerable only from the start.
        filler = "The quick brown fox jumps over the lazy dog. " * (approx_tokens // 10 + 1)
        prompt = (
            "Remember the code word: AMBER-42.\n" + filler + "\nWhat was the code word? Reply with it only."
        )
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 20,
        }
        t0 = time.perf_counter()
        resp = self.client.post("/chat/completions", json=payload)
        latency_ms = round((time.perf_counter() - t0) * 1000)
        if resp.status_code != 200:
            return {"ok": False, "approx_tokens": approx_tokens, "chars": len(prompt), **safe_error(resp)}
        body = resp.json()
        content = (((body.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
        usage = body.get("usage") or {}
        return {
            "ok": True,
            "approx_tokens": approx_tokens,
            "chars": len(prompt),
            "prompt_tokens": usage.get("prompt_tokens"),
            "chars_per_token": round(len(prompt) / usage["prompt_tokens"], 2)
            if usage.get("prompt_tokens")
            else None,
            "recalled": "AMBER-42" in content,
            "latency_ms": latency_ms,
        }


def probe_invalid_key(base_url: str) -> dict[str, Any]:
    with httpx.Client(
        base_url=base_url, timeout=TIMEOUT, headers={"Authorization": "Bearer invalid-key-for-probe"}
    ) as c:
        resp = c.get("/models")
        return safe_error(resp)


def probe_bad_request(client: httpx.Client) -> dict[str, Any]:
    resp = client.post("/chat/completions", json={"model": "definitely-not-a-real-model", "messages": []})
    return safe_error(resp)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--models", nargs="*", help="Model IDs to probe (default: all chat-like models listed)"
    )
    parser.add_argument("--context", action="store_true", help="Also probe ~4k and ~8k token prompts")
    parser.add_argument("--list-only", action="store_true")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    base_url = os.getenv("GROQ_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    if not api_key:
        print(f"GROQ_API_KEY is not set. Add it to {ROOT / '.env'} (see .env.example).", file=sys.stderr)
        return 2

    results: dict[str, Any] = {
        "probed_at": datetime.now(UTC).isoformat(),
        "base_url": base_url,
        "models": {},
    }
    with httpx.Client(
        base_url=base_url, timeout=TIMEOUT, headers={"Authorization": f"Bearer {api_key}"}
    ) as client:
        p = Probe(client)
        listing = p.list_models()
        results["model_list"] = listing
        if not listing.get("ok"):
            print("Listing models failed:", json.dumps(listing, indent=2))
            return 1

        print(f"{'model id':45} {'owner':15} {'context':>8} active")
        for m in sorted(listing["models"], key=lambda m: m.get("id", "")):
            print(
                f"{m.get('id', ''):45} {str(m.get('owned_by', '')):15} "
                f"{str(m.get('context_window', '')):>8} {m.get('active', '')}"
            )
        if args.list_only:
            _save(results)
            return 0

        if args.models:
            targets = args.models
        else:
            targets = sorted(
                m["id"]
                for m in listing["models"]
                if m.get("active", True) and not any(k in m["id"].lower() for k in NON_CHAT_MARKERS)
            )
        print(f"\nProbing {len(targets)} model(s): {', '.join(targets)}\n")

        for model in targets:
            print(f"== {model}")
            r: dict[str, Any] = {}
            for name, fn in [
                ("chat", lambda model=model: p.chat(model)),
                ("stream_plain", lambda model=model: p.stream(model, include_usage_option=False)),
                ("stream_with_usage_option", lambda model=model: p.stream(model, include_usage_option=True)),
                ("tools", lambda model=model: p.tools(model)),
                ("json_mode", lambda model=model: p.json_mode(model)),
                ("json_schema", lambda model=model: p.json_schema(model)),
            ] + (
                [
                    ("context_4k", lambda model=model: p.context(model, 4000)),
                    ("context_8k", lambda model=model: p.context(model, 8000)),
                ]
                if args.context
                else []
            ):
                try:
                    r[name] = fn()
                except httpx.HTTPError as exc:
                    r[name] = {"ok": False, "exception": type(exc).__name__, "detail": str(exc)[:300]}
                print(f"   {name:26} {_summary(name, r[name])}")
                time.sleep(1.0)  # be gentle with free-tier rate limits
            results["models"][model] = r

        results["error_cases"] = {
            "invalid_key": probe_invalid_key(base_url),
            "bad_request_unknown_model": probe_bad_request(client),
        }
        print("\nError cases:")
        for k, v in results["error_cases"].items():
            print(f"   {k:26} HTTP {v['status']}: {json.dumps(v['body'])[:160]}")

    _save(results)
    return 0


def _summary(name: str, r: dict[str, Any]) -> str:
    if not r.get("ok"):
        return (
            f"FAIL {r.get('status', r.get('exception'))}: {json.dumps(r.get('body', r.get('detail')))[:120]}"
        )
    if name == "chat":
        return f"ok {r['latency_ms']}ms content={r['content']!r} usage={r['usage']}"
    if name.startswith("stream"):
        return (
            f"ok ttft={r['ttft_ms']}ms total={r['total_ms']}ms chunks={r['chunks']} "
            f"done={r['saw_done_sentinel']} usage_in={list(r['usage_found_in'])}"
        )
    if name == "tools":
        return f"ok tool_called={r['tool_called']} {r['tool_calls']}"
    if name == "json_mode":
        return f"ok valid_json={r['valid_json']}"
    if name == "json_schema":
        return f"ok schema_valid={r['schema_valid']}"
    if name.startswith("context"):
        return (
            f"ok prompt_tokens={r['prompt_tokens']} chars/token={r['chars_per_token']} "
            f"recalled={r['recalled']} {r['latency_ms']}ms"
        )
    return "ok"


def _save(results: dict[str, Any]) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"groq-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nRaw results saved to {out}")


if __name__ == "__main__":
    sys.exit(main())
