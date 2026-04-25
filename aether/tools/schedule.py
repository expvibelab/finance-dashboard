"""Schedule tools: agent creates cron jobs that re-prompt itself and deliver to platforms."""

from __future__ import annotations

from typing import Any, Callable

from claude_agent_sdk import tool
from croniter import croniter

from aether.memory import MemoryStore


def build_schedule_tools(store: MemoryStore, user_id_provider: Callable[[], str]):
    @tool(
        "schedule",
        "Schedule a recurring prompt for yourself. The agent will run with the given "
        "prompt at every cron tick and deliver the response to the named platform. "
        "`cron` accepts standard 5-field cron syntax. `deliver_to` is one of: "
        "telegram, discord, cli, none.",
        {"cron": str, "prompt": str, "deliver_to": str},
    )
    async def schedule(args: dict[str, Any]) -> dict[str, Any]:
        cron = (args.get("cron") or "").strip()
        prompt = (args.get("prompt") or "").strip()
        deliver_to = (args.get("deliver_to") or "cli").strip().lower()
        if not cron or not prompt:
            return _err("`cron` and `prompt` are required")
        if not croniter.is_valid(cron):
            return _err(f"Invalid cron expression: {cron}")
        if deliver_to not in {"telegram", "discord", "cli", "none"}:
            return _err("deliver_to must be telegram, discord, cli, or none")
        sid = await store.add_schedule(
            cron=cron, prompt=prompt, deliver_to=deliver_to, user_id=user_id_provider()
        )
        return _ok(f"Scheduled `{sid}`: `{cron}` → {deliver_to}")

    @tool(
        "list_schedules",
        "List active scheduled jobs for the current user.",
        {},
    )
    async def list_schedules(_: dict[str, Any]) -> dict[str, Any]:
        rows = await store.list_schedules(user_id=user_id_provider())
        if not rows:
            return _ok("(no schedules)")
        lines = []
        for r in rows:
            lines.append(
                f"- `{r['id'][:8]}` {r['cron']} → {r['deliver_to']}: {r['prompt'][:80]}"
            )
        return _ok("\n".join(lines))

    @tool(
        "cancel_schedule",
        "Cancel a scheduled job by id (the short id from list_schedules works).",
        {"schedule_id": str},
    )
    async def cancel_schedule(args: dict[str, Any]) -> dict[str, Any]:
        sid = (args.get("schedule_id") or "").strip()
        if not sid:
            return _err("`schedule_id` is required")
        # Allow short prefix.
        rows = await store.list_schedules(user_id=user_id_provider())
        match = next((r for r in rows if r["id"].startswith(sid)), None)
        if match is None:
            return _err("Schedule not found")
        await store.remove_schedule(match["id"])
        return _ok(f"Cancelled `{match['id']}`.")

    return [schedule, list_schedules, cancel_schedule]


def _ok(msg: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": msg}]}


def _err(msg: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": msg}], "is_error": True}
