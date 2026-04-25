"""Aether agent core: wraps ClaudeSDKClient with persistence and live streaming.

Responsibilities
----------------
- Build the system prompt from CLAUDE.md + MEMORY.md + per-user facts + user model.
- Construct the in-process MCP server with our custom tools.
- Drive the SDK's message loop, mirroring messages into SQLite and broadcasting
  tool-call events to gateway listeners.
- Track session lifecycle (create / resume / fork / end) and message counts.
- Trigger memory-curation nudges and self-evolution sweeps post-session.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
)

from aether.config import Settings, get_settings
from aether.memory import MemoryStore, format_facts_for_prompt
from aether.skills import SkillRegistry
from aether.streaming import StreamBroadcaster, StreamEvent
from aether.tools import build_aether_mcp_server, aether_tool_names
from aether.subagents import build_agent_definitions

log = logging.getLogger("aether.core")


# ContextVars give the in-process MCP tools access to the active user/session
# without threading them through every call.
_current_user_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "aether_user_id", default="local"
)
_current_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "aether_session_id", default=None
)


def _user_id_provider() -> str:
    return _current_user_id.get()


def _session_id_provider() -> str | None:
    return _current_session_id.get()


# Tools the agent gets out of the box on top of our custom MCP server.
DEFAULT_BUILTIN_TOOLS: tuple[str, ...] = (
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "Bash",
    "WebFetch",
    "WebSearch",
    "Skill",
    "Agent",
    "TodoWrite",
)


@dataclass
class AgentResponse:
    text: str
    session_id: str | None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0


class Agent:
    """Long-lived agent attached to a project workspace."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        project_root: Path | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.project_root = (project_root or Path.cwd()).resolve()
        self.memory = MemoryStore(self.settings.db_path)
        self.skills = SkillRegistry(self.project_root / ".claude" / "skills")
        self._initialised = False

    async def initialize(self) -> None:
        if self._initialised:
            return
        await self.memory.initialize()
        self._initialised = True
        log.info("Aether ready · model=%s · home=%s", self.settings.model, self.settings.home)

    # ---------- System prompt ----------

    async def _build_system_prompt(self, user_id: str) -> str:
        parts: list[str] = []
        claude_md = self.project_root / "CLAUDE.md"
        if claude_md.exists():
            parts.append(claude_md.read_text(encoding="utf-8"))
        memory_md = self.project_root / "MEMORY.md"
        if memory_md.exists():
            parts.append("# Curated Memory (MEMORY.md)\n" + memory_md.read_text(encoding="utf-8"))

        facts = await self.memory.list_facts(user_id, limit=200)
        parts.append(
            "# Facts about the current user\n" + format_facts_for_prompt(facts)
        )
        user_model = await self.memory.get_user_model(user_id)
        if user_model.get("summary"):
            parts.append(
                "# User model\n"
                f"Summary: {user_model['summary']}\n"
                f"Tone: {user_model.get('tone') or '(not set)'}\n"
                f"Interests: {', '.join(user_model.get('interests') or []) or '(none)'}"
            )
        return "\n\n".join(parts)

    # ---------- SDK options ----------

    def _build_options(
        self,
        *,
        system_prompt: str,
        resume_session: str | None,
        broadcaster: StreamBroadcaster,
    ) -> ClaudeAgentOptions:
        mcp_server = build_aether_mcp_server(
            memory=self.memory,
            registry=self.skills,
            current_user_id_provider=_user_id_provider,
            current_session_id_provider=_session_id_provider,
        )
        agent_defs = build_agent_definitions()

        # Allow the in-built tools, all aether MCP tools, and any external MCP servers
        allowed = list(DEFAULT_BUILTIN_TOOLS) + aether_tool_names()

        async def on_pre_tool(input_data, tool_use_id, _ctx):
            tool_name = input_data.get("tool_name", "?")
            tool_input = input_data.get("tool_input") or {}
            await broadcaster.emit(
                StreamEvent(
                    kind="tool_call",
                    tool_name=tool_name,
                    tool_input=tool_input,
                )
            )
            return {}

        async def on_post_tool(input_data, tool_use_id, _ctx):
            tool_name = input_data.get("tool_name", "?")
            response = input_data.get("tool_response") or {}
            text = ""
            if isinstance(response, dict):
                content = response.get("content")
                if isinstance(content, list) and content:
                    first = content[0]
                    if isinstance(first, dict):
                        text = first.get("text", "")
            await broadcaster.emit(
                StreamEvent(kind="tool_result", tool_name=tool_name, text=str(text))
            )
            return {"async_": True, "asyncTimeout": 5000}

        options = ClaudeAgentOptions(
            model=self.settings.model,
            system_prompt={
                "type": "preset",
                "preset": "claude_code",
                "append": system_prompt,
            },
            cwd=str(self.project_root),
            setting_sources=["project", "user"],
            allowed_tools=allowed,
            permission_mode=self.settings.permission_mode,
            max_turns=self.settings.max_turns,
            mcp_servers={"aether": mcp_server},
            agents=agent_defs,
            hooks={
                "PreToolUse": [HookMatcher(matcher=".*", hooks=[on_pre_tool])],
                "PostToolUse": [HookMatcher(matcher=".*", hooks=[on_post_tool])],
            },
            resume=resume_session,
        )
        return options

    # ---------- Run a turn ----------

    async def run_turn(
        self,
        *,
        prompt: str,
        user_id: str,
        source: str,
        broadcaster: StreamBroadcaster | None = None,
        resume_session: str | None = None,
    ) -> AgentResponse:
        await self.initialize()
        broadcaster = broadcaster or StreamBroadcaster()
        token_user = _current_user_id.set(user_id)
        token_session = _current_session_id.set(None)
        try:
            # Resume if the user has an active session for this source, else create one.
            session_obj = None
            if resume_session is None:
                session_obj = await self.memory.latest_session_for_user(user_id, source)
            session_id = resume_session or (session_obj.id if session_obj else None)

            if session_id is None:
                created = await self.memory.create_session(
                    source=source,
                    user_id=user_id,
                    model=self.settings.model,
                )
                session_id = created.id
            _current_session_id.set(session_id)

            await self.memory.append_message(session_id, "user", prompt)

            system_prompt = await self._build_system_prompt(user_id)
            options = self._build_options(
                system_prompt=system_prompt,
                resume_session=resume_session,
                broadcaster=broadcaster,
            )

            text_chunks: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            cost = 0.0
            in_tokens = 0
            out_tokens = 0

            async with ClaudeSDKClient(options=options) as client:
                await client.query(prompt)
                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                text_chunks.append(block.text)
                                await broadcaster.emit(
                                    StreamEvent(kind="assistant_text", text=block.text)
                                )
                            elif isinstance(block, ToolUseBlock):
                                tool_calls.append(
                                    {
                                        "name": block.name,
                                        "input": block.input,
                                        "id": block.id,
                                    }
                                )
                    elif isinstance(message, SystemMessage):
                        # First system message contains session metadata.
                        pass
                    elif isinstance(message, ResultMessage):
                        cost = float(getattr(message, "total_cost_usd", 0) or 0)
                        usage = getattr(message, "usage", None) or {}
                        if isinstance(usage, dict):
                            in_tokens = int(usage.get("input_tokens", 0) or 0)
                            out_tokens = int(usage.get("output_tokens", 0) or 0)

            full_text = "".join(text_chunks).strip()
            await self.memory.append_message(
                session_id,
                "assistant",
                full_text,
                tool_calls=tool_calls or None,
            )

            await broadcaster.emit(StreamEvent(kind="done"))
            await broadcaster.close()

            return AgentResponse(
                text=full_text,
                session_id=session_id,
                tool_calls=tool_calls,
                cost_usd=cost,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
            )
        except Exception as exc:
            log.exception("agent turn failed: %s", exc)
            await broadcaster.emit(StreamEvent(kind="error", text=str(exc)))
            await broadcaster.close()
            raise
        finally:
            _current_user_id.reset(token_user)
            _current_session_id.reset(token_session)

    async def reset_session(self, user_id: str, source: str) -> None:
        """Mark the user's current session ended; next turn creates a fresh one."""
        sess = await self.memory.latest_session_for_user(user_id, source)
        if sess is not None:
            await self.memory.end_session(sess.id, reason="user_reset")
