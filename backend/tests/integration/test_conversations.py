"""Conversation CRUD, settings validation, ordering, persistence and cross-user isolation."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from app.db.models import Conversation, Message


async def _create(client: httpx.AsyncClient, **body: object) -> dict:
    resp = await client.post("/api/conversations", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_create_with_defaults(alice: httpx.AsyncClient) -> None:
    conv = await _create(alice)
    assert conv["title"] == "New conversation"
    assert conv["system_prompt"].startswith("You are a friendly, professional customer-support assistant")
    assert conv["settings"] == {"model": "qwen/qwen3.8-27b", "temperature": 0.3, "max_tokens": 800}


async def test_create_with_settings_and_validation(alice: httpx.AsyncClient) -> None:
    conv = await _create(
        alice,
        title="  Refund question  ",
        system_prompt="You support Acme.",
        settings={"model": "openai/gpt-oss-20b", "temperature": 0.7},
    )
    assert conv["title"] == "Refund question"
    assert conv["settings"] == {"model": "openai/gpt-oss-20b", "temperature": 0.7, "max_tokens": 1000}

    bad_model = await alice.post("/api/conversations", json={"settings": {"model": "allam-2-7b"}})
    assert bad_model.status_code == 422 and bad_model.json()["error"]["code"] == "invalid_model"
    too_many = await alice.post("/api/conversations", json={"settings": {"max_tokens": 999999}})
    assert too_many.json()["error"]["code"] == "invalid_settings"
    bad_temp = await alice.post("/api/conversations", json={"settings": {"temperature": 5}})
    assert bad_temp.json()["error"]["code"] == "validation_error"
    long_prompt = await alice.post("/api/conversations", json={"system_prompt": "x" * 4001})
    assert long_prompt.status_code == 422


async def test_list_is_newest_first_and_excludes_deleted(alice: httpx.AsyncClient) -> None:
    first = await _create(alice, title="first")
    second = await _create(alice, title="second")
    await alice.patch(f"/api/conversations/{first['id']}", json={"title": "first (edited)"})
    titles = [c["title"] for c in (await alice.get("/api/conversations")).json()]
    assert titles == ["first (edited)", "second"]  # most recently updated first

    assert (await alice.delete(f"/api/conversations/{second['id']}")).status_code == 204
    assert [c["id"] for c in (await alice.get("/api/conversations")).json()] == [first["id"]]
    assert (await alice.get(f"/api/conversations/{second['id']}")).status_code == 404


async def test_patch_updates_only_given_fields(alice: httpx.AsyncClient) -> None:
    conv = await _create(alice, title="t", system_prompt="keep me", settings={"temperature": 0.9})
    url = f"/api/conversations/{conv['id']}"

    renamed = (await alice.patch(url, json={"title": "renamed"})).json()
    assert renamed["system_prompt"] == "keep me" and renamed["settings"]["temperature"] == 0.9

    switched = (await alice.patch(url, json={"settings": {"model": "openai/gpt-oss-20b"}})).json()
    # Model change resets max_tokens to the new model's default but keeps temperature.
    assert switched["settings"] == {"model": "openai/gpt-oss-20b", "temperature": 0.9, "max_tokens": 1000}

    cleared = (await alice.patch(url, json={"system_prompt": None})).json()
    assert cleared["system_prompt"] is None and cleared["title"] == "renamed"


async def test_other_users_conversations_are_invisible(
    alice: httpx.AsyncClient, bob: httpx.AsyncClient
) -> None:
    conv = await _create(alice, title="alice private")
    url = f"/api/conversations/{conv['id']}"

    assert (await bob.get("/api/conversations")).json() == []
    for method, path, body in [
        ("GET", url, None),
        ("PATCH", url, {"title": "hijacked"}),
        ("DELETE", url, None),
        ("GET", f"{url}/messages", None),
    ]:
        resp = await bob.request(method, path, json=body)
        assert resp.status_code == 404, (method, path)
        assert resp.json()["error"]["code"] == "not_found"

    # Same response as a conversation that does not exist at all (no existence leak).
    missing = await bob.get(f"/api/conversations/{uuid.uuid4()}")
    assert missing.json()["error"]["message"] == (await bob.get(url)).json()["error"]["message"]
    # Alice's data is untouched.
    assert (await alice.get(url)).json()["title"] == "alice private"


async def test_messages_are_ordered_by_seq(alice: httpx.AsyncClient, app: FastAPI) -> None:
    conv = await _create(alice)
    cid = uuid.UUID(conv["id"])
    async with app.state.db.sessionmaker() as db:  # inserted out of order on purpose
        db.add_all(
            [
                Message(conversation_id=cid, seq=2, role="assistant", content="second"),
                Message(conversation_id=cid, seq=1, role="user", content="first"),
                Message(conversation_id=cid, seq=3, role="user", content="third"),
            ]
        )
        await db.commit()
    msgs = (await alice.get(f"/api/conversations/{cid}/messages")).json()
    assert [(m["seq"], m["content"]) for m in msgs] == [(1, "first"), (2, "second"), (3, "third")]


async def test_db_enforces_one_streaming_reply_per_conversation(
    alice: httpx.AsyncClient, app: FastAPI
) -> None:
    import pytest
    from sqlalchemy.exc import IntegrityError

    cid = uuid.UUID((await _create(alice))["id"])
    async with app.state.db.sessionmaker() as db:
        db.add(Message(conversation_id=cid, seq=1, role="assistant", status="streaming"))
        await db.commit()
        db.add(Message(conversation_id=cid, seq=2, role="assistant", status="streaming"))
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_data_persists_across_app_restart(
    alice: httpx.AsyncClient, make_app: Callable[..., Awaitable[FastAPI]]
) -> None:
    conv = await _create(alice, title="survives restart")
    restarted = await make_app()  # fresh app instance + fresh engine, same DB
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url="http://test") as c:
        c.cookies.set("session", alice.cookies["session"])
        assert (await c.get(f"/api/conversations/{conv['id']}")).json()["title"] == "survives restart"
        async with restarted.state.db.sessionmaker() as db:
            assert await db.scalar(select(Conversation.title)) == "survives restart"


async def test_invalid_uuid_path_is_validation_error(alice: httpx.AsyncClient) -> None:
    resp = await alice.get("/api/conversations/not-a-uuid")
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "validation_error"


async def test_explicit_null_system_prompt_overrides_default(alice: httpx.AsyncClient) -> None:
    assert (await _create(alice, system_prompt=None))["system_prompt"] is None
    assert (await _create(alice, system_prompt="Custom."))["system_prompt"] == "Custom."
