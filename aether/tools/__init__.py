"""Custom MCP tools the agent uses to manage memory, skills, schedules, and itself.

Bundled into a single in-process MCP server (`aether`) so all tools register as
`mcp__aether__<name>` in the Claude Agent SDK.
"""

from __future__ import annotations

from claude_agent_sdk import create_sdk_mcp_server

from aether.memory import MemoryStore
from aether.skills import SkillRegistry
from aether.tools.memory import build_memory_tools
from aether.tools.skills import build_skill_tools
from aether.tools.schedule import build_schedule_tools


def build_aether_mcp_server(
    *,
    memory: MemoryStore,
    registry: SkillRegistry,
    current_user_id_provider,
    current_session_id_provider,
):
    tools = []
    tools += build_memory_tools(memory, current_user_id_provider, current_session_id_provider)
    tools += build_skill_tools(registry)
    tools += build_schedule_tools(memory, current_user_id_provider)
    return create_sdk_mcp_server(name="aether", version="0.1.0", tools=tools)


def aether_tool_names() -> list[str]:
    """Pre-approved allowlist for permission_mode=dontAsk users."""
    return [
        "mcp__aether__remember",
        "mcp__aether__recall",
        "mcp__aether__forget",
        "mcp__aether__list_facts",
        "mcp__aether__update_user_profile",
        "mcp__aether__create_skill",
        "mcp__aether__edit_skill",
        "mcp__aether__list_skills",
        "mcp__aether__delete_skill",
        "mcp__aether__schedule",
        "mcp__aether__list_schedules",
        "mcp__aether__cancel_schedule",
    ]
