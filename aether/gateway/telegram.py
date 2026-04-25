"""Telegram gateway. Edits a single status message live as the agent runs.

The bot:
- Accepts text, voice (optional whisper), and replies in markdown.
- Streams "🔧 calling tool: X" updates by editing its placeholder reply.
- Honours TELEGRAM_ALLOWED_USERS as a chat-id allowlist.
- Forwards scheduled job output via send_status_message().
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from aether.config import Settings
from aether.core import Agent
from aether.gateway.router import GatewayRouter, IncomingMessage
from aether.streaming import StreamEvent

log = logging.getLogger("aether.telegram")

MAX_TG_MESSAGE = 4000  # Telegram caps at 4096; keep slack for footers.
ACTIVITY_TICK_LIMIT = 25  # Telegram rate-limits message edits at ~30/min.


def build_application(agent: Agent, settings: Settings) -> Application:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required for the Telegram gateway")

    app = Application.builder().token(settings.telegram_bot_token).build()
    router = GatewayRouter(agent)
    allowed = settings.allowed_telegram_users
    app.bot_data["agent"] = agent
    app.bot_data["router"] = router
    app.bot_data["allowed"] = allowed

    app.add_handler(CommandHandler("start", _cmd_start))
    app.add_handler(CommandHandler("new", _cmd_new))
    app.add_handler(CommandHandler("reset", _cmd_new))
    app.add_handler(CommandHandler("skills", _cmd_skills))
    app.add_handler(CommandHandler("memory", _cmd_memory))
    app.add_handler(CommandHandler("status", _cmd_status))
    app.add_handler(CommandHandler("schedules", _cmd_schedules))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_text))
    return app


async def _cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Aether online. Talk to me normally; use /new to reset, /skills to list skills, "
        "/memory to see what I remember about you."
    )


async def _cmd_new(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update, ctx):
        return
    agent: Agent = ctx.bot_data["agent"]
    user_id = str(update.effective_user.id)
    await agent.reset_session(user_id, "telegram")
    await update.message.reply_text("Session reset.")


async def _cmd_skills(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update, ctx):
        return
    agent: Agent = ctx.bot_data["agent"]
    skills = agent.skills.list_skills()
    if not skills:
        await update.message.reply_text("(no skills installed yet)")
        return
    lines = [f"• *{s.name}* v{s.version} — {s.description}" for s in skills]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def _cmd_memory(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update, ctx):
        return
    agent: Agent = ctx.bot_data["agent"]
    user_id = str(update.effective_user.id)
    facts = await agent.memory.list_facts(user_id)
    if not facts:
        await update.message.reply_text("(no facts recorded)")
        return
    lines = []
    for f in facts:
        cat = f"[{f.category}] " if f.category else ""
        lines.append(f"• {cat}{f.fact}")
    await update.message.reply_text("\n".join(lines)[:MAX_TG_MESSAGE])


async def _cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update, ctx):
        return
    agent: Agent = ctx.bot_data["agent"]
    user_id = str(update.effective_user.id)
    sess = await agent.memory.latest_session_for_user(user_id, "telegram")
    if not sess:
        await update.message.reply_text("(no active session)")
        return
    await update.message.reply_text(
        f"session `{sess.id[:8]}` · messages: {sess.message_count}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def _cmd_schedules(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update, ctx):
        return
    agent: Agent = ctx.bot_data["agent"]
    user_id = str(update.effective_user.id)
    rows = await agent.memory.list_schedules(user_id=user_id)
    if not rows:
        await update.message.reply_text("(no schedules)")
        return
    lines = [
        f"• `{r['id'][:8]}` `{r['cron']}` → {r['deliver_to']}: {r['prompt'][:60]}"
        for r in rows
    ]
    await update.message.reply_text(
        "\n".join(lines)[:MAX_TG_MESSAGE], parse_mode=ParseMode.MARKDOWN
    )


async def _handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update, ctx):
        return
    router: GatewayRouter = ctx.bot_data["router"]
    user_id = str(update.effective_user.id)
    chat = update.effective_chat
    placeholder = await update.message.reply_text("…thinking")

    activity: list[str] = []
    edits = 0

    async def consume(event: StreamEvent) -> None:
        nonlocal edits
        if event.kind in {"tool_call", "subagent"}:
            activity.append(event.render(compact=True))
            if edits < ACTIVITY_TICK_LIMIT:
                edits += 1
                try:
                    text = "\n".join(activity[-6:])
                    await placeholder.edit_text(
                        text[:MAX_TG_MESSAGE] or "…thinking",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                except Exception as e:  # noqa: BLE001
                    log.debug("edit failed: %s", e)
        elif event.kind == "error":
            try:
                await placeholder.edit_text(f"⚠️ {event.text}")
            except Exception:
                pass

    try:
        await chat.send_chat_action(action=ChatAction.TYPING)
        response = await router.dispatch_with_streaming(
            IncomingMessage(
                user_id=user_id,
                source="telegram",
                text=update.message.text,
                chat_id=str(chat.id),
            ),
            consume,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("telegram turn failed")
        try:
            await placeholder.edit_text(f"⚠️ error: {e}")
        except Exception:
            pass
        return

    final = response.text or "(no reply)"
    chunks = _split_for_telegram(final)
    for i, chunk in enumerate(chunks):
        try:
            if i == 0:
                await placeholder.edit_text(chunk, parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            # Markdown parse failures fall back to plain text.
            await update.message.reply_text(chunk)


def _allowed(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    allowed = ctx.bot_data.get("allowed") or set()
    if not allowed:
        return True
    return update.effective_user and update.effective_user.id in allowed


def _split_for_telegram(text: str) -> list[str]:
    if len(text) <= MAX_TG_MESSAGE:
        return [text]
    out: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= MAX_TG_MESSAGE:
            out.append(remaining)
            break
        cut = remaining.rfind("\n", 0, MAX_TG_MESSAGE)
        if cut <= 0:
            cut = MAX_TG_MESSAGE
        out.append(remaining[:cut])
        remaining = remaining[cut:]
    return out


async def send_status_message(
    app: Application, chat_id: int | str, text: str
) -> None:
    """Used by the scheduler to deliver scheduled output to a Telegram chat."""
    for chunk in _split_for_telegram(text):
        await app.bot.send_message(chat_id=chat_id, text=chunk)
