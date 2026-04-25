"""Cron scheduler — drives recurring agent prompts and delivers results to platforms.

Persistence is in SQLite (the `schedules` table). On startup we reload every
enabled schedule, plug it into APScheduler, and on each tick run a fresh agent
turn whose response is forwarded to the appropriate adapter.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Awaitable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from aether.core import Agent
from aether.streaming import StreamBroadcaster

log = logging.getLogger("aether.scheduler")

DeliveryFn = Callable[[str, str, str], Awaitable[None]]
"""(deliver_to, user_id, text) -> None"""


class AetherScheduler:
    def __init__(
        self,
        agent: Agent,
        delivery_fn: DeliveryFn | None = None,
    ) -> None:
        self.agent = agent
        self._scheduler = AsyncIOScheduler()
        self._delivery_fn = delivery_fn or _default_delivery

    async def start(self) -> None:
        await self.agent.initialize()
        rows = await self.agent.memory.list_schedules(only_enabled=True)
        for r in rows:
            self._add_job(r)
        self._scheduler.start()
        log.info("scheduler started with %d job(s)", len(rows))

    async def reload(self) -> None:
        for j in self._scheduler.get_jobs():
            j.remove()
        rows = await self.agent.memory.list_schedules(only_enabled=True)
        for r in rows:
            self._add_job(r)

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)

    def _add_job(self, row: dict[str, Any]) -> None:
        try:
            trigger = CronTrigger.from_crontab(row["cron"])
        except ValueError as e:
            log.warning("invalid cron for %s: %s", row["id"], e)
            return
        self._scheduler.add_job(
            self._run_job,
            trigger=trigger,
            id=row["id"],
            args=[row],
            replace_existing=True,
        )

    async def _run_job(self, row: dict[str, Any]) -> None:
        log.info("running schedule %s", row["id"][:8])
        try:
            user_id = row.get("user_id") or "scheduler"
            response = await self.agent.run_turn(
                prompt=row["prompt"],
                user_id=user_id,
                source=f"schedule:{row['deliver_to']}",
                broadcaster=StreamBroadcaster(),
            )
            await self.agent.memory.mark_schedule_run(row["id"], status="ok")
            if row["deliver_to"] != "none":
                await self._delivery_fn(row["deliver_to"], user_id, response.text or "(no output)")
        except Exception as e:  # noqa: BLE001
            log.exception("schedule %s failed: %s", row["id"][:8], e)
            await self.agent.memory.mark_schedule_run(row["id"], status=f"error:{e}")


async def _default_delivery(deliver_to: str, user_id: str, text: str) -> None:
    log.info("[%s → %s] %s", deliver_to, user_id, text[:200])
