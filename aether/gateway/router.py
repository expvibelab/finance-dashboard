"""Router: shared agent instance, dispatches to platform adapters.

Adapters subscribe to a per-message StreamBroadcaster so they can render
tool-call updates live (Telegram editing the bot's own message, Discord
typing indicators, the CLI printing dimmed lines, etc.).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from aether.core import Agent, AgentResponse
from aether.streaming import StreamBroadcaster

log = logging.getLogger("aether.gateway")


@dataclass
class IncomingMessage:
    user_id: str
    source: str  # "telegram" | "discord" | "cli"
    text: str
    chat_id: str | None = None


class GatewayRouter:
    def __init__(self, agent: Agent):
        self.agent = agent

    async def dispatch(
        self,
        msg: IncomingMessage,
        *,
        broadcaster: StreamBroadcaster | None = None,
    ) -> AgentResponse:
        broadcaster = broadcaster or StreamBroadcaster()
        return await self.agent.run_turn(
            prompt=msg.text,
            user_id=msg.user_id,
            source=msg.source,
            broadcaster=broadcaster,
        )

    async def dispatch_with_streaming(
        self,
        msg: IncomingMessage,
        consumer,
    ) -> AgentResponse:
        """Run a turn and forward every stream event to `consumer(event)`.

        `consumer` is an async callable that handles each StreamEvent. Returns
        the final AgentResponse once the turn completes.
        """
        broadcaster = StreamBroadcaster()

        async def listen() -> None:
            async for event in broadcaster.listen():
                try:
                    await consumer(event)
                except Exception as e:  # noqa: BLE001
                    log.warning("consumer raised: %s", e)

        listener = asyncio.create_task(listen())
        try:
            response = await self.agent.run_turn(
                prompt=msg.text,
                user_id=msg.user_id,
                source=msg.source,
                broadcaster=broadcaster,
            )
        finally:
            await listener
        return response
