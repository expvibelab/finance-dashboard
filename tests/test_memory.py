"""Smoke tests for the memory store. Run with: pytest tests/"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from aether.memory import MemoryStore


@pytest.fixture
async def store():
    with tempfile.TemporaryDirectory() as tmp:
        s = MemoryStore(Path(tmp) / "test.db")
        await s.initialize()
        yield s


async def test_session_and_messages(store):
    sess = await store.create_session(source="cli", user_id="alice", model="opus")
    await store.append_message(sess.id, "user", "hello")
    await store.append_message(sess.id, "assistant", "hi there")
    msgs = await store.session_messages(sess.id)
    assert [m.role for m in msgs] == ["user", "assistant"]


async def test_fts_recall(store):
    sess = await store.create_session(source="cli", user_id="alice", model="opus")
    await store.append_message(sess.id, "user", "I love sourdough bread baking")
    await store.append_message(sess.id, "user", "What's the weather in Paris")
    rows = await store.search_messages("sourdough", user_id="alice")
    assert any("sourdough" in r["content"] for r in rows)
    rows2 = await store.search_messages("paris", user_id="alice")
    assert any("Paris" in r["content"] for r in rows2)


async def test_facts(store):
    fid = await store.add_fact("alice", "Prefers TypeScript", category="preference")
    facts = await store.list_facts("alice")
    assert any(f.id == fid for f in facts)
    await store.supersede_fact(fid, replacement_id=None)
    facts2 = await store.list_facts("alice")
    assert all(f.id != fid for f in facts2)


async def test_user_model(store):
    await store.upsert_user_model("alice", summary="Rust enthusiast", interests=["rust"])
    m = await store.get_user_model("alice")
    assert m["summary"] == "Rust enthusiast"
    assert m["interests"] == ["rust"]
