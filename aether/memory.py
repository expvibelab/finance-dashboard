"""Persistent memory store: sessions, messages, FTS5 search, agent-curated facts.

Schema mirrors Hermes' core tables (sessions, messages, messages_fts) so we get the
same cross-session recall behaviour. Adds `facts` (curated by the agent), `skill_uses`
(usage tracking that drives self-evolution), and `schedules` (cron jobs).
"""

from __future__ import annotations

import json
import re
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

import aiosqlite

SCHEMA_VERSION = 1


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    user_id TEXT,
    model TEXT,
    system_prompt TEXT,
    started_at REAL NOT NULL,
    ended_at REAL,
    end_reason TEXT,
    title TEXT,
    parent_session_id TEXT,
    message_count INTEGER NOT NULL DEFAULT 0,
    tool_call_count INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_source ON sessions(source);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp REAL NOT NULL,
    tool_call_id TEXT,
    tool_calls TEXT,
    tool_name TEXT,
    token_count INTEGER,
    finish_reason TEXT,
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, timestamp);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    role UNINDEXED,
    session_id UNINDEXED,
    content='messages',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content, role, session_id)
    VALUES (new.id, new.content, new.role, new.session_id);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content, role, session_id)
    VALUES ('delete', old.id, old.content, old.role, old.session_id);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_update AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content, role, session_id)
    VALUES ('delete', old.id, old.content, old.role, old.session_id);
    INSERT INTO messages_fts(rowid, content, role, session_id)
    VALUES (new.id, new.content, new.role, new.session_id);
END;

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    fact TEXT NOT NULL,
    category TEXT,
    confidence REAL NOT NULL DEFAULT 0.5,
    source_session_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    superseded_by INTEGER
);
CREATE INDEX IF NOT EXISTS idx_facts_user ON facts(user_id);
CREATE INDEX IF NOT EXISTS idx_facts_active ON facts(user_id) WHERE superseded_by IS NULL;

CREATE TABLE IF NOT EXISTS user_models (
    user_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL DEFAULT '',
    tone TEXT,
    interests TEXT,
    last_updated REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS skill_uses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name TEXT NOT NULL,
    session_id TEXT,
    success INTEGER NOT NULL,
    notes TEXT,
    timestamp REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skill_uses_name ON skill_uses(skill_name, timestamp DESC);

CREATE TABLE IF NOT EXISTS schedules (
    id TEXT PRIMARY KEY,
    cron TEXT NOT NULL,
    prompt TEXT NOT NULL,
    deliver_to TEXT NOT NULL,
    user_id TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    last_run_at REAL,
    last_status TEXT
);
"""


# FTS5 reserved tokens we strip from user input before searching.
_FTS_OPS = re.compile(r'[":\(\)\*]+')


def _sanitize_fts(query: str) -> str:
    """Sanitise a user-provided FTS5 query.

    Hermes' approach: wrap hyphenated terms in quotes, strip unmatched operators,
    and fall back to a phrase match when nothing usable remains.
    """
    if not query:
        return '""'
    cleaned = _FTS_OPS.sub(" ", query).strip()
    if not cleaned:
        return f'"{query[:64]}"'
    parts = []
    for tok in cleaned.split():
        if "-" in tok:
            parts.append(f'"{tok}"')
        else:
            parts.append(tok)
    return " ".join(parts)


def _now() -> float:
    return time.time()


@dataclass
class Session:
    id: str
    source: str
    user_id: str | None
    model: str | None
    started_at: float
    title: str | None = None
    parent_session_id: str | None = None
    message_count: int = 0


@dataclass
class Message:
    id: int | None
    session_id: str
    role: str
    content: str
    timestamp: float
    tool_name: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Fact:
    id: int
    user_id: str
    fact: str
    category: str | None
    confidence: float
    created_at: float


class MemoryStore:
    """Async SQLite-backed persistence layer."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        conn = await aiosqlite.connect(self.db_path, timeout=1.0)
        try:
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA foreign_keys=ON")
            await conn.execute("PRAGMA synchronous=NORMAL")
            conn.row_factory = aiosqlite.Row
            yield conn
        finally:
            await conn.close()

    async def initialize(self) -> None:
        async with self._connect() as conn:
            await conn.executescript(SCHEMA)
            cur = await conn.execute("SELECT version FROM schema_version LIMIT 1")
            row = await cur.fetchone()
            if row is None:
                await conn.execute(
                    "INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,)
                )
            await conn.commit()

    # ---------- Sessions ----------

    async def create_session(
        self,
        *,
        source: str,
        user_id: str | None,
        model: str | None,
        system_prompt: str | None = None,
        parent_session_id: str | None = None,
    ) -> Session:
        sid = str(uuid.uuid4())
        now = _now()
        async with self._connect() as conn:
            await conn.execute(
                """
                INSERT INTO sessions(id, source, user_id, model, system_prompt,
                                     started_at, parent_session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (sid, source, user_id, model, system_prompt, now, parent_session_id),
            )
            await conn.commit()
        return Session(
            id=sid,
            source=source,
            user_id=user_id,
            model=model,
            started_at=now,
            parent_session_id=parent_session_id,
        )

    async def end_session(self, session_id: str, *, reason: str = "complete") -> None:
        async with self._connect() as conn:
            await conn.execute(
                "UPDATE sessions SET ended_at=?, end_reason=? WHERE id=?",
                (_now(), reason, session_id),
            )
            await conn.commit()

    async def latest_session_for_user(
        self, user_id: str, source: str
    ) -> Session | None:
        async with self._connect() as conn:
            cur = await conn.execute(
                """
                SELECT id, source, user_id, model, started_at, title,
                       parent_session_id, message_count
                FROM sessions
                WHERE user_id=? AND source=?
                ORDER BY started_at DESC LIMIT 1
                """,
                (user_id, source),
            )
            row = await cur.fetchone()
            if row is None:
                return None
            return Session(**dict(row))

    # ---------- Messages ----------

    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        tool_name: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> int:
        async with self._connect() as conn:
            cur = await conn.execute(
                """
                INSERT INTO messages(session_id, role, content, timestamp,
                                     tool_name, tool_calls)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    role,
                    content,
                    _now(),
                    tool_name,
                    json.dumps(tool_calls) if tool_calls else None,
                ),
            )
            await conn.execute(
                "UPDATE sessions SET message_count = message_count + 1 WHERE id=?",
                (session_id,),
            )
            if tool_name:
                await conn.execute(
                    "UPDATE sessions SET tool_call_count = tool_call_count + 1 WHERE id=?",
                    (session_id,),
                )
            await conn.commit()
            return cur.lastrowid or 0

    async def session_messages(
        self, session_id: str, limit: int | None = None
    ) -> list[Message]:
        sql = (
            "SELECT id, session_id, role, content, timestamp, tool_name, tool_calls "
            "FROM messages WHERE session_id=? ORDER BY timestamp ASC"
        )
        params: tuple[Any, ...] = (session_id,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (session_id, limit)
        async with self._connect() as conn:
            cur = await conn.execute(sql, params)
            rows = await cur.fetchall()
        out: list[Message] = []
        for r in rows:
            out.append(
                Message(
                    id=r["id"],
                    session_id=r["session_id"],
                    role=r["role"],
                    content=r["content"],
                    timestamp=r["timestamp"],
                    tool_name=r["tool_name"],
                    tool_calls=json.loads(r["tool_calls"]) if r["tool_calls"] else [],
                )
            )
        return out

    async def search_messages(
        self, query: str, *, user_id: str | None = None, limit: int = 25
    ) -> list[dict[str, Any]]:
        """Full-text search across all messages, optionally scoped by user_id."""
        fts = _sanitize_fts(query)
        sql = (
            "SELECT m.id, m.session_id, m.role, m.content, m.timestamp, "
            "       s.source, s.user_id, s.title "
            "FROM messages_fts f "
            "JOIN messages m ON m.id = f.rowid "
            "JOIN sessions s ON s.id = m.session_id "
            "WHERE messages_fts MATCH ? "
        )
        params: list[Any] = [fts]
        if user_id:
            sql += "AND s.user_id = ? "
            params.append(user_id)
        sql += "ORDER BY rank LIMIT ?"
        params.append(limit)
        async with self._connect() as conn:
            cur = await conn.execute(sql, tuple(params))
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # ---------- Facts (agent-curated MEMORY.md analogue) ----------

    async def add_fact(
        self,
        user_id: str,
        fact: str,
        *,
        category: str | None = None,
        confidence: float = 0.7,
        source_session_id: str | None = None,
    ) -> int:
        now = _now()
        async with self._connect() as conn:
            cur = await conn.execute(
                """
                INSERT INTO facts(user_id, fact, category, confidence,
                                  source_session_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, fact, category, confidence, source_session_id, now, now),
            )
            await conn.commit()
            return cur.lastrowid or 0

    async def list_facts(
        self, user_id: str, *, category: str | None = None, limit: int = 200
    ) -> list[Fact]:
        sql = (
            "SELECT id, user_id, fact, category, confidence, created_at "
            "FROM facts WHERE user_id=? AND superseded_by IS NULL "
        )
        params: list[Any] = [user_id]
        if category:
            sql += "AND category=? "
            params.append(category)
        sql += "ORDER BY confidence DESC, updated_at DESC LIMIT ?"
        params.append(limit)
        async with self._connect() as conn:
            cur = await conn.execute(sql, tuple(params))
            rows = await cur.fetchall()
        return [Fact(**dict(r)) for r in rows]

    async def supersede_fact(self, fact_id: int, *, replacement_id: int | None) -> None:
        async with self._connect() as conn:
            await conn.execute(
                "UPDATE facts SET superseded_by=?, updated_at=? WHERE id=?",
                (replacement_id, _now(), fact_id),
            )
            await conn.commit()

    # ---------- User model (Honcho-equivalent) ----------

    async def get_user_model(self, user_id: str) -> dict[str, Any]:
        async with self._connect() as conn:
            cur = await conn.execute(
                "SELECT user_id, summary, tone, interests, last_updated "
                "FROM user_models WHERE user_id=?",
                (user_id,),
            )
            row = await cur.fetchone()
        if row is None:
            return {"user_id": user_id, "summary": "", "tone": None, "interests": []}
        d = dict(row)
        d["interests"] = json.loads(d["interests"]) if d["interests"] else []
        return d

    async def upsert_user_model(
        self,
        user_id: str,
        *,
        summary: str | None = None,
        tone: str | None = None,
        interests: list[str] | None = None,
    ) -> None:
        existing = await self.get_user_model(user_id)
        new_summary = summary if summary is not None else existing["summary"]
        new_tone = tone if tone is not None else existing.get("tone")
        new_interests = interests if interests is not None else existing.get("interests") or []
        async with self._connect() as conn:
            await conn.execute(
                """
                INSERT INTO user_models(user_id, summary, tone, interests, last_updated)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    summary=excluded.summary,
                    tone=excluded.tone,
                    interests=excluded.interests,
                    last_updated=excluded.last_updated
                """,
                (user_id, new_summary, new_tone, json.dumps(new_interests), _now()),
            )
            await conn.commit()

    # ---------- Skill usage tracking ----------

    async def record_skill_use(
        self,
        skill_name: str,
        *,
        session_id: str | None,
        success: bool,
        notes: str | None = None,
    ) -> None:
        async with self._connect() as conn:
            await conn.execute(
                """
                INSERT INTO skill_uses(skill_name, session_id, success, notes, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (skill_name, session_id, 1 if success else 0, notes, _now()),
            )
            await conn.commit()

    async def skill_use_stats(self) -> list[dict[str, Any]]:
        async with self._connect() as conn:
            cur = await conn.execute(
                """
                SELECT skill_name,
                       COUNT(*) AS uses,
                       SUM(success) AS successes,
                       MAX(timestamp) AS last_used
                FROM skill_uses
                GROUP BY skill_name
                ORDER BY uses DESC
                """
            )
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # ---------- Schedules ----------

    async def add_schedule(
        self,
        *,
        cron: str,
        prompt: str,
        deliver_to: str,
        user_id: str | None,
    ) -> str:
        sid = str(uuid.uuid4())
        async with self._connect() as conn:
            await conn.execute(
                """
                INSERT INTO schedules(id, cron, prompt, deliver_to, user_id,
                                      enabled, created_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (sid, cron, prompt, deliver_to, user_id, _now()),
            )
            await conn.commit()
        return sid

    async def list_schedules(
        self, *, user_id: str | None = None, only_enabled: bool = True
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM schedules WHERE 1=1 "
        params: list[Any] = []
        if user_id:
            sql += "AND user_id=? "
            params.append(user_id)
        if only_enabled:
            sql += "AND enabled=1 "
        sql += "ORDER BY created_at DESC"
        async with self._connect() as conn:
            cur = await conn.execute(sql, tuple(params))
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def remove_schedule(self, schedule_id: str) -> bool:
        async with self._connect() as conn:
            cur = await conn.execute(
                "UPDATE schedules SET enabled=0 WHERE id=?", (schedule_id,)
            )
            await conn.commit()
            return cur.rowcount > 0

    async def mark_schedule_run(
        self, schedule_id: str, *, status: str
    ) -> None:
        async with self._connect() as conn:
            await conn.execute(
                "UPDATE schedules SET last_run_at=?, last_status=? WHERE id=?",
                (_now(), status, schedule_id),
            )
            await conn.commit()


def format_facts_for_prompt(facts: list[Fact]) -> str:
    """Render the user's curated facts as a compact bulleted list."""
    if not facts:
        return "(no facts recorded yet)"
    lines = []
    for f in facts:
        cat = f"[{f.category}] " if f.category else ""
        lines.append(f"- {cat}{f.fact}")
    return "\n".join(lines)


def utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")
