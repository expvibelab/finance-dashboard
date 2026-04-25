"""Discord gateway. Mirrors Telegram's behaviour: status-message editing, allowlist.

Implemented with discord.py 2.x message intents. Reacts to mentions in servers
and any DM. Slash commands are kept as text commands (`!new`, `!skills`, …)
to avoid the per-guild registration step on first deploy.
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from aether.config import Settings
from aether.core import Agent
from aether.gateway.router import GatewayRouter, IncomingMessage
from aether.streaming import StreamEvent

log = logging.getLogger("aether.discord")
MAX_DC_MESSAGE = 1900  # Discord 2000-char cap with safety margin.


def build_bot(agent: Agent, settings: Settings) -> commands.Bot:
    if not settings.discord_bot_token:
        raise RuntimeError("DISCORD_BOT_TOKEN is required for the Discord gateway")
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents)

    router = GatewayRouter(agent)
    allowed = settings.allowed_discord_users

    @bot.event
    async def on_ready() -> None:
        log.info("Discord ready as %s", bot.user)

    @bot.command(name="new")
    async def new(ctx: commands.Context) -> None:
        if allowed and ctx.author.id not in allowed:
            return
        await agent.reset_session(str(ctx.author.id), "discord")
        await ctx.reply("Session reset.")

    @bot.command(name="skills")
    async def skills(ctx: commands.Context) -> None:
        if allowed and ctx.author.id not in allowed:
            return
        items = agent.skills.list_skills()
        if not items:
            await ctx.reply("(no skills installed)")
            return
        lines = [f"• **{s.name}** v{s.version} — {s.description}" for s in items]
        await ctx.reply("\n".join(lines)[:MAX_DC_MESSAGE])

    @bot.command(name="memory")
    async def memory(ctx: commands.Context) -> None:
        if allowed and ctx.author.id not in allowed:
            return
        facts = await agent.memory.list_facts(str(ctx.author.id))
        if not facts:
            await ctx.reply("(no facts recorded)")
            return
        lines = [f"• {f.fact}" for f in facts]
        await ctx.reply("\n".join(lines)[:MAX_DC_MESSAGE])

    @bot.event
    async def on_message(message: discord.Message) -> None:
        if message.author.bot:
            return
        if allowed and message.author.id not in allowed:
            return
        # Process commands first.
        if message.content.startswith("!"):
            await bot.process_commands(message)
            return
        # Only respond to DMs or @mentions.
        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mention = bot.user in message.mentions
        if not (is_dm or is_mention):
            return

        prompt = message.content
        if is_mention:
            prompt = prompt.replace(f"<@{bot.user.id}>", "").strip()

        placeholder = await message.reply("…thinking")
        activity: list[str] = []
        edits = 0

        async def consume(event: StreamEvent) -> None:
            nonlocal edits
            if event.kind in {"tool_call", "subagent"} and edits < 25:
                activity.append(event.render())
                edits += 1
                try:
                    await placeholder.edit(content="\n".join(activity[-6:])[:MAX_DC_MESSAGE])
                except Exception:
                    pass

        try:
            response = await router.dispatch_with_streaming(
                IncomingMessage(
                    user_id=str(message.author.id),
                    source="discord",
                    text=prompt,
                    chat_id=str(message.channel.id),
                ),
                consume,
            )
        except Exception as e:  # noqa: BLE001
            try:
                await placeholder.edit(content=f"⚠️ error: {e}")
            except Exception:
                pass
            return

        final = response.text or "(no reply)"
        chunks = _chunk(final)
        try:
            await placeholder.edit(content=chunks[0][:MAX_DC_MESSAGE])
        except Exception:
            pass
        for c in chunks[1:]:
            await message.channel.send(c[:MAX_DC_MESSAGE])

    return bot


def _chunk(text: str) -> list[str]:
    if len(text) <= MAX_DC_MESSAGE:
        return [text]
    out: list[str] = []
    rem = text
    while rem:
        if len(rem) <= MAX_DC_MESSAGE:
            out.append(rem)
            break
        cut = rem.rfind("\n", 0, MAX_DC_MESSAGE)
        if cut <= 0:
            cut = MAX_DC_MESSAGE
        out.append(rem[:cut])
        rem = rem[cut:]
    return out
