"""Tool-call event broadcast: turns SDK message stream into platform-friendly updates.

A `StreamBroadcaster` is created per session. The core loop forwards every
SDK message to it; gateway adapters subscribe via async iteration to render
"calling tool: X(...)" updates in Telegram, Discord, the CLI, etc.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Literal


EventKind = Literal[
    "thinking",
    "tool_call",
    "tool_result",
    "assistant_text",
    "done",
    "error",
    "subagent",
]


@dataclass
class StreamEvent:
    kind: EventKind
    text: str = ""
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    def render(self, *, compact: bool = True) -> str:
        if self.kind == "tool_call":
            args = ""
            if self.tool_input and compact:
                args = _compact_args(self.tool_input)
            return f"🔧 `{self.tool_name}`{args}"
        if self.kind == "tool_result":
            return f"✓ `{self.tool_name}` → {self.text[:200]}"
        if self.kind == "assistant_text":
            return self.text
        if self.kind == "subagent":
            return f"↘ delegating to **{self.tool_name}** — {self.text}"
        if self.kind == "thinking":
            return f"💭 {self.text}"
        if self.kind == "error":
            return f"⚠️ {self.text}"
        if self.kind == "done":
            return ""
        return self.text


def _compact_args(args: dict[str, Any], max_len: int = 80) -> str:
    if not args:
        return ""
    try:
        s = json.dumps(args, ensure_ascii=False)
    except TypeError:
        s = str(args)
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return f"({s})"


class StreamBroadcaster:
    """Fan-out async queue. Multiple gateway listeners can subscribe."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[StreamEvent | None]] = []
        self._closed = False

    def subscribe(self) -> asyncio.Queue[StreamEvent | None]:
        q: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
        self._subscribers.append(q)
        return q

    async def emit(self, event: StreamEvent) -> None:
        if self._closed:
            return
        for q in self._subscribers:
            await q.put(event)

    async def close(self) -> None:
        self._closed = True
        for q in self._subscribers:
            await q.put(None)

    async def listen(self) -> AsyncIterator[StreamEvent]:
        q = self.subscribe()
        while True:
            event = await q.get()
            if event is None:
                return
            yield event
