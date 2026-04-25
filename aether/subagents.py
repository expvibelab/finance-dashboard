"""Programmatic subagent definitions passed to ClaudeAgentOptions.agents.

Filesystem-based agents in `.claude/agents/` are also picked up automatically
when `setting_sources=["project"]`. We define a core set programmatically so
the system works even if the .claude tree gets clobbered.
"""

from __future__ import annotations

from claude_agent_sdk import AgentDefinition


def build_agent_definitions() -> dict[str, AgentDefinition]:
    return {
        "researcher": AgentDefinition(
            description=(
                "Use for open-ended investigation, gathering facts from the web or "
                "the codebase, and producing concise written briefings. Read-only."
            ),
            prompt=(
                "You are a research specialist. Be thorough but concise. "
                "Cite sources with URLs where applicable. Return a tight bulleted "
                "summary unless asked for prose. Never write code — your output is text."
            ),
            tools=["Read", "Glob", "Grep", "WebSearch", "WebFetch"],
            model="sonnet",
        ),
        "coder": AgentDefinition(
            description=(
                "Use for focused code changes the parent agent can hand off in full. "
                "Receives a clear spec and edits files autonomously."
            ),
            prompt=(
                "You are an implementation specialist. Make the requested code "
                "changes precisely. Run any obvious validation (type-check, tests) "
                "before reporting done. Do not refactor unrelated code."
            ),
            tools=["Read", "Write", "Edit", "Glob", "Grep", "Bash"],
            model="opus",
        ),
        "memory-curator": AgentDefinition(
            description=(
                "Periodic memory housekeeping. Reads the latest session messages, "
                "extracts durable facts about the user, dedupes against existing "
                "facts, and updates the user profile. Triggered by hooks, not user prompts."
            ),
            prompt=(
                "You curate long-term memory. Use mcp__aether__list_facts first to see "
                "what is already known. Use mcp__aether__remember only for genuinely new, "
                "durable information (preferences, biographical, project context). "
                "Use mcp__aether__update_user_profile to keep the rolling summary fresh. "
                "Be conservative — false memories are worse than missing memories."
            ),
            tools=[
                "mcp__aether__list_facts",
                "mcp__aether__remember",
                "mcp__aether__forget",
                "mcp__aether__update_user_profile",
                "mcp__aether__recall",
            ],
            model="sonnet",
        ),
        "skill-evolver": AgentDefinition(
            description=(
                "Reviews how an existing skill performed in the latest session and "
                "proposes improvements. Edits SKILL.md files. Triggered by the "
                "self-evolution loop after a skill has been used several times."
            ),
            prompt=(
                "You evolve agent skills. Read the target skill with mcp__aether__list_skills "
                "and the underlying SKILL.md file. Look at recent uses of the skill in "
                "session transcripts. Propose a focused edit that addresses an observed "
                "failure mode or makes the skill more reliable. Keep skills under 15KB. "
                "Use mcp__aether__edit_skill to apply the change. Bump the patch version. "
                "Preserve the original purpose — never broaden scope."
            ),
            tools=[
                "Read",
                "Glob",
                "mcp__aether__list_skills",
                "mcp__aether__edit_skill",
                "mcp__aether__recall",
            ],
            model="opus",
        ),
        "scheduler-runner": AgentDefinition(
            description=(
                "Internal: executes a scheduled prompt and returns the response text. "
                "Not for direct user delegation."
            ),
            prompt=(
                "You execute a scheduled task. Run the prompt the user originally gave "
                "you to schedule. Be concise — the result will be delivered to a chat "
                "platform with limited message size."
            ),
            tools=["Read", "Glob", "Grep", "WebFetch", "WebSearch", "Bash"],
            model="sonnet",
        ),
    }
