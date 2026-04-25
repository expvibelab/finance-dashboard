"""Memory tools: remember, recall, forget, list facts, update user profile."""

from __future__ import annotations

from typing import Any, Callable

from claude_agent_sdk import tool

from aether.memory import MemoryStore, format_facts_for_prompt


def build_memory_tools(
    store: MemoryStore,
    user_id_provider: Callable[[], str],
    session_id_provider: Callable[[], str | None],
):
    @tool(
        "remember",
        "Save a durable fact about the current user. Use for stable preferences, "
        "biographical details, project context, and decisions you should recall in "
        "future conversations. Avoid storing one-off transient information.",
        {"fact": str, "category": str, "confidence": float},
    )
    async def remember(args: dict[str, Any]) -> dict[str, Any]:
        fact = (args.get("fact") or "").strip()
        if not fact:
            return _err("`fact` is required")
        category = args.get("category") or None
        confidence = float(args.get("confidence", 0.7))
        fid = await store.add_fact(
            user_id_provider(),
            fact,
            category=category,
            confidence=confidence,
            source_session_id=session_id_provider(),
        )
        return _ok(f"Saved fact #{fid}: {fact}")

    @tool(
        "recall",
        "Search prior conversations and facts using full-text search. "
        "Returns the most relevant snippets across every past session for the "
        "current user. Use when the user references something they 'told you before'.",
        {"query": str, "limit": int},
    )
    async def recall(args: dict[str, Any]) -> dict[str, Any]:
        q = (args.get("query") or "").strip()
        if not q:
            return _err("`query` is required")
        limit = int(args.get("limit") or 10)
        rows = await store.search_messages(q, user_id=user_id_provider(), limit=limit)
        if not rows:
            return _ok("No matches.")
        lines = []
        for r in rows:
            snippet = r["content"].replace("\n", " ")[:200]
            lines.append(f"[{r['role']} · {r['source']}] {snippet}")
        return _ok("\n".join(lines))

    @tool(
        "list_facts",
        "List all facts you currently remember about the user. Optional category filter.",
        {"category": str},
    )
    async def list_facts(args: dict[str, Any]) -> dict[str, Any]:
        cat = args.get("category") or None
        facts = await store.list_facts(user_id_provider(), category=cat)
        return _ok(format_facts_for_prompt(facts))

    @tool(
        "forget",
        "Mark a fact as superseded so it no longer surfaces. Pass the fact id from list_facts.",
        {"fact_id": int},
    )
    async def forget(args: dict[str, Any]) -> dict[str, Any]:
        fid = args.get("fact_id")
        if not isinstance(fid, int):
            return _err("`fact_id` (int) is required")
        await store.supersede_fact(fid, replacement_id=None)
        return _ok(f"Forgot fact #{fid}.")

    @tool(
        "update_user_profile",
        "Update the long-form summary of who the user is, their tone preferences, "
        "and current interests. Overwrites the existing summary.",
        {"summary": str, "tone": str, "interests": list},
    )
    async def update_user_profile(args: dict[str, Any]) -> dict[str, Any]:
        await store.upsert_user_model(
            user_id_provider(),
            summary=args.get("summary"),
            tone=args.get("tone"),
            interests=args.get("interests") or [],
        )
        return _ok("User profile updated.")

    return [remember, recall, forget, list_facts, update_user_profile]


def _ok(msg: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": msg}]}


def _err(msg: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": msg}], "is_error": True}
