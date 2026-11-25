"""Chat endpoint end-to-end with the fake provider and a real database.

Covers roadmap §9: normal Q&A, empty / long messages, provider failures (429, 5xx, auth, timeout,
malformed, stream interruption), duplicate submission, concurrency, retry, refresh/persistence,
isolation, context-limit trimming, missing provider configuration, usage accounting, cancellation.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update

from app.chat.service import ChatService
from app.db.models import LlmCall, Message
from app.providers.base import ProviderUnavailable
from app.providers.fake import FakeProvider

# ------------------------------------------------------------------ helpers


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    return events


async def new_conversation(client: httpx.AsyncClient, **body: object) -> str:
    resp = await client.post("/api/conversations", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def send(
    client: httpx.AsyncClient, cid: str, content: str, client_message_id: str | None = None
) -> httpx.Response:
    return await client.post(
        f"/api/conversations/{cid}/messages",
        json={"client_message_id": client_message_id or str(uuid.uuid4()), "content": content},
    )


async def messages(client: httpx.AsyncClient, cid: str) -> list[dict]:
    return (await client.get(f"/api/conversations/{cid}/messages")).json()


async def llm_calls(app: FastAPI) -> list[LlmCall]:
    async with app.state.db.sessionmaker() as db:
        return list(await db.scalars(select(LlmCall).order_by(LlmCall.created_at)))


def text_of(events: list[tuple[str, dict]]) -> str:
    return "".join(d["text"] for e, d in events if e == "delta")


# ------------------------------------------------------------------ happy path


async def test_send_streams_reply_and_persists_everything(alice: httpx.AsyncClient, app: FastAPI) -> None:
    cid = await new_conversation(alice)
    resp = await send(alice, cid, "Where is my order #42?")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(resp.text)
    names = [e for e, _ in events]
    assert names[:2] == ["user_message", "assistant_started"]
    assert names[-2:] == ["usage", "done"] and "delta" in names
    assert text_of(events) == "(fake reply) You said: Where is my order #42?"

    stored = await messages(alice, cid)
    assert [(m["seq"], m["role"], m["status"]) for m in stored] == [
        (1, "user", "complete"),
        (2, "assistant", "complete"),
    ]
    assert stored[1]["content"] == text_of(events) and stored[1]["reply_to_id"] == stored[0]["id"]

    conv = (await alice.get(f"/api/conversations/{cid}")).json()
    assert conv["title"] == "Where is my order #42?"  # auto-titled from the first message

    [call] = await llm_calls(app)
    usage = dict(events)["usage"]
    assert call.status == "complete" and call.provider == "fake" and call.model == "qwen/qwen3.8-27b"
    assert call.input_tokens == usage["input_tokens"] and call.output_tokens > 0
    assert call.estimated_input_tokens > 0 and call.latency_ms is not None and call.ttft_ms is not None
    assert call.request_id == resp.headers["x-request-id"]


async def test_follow_up_includes_history_and_system_prompt(alice: httpx.AsyncClient, app: FastAPI) -> None:
    cid = await new_conversation(alice, system_prompt="You are Acme support.")
    await send(alice, cid, "first question")
    await send(alice, cid, "second question")
    sent = app.state.provider.requests[-1]
    assert [(m.role, m.content.split(":")[0]) for m in sent.messages] == [
        ("system", "You are Acme support."),
        ("user", "first question"),
        ("assistant", "(fake reply) You said"),
        ("user", "second question"),
    ]
    assert sent.temperature == 0.3 and sent.max_tokens == 800


async def test_conversation_settings_are_used(alice: httpx.AsyncClient, app: FastAPI) -> None:
    cid = await new_conversation(
        alice, settings={"model": "openai/gpt-oss-20b", "temperature": 0.9, "max_tokens": 500}
    )
    await send(alice, cid, "hi")
    req = app.state.provider.requests[-1]
    assert (req.model, req.temperature, req.max_tokens, req.reasoning_effort) == (
        "openai/gpt-oss-20b",
        0.9,
        500,
        "low",
    )


# ------------------------------------------------------------------ input validation


@pytest.mark.parametrize("content", ["", "   \n\t  "])
async def test_empty_message_is_rejected_without_side_effects(
    alice: httpx.AsyncClient, app: FastAPI, content: str
) -> None:
    cid = await new_conversation(alice)
    resp = await send(alice, cid, content)
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "empty_message"
    assert await messages(alice, cid) == [] and app.state.provider.requests == []


async def test_too_long_message_is_rejected(alice: httpx.AsyncClient, app: FastAPI) -> None:
    cid = await new_conversation(alice)
    resp = await send(alice, cid, "x" * 8001)
    assert resp.status_code == 413 and resp.json()["error"]["code"] == "message_too_long"
    assert await messages(alice, cid) == []


async def test_missing_client_message_id_is_validation_error(alice: httpx.AsyncClient) -> None:
    cid = await new_conversation(alice)
    resp = await alice.post(f"/api/conversations/{cid}/messages", json={"content": "hi"})
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "validation_error"


# ------------------------------------------------------------------ provider failures


@pytest.mark.parametrize(
    ("marker", "code", "retryable"),
    [
        ("rate_limit", "provider_rate_limited", True),
        ("unavailable", "provider_unavailable", True),
        ("timeout", "provider_timeout", True),
        ("malformed", "provider_bad_response", True),
        ("auth", "provider_auth", False),
        ("too_large", "request_too_large", False),
    ],
)
async def test_provider_failure_becomes_error_event_and_failed_row(
    alice: httpx.AsyncClient, app: FastAPI, marker: str, code: str, retryable: bool
) -> None:
    cid = await new_conversation(alice)
    events = parse_sse((await send(alice, cid, f"hello [fake:{marker}]")).text)
    name, data = events[-1]
    assert name == "error" and data["code"] == code and data["retryable"] is retryable
    assert data["status"] == "failed" and "Fake" not in data["message"]  # no provider internals leak
    if marker == "rate_limit":
        assert data["retry_after"] == 7

    stored = await messages(alice, cid)
    assert stored[1]["status"] == "failed" and stored[1]["error_code"] == code and stored[1]["content"] == ""
    [call] = await llm_calls(app)
    assert call.status == "failed" and call.error_code == code and call.usage_source == "none"


async def test_stream_interruption_keeps_partial_text(alice: httpx.AsyncClient) -> None:
    cid = await new_conversation(alice)
    events = parse_sse((await send(alice, cid, "one two three four five six [fake:cut]")).text)
    partial = text_of(events)
    assert partial and events[-1][0] == "error"
    assert events[-1][1]["status"] == "partial" and events[-1][1]["retryable"] is True
    stored = (await messages(alice, cid))[1]
    assert stored["status"] == "partial" and stored["content"] == partial


async def test_provider_not_configured_returns_503(make_app: Callable[..., Awaitable[FastAPI]]) -> None:
    app = await make_app(provider_obj=None, provider="groq", groq_api_key=None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/auth/register", json={"email": "p@example.com", "password": "password-123"})
        cid = await new_conversation(c)
        resp = await send(c, cid, "hello")
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "provider_not_configured"


# ------------------------------------------------------------------ idempotency & concurrency


async def test_duplicate_submission_is_not_processed_twice(alice: httpx.AsyncClient, app: FastAPI) -> None:
    cid = await new_conversation(alice)
    client_id = str(uuid.uuid4())
    first = await send(alice, cid, "pay my invoice", client_id)
    assert first.status_code == 200
    again = await send(alice, cid, "pay my invoice", client_id)

    assert again.status_code == 409
    err = again.json()["error"]
    stored = await messages(alice, cid)
    assert err["code"] == "duplicate"
    assert err["details"] == {
        "user_message_id": stored[0]["id"],
        "assistant_message_id": stored[1]["id"],
        "assistant_status": "complete",
    }
    assert len(stored) == 2 and len(app.state.provider.requests) == 1


async def test_second_message_while_generating_is_rejected(alice: httpx.AsyncClient, app: FastAPI) -> None:
    cid = await new_conversation(alice)
    async with app.state.db.sessionmaker() as db:
        db.add(Message(conversation_id=uuid.UUID(cid), seq=1, role="assistant", status="streaming"))
        await db.commit()
    resp = await send(alice, cid, "are you there?")
    assert resp.status_code == 409
    assert (
        resp.json()["error"]["code"] == "conflict_in_progress" and resp.json()["error"]["retryable"] is True
    )


async def test_stale_streaming_reply_is_released(alice: httpx.AsyncClient, app: FastAPI) -> None:
    cid = uuid.UUID(await new_conversation(alice))
    async with app.state.db.sessionmaker() as db:
        db.add(Message(conversation_id=cid, seq=1, role="assistant", status="streaming"))
        await db.commit()
        await db.execute(update(Message).values(updated_at=datetime.now(UTC) - timedelta(minutes=10)))
        await db.commit()
    resp = await send(alice, str(cid), "hello again")
    assert resp.status_code == 200
    stored = await messages(alice, str(cid))
    assert stored[0]["status"] == "failed" and stored[0]["error_code"] == "abandoned"
    assert stored[-1]["status"] == "complete"


async def test_concurrent_sends_produce_exactly_one_generation(
    alice: httpx.AsyncClient, app: FastAPI
) -> None:
    app.state.provider.chunk_delay_s = 0.01
    cid = await new_conversation(alice)
    results = await asyncio.gather(*(send(alice, cid, f"msg {i}") for i in range(4)))
    codes = sorted(r.status_code for r in results)
    assert codes.count(200) >= 1 and set(codes) <= {200, 409}
    stored = await messages(alice, cid)
    seqs = [m["seq"] for m in stored]
    assert seqs == list(range(1, len(seqs) + 1))  # no gaps or duplicates
    assert all(m["status"] == "complete" for m in stored)
    assert len(stored) == 2 * codes.count(200)


# ------------------------------------------------------------------ retry


async def test_retry_regenerates_failed_reply_in_place(alice: httpx.AsyncClient, app: FastAPI) -> None:
    cid = await new_conversation(alice)
    app.state.provider.fail_next.append(ProviderUnavailable("down", status_code=503))
    failed = parse_sse((await send(alice, cid, "what are your hours?")).text)
    assistant_id = failed[-1][1]["id"]

    retry = await alice.post(f"/api/conversations/{cid}/messages/{assistant_id}/retry")
    events = parse_sse(retry.text)
    assert [e for e, _ in events][0] == "assistant_started"  # no new user_message on retry
    assert events[-1] == ("done", {"id": assistant_id, "status": "complete", "finish_reason": "stop"})

    stored = await messages(alice, cid)
    assert len(stored) == 2 and stored[1]["id"] == assistant_id
    assert stored[1]["status"] == "complete" and stored[1]["error_code"] is None
    assert stored[1]["content"] == "(fake reply) You said: what are your hours?"
    assert [c.status for c in await llm_calls(app)] == ["failed", "complete"]


async def test_retry_rules(alice: httpx.AsyncClient, bob: httpx.AsyncClient, app: FastAPI) -> None:
    cid = await new_conversation(alice)
    app.state.provider.fail_next.append(ProviderUnavailable("down"))
    old_failed = parse_sse((await send(alice, cid, "first")).text)[-1][1]["id"]
    ok = dict(parse_sse((await send(alice, cid, "second")).text))["done"]["id"]

    completed = await alice.post(f"/api/conversations/{cid}/messages/{ok}/retry")
    assert completed.status_code == 409 and completed.json()["error"]["code"] == "not_retryable"
    not_latest = await alice.post(f"/api/conversations/{cid}/messages/{old_failed}/retry")
    assert not_latest.status_code == 409 and not_latest.json()["error"]["code"] == "retry_not_latest"
    other_user = await bob.post(f"/api/conversations/{cid}/messages/{old_failed}/retry")
    assert other_user.status_code == 404
    unknown = await alice.post(f"/api/conversations/{cid}/messages/{uuid.uuid4()}/retry")
    assert unknown.status_code == 404


# ------------------------------------------------------------------ isolation, persistence, limits


async def test_cannot_send_into_another_users_conversation(
    alice: httpx.AsyncClient, bob: httpx.AsyncClient, app: FastAPI
) -> None:
    cid = await new_conversation(alice)
    resp = await send(bob, cid, "let me in")
    assert resp.status_code == 404 and app.state.provider.requests == []


async def test_conversations_stay_separate(alice: httpx.AsyncClient, app: FastAPI) -> None:
    a = await new_conversation(alice)
    b = await new_conversation(alice)
    await send(alice, a, "secret topic A")
    await send(alice, b, "topic B")
    assert all("secret topic A" not in m.content for m in app.state.provider.requests[-1].messages)
    assert len(await messages(alice, a)) == len(await messages(alice, b)) == 2


async def test_history_near_budget_is_trimmed(make_app: Callable[..., Awaitable[FastAPI]]) -> None:
    app = await make_app(context_budget_tokens=300)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/auth/register", json={"email": "t@example.com", "password": "password-123"})
        cid = await new_conversation(c)
        for i in range(6):
            await send(c, cid, f"message {i} " + "padding " * 20)
        sent = app.state.provider.requests[-1]
    assert sent.messages[-1].content.startswith("message 5")
    assert all(not m.content.startswith("message 0") for m in sent.messages)  # oldest trimmed
    assert sum(len(m.content) // 4 + 7 for m in sent.messages) <= 300


async def test_chat_is_rate_limited_per_user(make_app: Callable[..., Awaitable[FastAPI]]) -> None:
    app = await make_app(chat_rate_per_minute=2)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/auth/register", json={"email": "r@example.com", "password": "password-123"})
        cid = await new_conversation(c)
        codes = [(await send(c, cid, f"m{i}")).status_code for i in range(3)]
    assert codes == [200, 200, 429]


async def test_history_persists_across_restart(
    alice: httpx.AsyncClient, make_app: Callable[..., Awaitable[FastAPI]]
) -> None:
    cid = await new_conversation(alice)
    await send(alice, cid, "remember me")
    restarted = await make_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url="http://test") as c:
        c.cookies.set("session", alice.cookies["session"])
        stored = await messages(c, cid)
    assert [m["content"] for m in stored][0] == "remember me" and stored[1]["status"] == "complete"


async def test_startup_releases_abandoned_streams(
    alice: httpx.AsyncClient, app: FastAPI, make_app: Callable[..., Awaitable[FastAPI]]
) -> None:
    cid = uuid.UUID(await new_conversation(alice))
    async with app.state.db.sessionmaker() as db:
        db.add(Message(conversation_id=cid, seq=1, role="assistant", status="streaming"))
        await db.commit()
    await make_app()  # simulated restart
    stored = await messages(alice, str(cid))
    assert stored[0]["status"] == "failed" and stored[0]["error_code"] == "server_restarted"


# ------------------------------------------------------------------ cancellation (client disconnect)


async def _prepare_slow_turn(app: FastAPI, client: httpx.AsyncClient) -> tuple[ChatService, object, str]:
    cid = await new_conversation(client)
    provider = FakeProvider(chunk_delay_s=0.05)
    service = ChatService(
        settings=app.state.settings,
        registry=app.state.registry,
        provider=provider,
        sessionmaker=app.state.db.sessionmaker,
    )
    me = (await client.get("/api/auth/me")).json()
    async with app.state.db.sessionmaker() as db:
        turn = await service.prepare_new_turn(
            db, uuid.UUID(me["id"]), uuid.UUID(cid), uuid.uuid4(), "one two three four five six seven eight"
        )
    return service, turn, cid


async def test_closing_the_stream_early_saves_partial_reply_as_cancelled(
    alice: httpx.AsyncClient, app: FastAPI
) -> None:
    service, turn, cid = await _prepare_slow_turn(app, alice)
    gen = service.generate(turn)
    received = []
    async for event in gen:
        if event["event"] == "delta":
            received.append(event["data"]["text"])
            if len(received) == 2:
                break
    await gen.aclose()  # what the SSE response does when the client disconnects

    stored = (await messages(alice, cid))[1]
    assert stored["status"] == "cancelled" and stored["error_code"] == "client_disconnected"
    assert stored["content"] == "".join(received)
    [call] = await llm_calls(app)
    assert call.status == "cancelled"


async def test_task_cancellation_still_persists_outcome(alice: httpx.AsyncClient, app: FastAPI) -> None:
    service, turn, cid = await _prepare_slow_turn(app, alice)
    started = asyncio.Event()

    async def consume() -> None:
        async for event in service.generate(turn):
            if event["event"] == "delta":
                started.set()

    task = asyncio.create_task(consume())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    stored = (await messages(alice, cid))[1]
    assert stored["status"] == "cancelled" and stored["content"]


async def test_reply_cut_off_by_max_tokens_is_flagged(alice: httpx.AsyncClient) -> None:
    cid = await new_conversation(alice)
    events = parse_sse((await send(alice, cid, "tell me everything [fake:length]")).text)
    assert events[-1][0] == "done" and events[-1][1]["finish_reason"] == "length"
    stored = (await messages(alice, cid))[1]
    assert stored["status"] == "complete" and stored["error_code"] == "length_limit"


async def test_dropped_history_is_summarised_in_background_and_reused(
    make_app: Callable[..., Awaitable[FastAPI]],
) -> None:
    from app.chat.service import BACKGROUND_TASKS
    from app.conversations.context import SUMMARY_PREFIX

    app = await make_app(context_summarization=True, context_budget_tokens=400, summary_min_new_messages=2)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/auth/register", json={"email": "s@example.com", "password": "password-123"})
        cid = await new_conversation(c, system_prompt=None)
        for i in range(6):
            await send(c, cid, f"fact {i}: my order number is 10{i} " + "detail " * 25)
            if BACKGROUND_TASKS:
                await asyncio.gather(*BACKGROUND_TASKS)

        async with app.state.db.sessionmaker() as db:
            from app.db.models import Conversation

            conv = await db.get(Conversation, uuid.UUID(cid))
            calls = list(await db.scalars(select(LlmCall).where(LlmCall.status == "summary")))
        assert conv.summary and conv.summary_through_seq >= 2
        assert calls and calls[0].input_tokens  # summary calls are accounted for

        resp = await send(c, cid, "what do you remember?")
        assert resp.status_code == 200, resp.text
        # The fake provider also records background summary calls; pick the chat request.
        sent = next(
            r
            for r in reversed(app.state.provider.requests)
            if r.messages[-1].content == "what do you remember?"
        )
        summary_msgs = [m for m in sent.messages if m.content.startswith(SUMMARY_PREFIX)]
        assert len(summary_msgs) == 1 and sent.messages[0] == summary_msgs[0]
        assert sum(len(m.content) // 4 + 7 for m in sent.messages) <= 400  # still within budget


async def test_summarisation_is_off_by_default(alice: httpx.AsyncClient, app: FastAPI) -> None:
    cid = await new_conversation(alice)
    for i in range(3):
        await send(alice, cid, f"message {i}")
    async with app.state.db.sessionmaker() as db:
        from app.db.models import Conversation

        assert (await db.get(Conversation, uuid.UUID(cid))).summary is None
    assert not any(m.content.startswith("Summary") for r in app.state.provider.requests for m in r.messages)
