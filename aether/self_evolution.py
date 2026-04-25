"""Self-evolution loop: dispatches the skill-evolver subagent against frequently used skills.

This module runs on a slow cadence (default: every hour). It picks a candidate
skill that has been used at least `evolve_min_uses` times, then asks the
skill-evolver subagent to inspect its recent uses and propose an edit. The
subagent applies the edit via `mcp__aether__edit_skill`, which writes a
new SKILL.md file and bumps the patch version.

Quality gates (mirroring Hermes' approach):
- Skills capped at 15KB (enforced by SkillRegistry.update).
- Original purpose preserved: we instruct the subagent explicitly.
- A pre-edit and post-edit diff is logged so a human can audit changes.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aether.core import Agent
from aether.streaming import StreamBroadcaster

log = logging.getLogger("aether.evolution")


class SelfEvolution:
    def __init__(self, agent: Agent, *, interval_seconds: int = 3600) -> None:
        self.agent = agent
        self.interval = interval_seconds
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="aether-evolution")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def _loop(self) -> None:
        await self.agent.initialize()
        while True:
            try:
                await asyncio.sleep(self.interval)
                if not self.agent.settings.evolve_enabled:
                    continue
                await self.run_once()
            except asyncio.CancelledError:
                return
            except Exception as e:  # noqa: BLE001
                log.exception("evolution cycle failed: %s", e)

    async def run_once(self) -> dict[str, Any] | None:
        stats = await self.agent.memory.skill_use_stats()
        threshold = self.agent.settings.evolve_min_uses
        candidates = [s for s in stats if s["uses"] >= threshold]
        if not candidates:
            return None
        # Pick the skill with the lowest success rate among those over threshold.
        candidates.sort(key=lambda s: (s["successes"] or 0) / max(s["uses"], 1))
        target = candidates[0]
        slug = target["skill_name"]
        log.info("evolving skill: %s (uses=%d)", slug, target["uses"])

        prompt = (
            f"Review the skill `{slug}`. It has been used {target['uses']} times "
            f"with {target['successes'] or 0} successes. Inspect recent transcripts "
            "via mcp__aether__recall, identify a concrete failure mode, and apply "
            "a focused improvement using mcp__aether__edit_skill. Preserve scope. "
            "Bump the patch version. Keep it under 15KB."
        )

        response = await self.agent.run_turn(
            prompt=prompt,
            user_id="aether-evolution",
            source="evolution",
            broadcaster=StreamBroadcaster(),
        )
        return {"skill": slug, "report": response.text}
