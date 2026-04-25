"""Aether CLI — entrypoints for chat REPL, Telegram bot, Discord bot, scheduler."""

from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path

import typer
from rich.console import Console

from aether.config import get_settings
from aether.core import Agent
from aether.gateway.cli import run_cli
from aether.scheduler import AetherScheduler
from aether.self_evolution import SelfEvolution

app = typer.Typer(help="Aether — self-evolving multi-platform agent")
console = Console()


def _setup_logging() -> None:
    s = get_settings()
    logging.basicConfig(
        level=getattr(logging, s.log_level.upper(), logging.INFO),
        format="%(asctime)s · %(name)s · %(levelname)s · %(message)s",
    )


@app.command("chat")
def chat_cmd(
    user_id: str = typer.Option("local", help="User identifier for the CLI session"),
    project: Path = typer.Option(Path.cwd(), help="Project workspace path"),
) -> None:
    """Interactive REPL gateway."""
    _setup_logging()
    agent = Agent(project_root=project)

    async def main() -> None:
        await agent.initialize()
        await run_cli(agent, user_id=user_id)

    asyncio.run(main())


@app.command("telegram")
def telegram_cmd(
    project: Path = typer.Option(Path.cwd(), help="Project workspace path"),
) -> None:
    """Run the Telegram gateway as a long-lived process."""
    _setup_logging()
    settings = get_settings()
    agent = Agent(settings=settings, project_root=project)

    from aether.gateway.telegram import build_application

    async def main() -> None:
        await agent.initialize()
        application = build_application(agent, settings)
        scheduler = AetherScheduler(
            agent,
            delivery_fn=_telegram_delivery_factory(application),
        )
        evo = SelfEvolution(agent)

        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        await scheduler.start()
        evo.start()

        console.print("[green]Aether (Telegram) is up.[/]")
        try:
            await asyncio.Event().wait()
        finally:
            evo and await evo.stop()
            scheduler.shutdown()
            await application.updater.stop()
            await application.stop()
            await application.shutdown()

    asyncio.run(main())


@app.command("discord")
def discord_cmd(
    project: Path = typer.Option(Path.cwd(), help="Project workspace path"),
) -> None:
    """Run the Discord gateway."""
    _setup_logging()
    settings = get_settings()
    agent = Agent(settings=settings, project_root=project)

    from aether.gateway.discord import build_bot

    async def main() -> None:
        await agent.initialize()
        bot = build_bot(agent, settings)
        scheduler = AetherScheduler(agent)
        evo = SelfEvolution(agent)

        await scheduler.start()
        evo.start()
        try:
            await bot.start(settings.discord_bot_token)
        finally:
            scheduler.shutdown()
            await evo.stop()

    asyncio.run(main())


@app.command("all")
def all_cmd(
    project: Path = typer.Option(Path.cwd(), help="Project workspace path"),
) -> None:
    """Run every configured gateway concurrently."""
    _setup_logging()
    settings = get_settings()
    agent = Agent(settings=settings, project_root=project)

    async def main() -> None:
        await agent.initialize()
        tasks: list[asyncio.Task] = []
        scheduler = AetherScheduler(agent)
        evo = SelfEvolution(agent)
        await scheduler.start()
        evo.start()

        if settings.telegram_bot_token:
            from aether.gateway.telegram import build_application

            telegram_app = build_application(agent, settings)
            await telegram_app.initialize()
            await telegram_app.start()
            await telegram_app.updater.start_polling()
            console.print("[green]Telegram gateway up.[/]")
            scheduler._delivery_fn = _telegram_delivery_factory(telegram_app)

        if settings.discord_bot_token:
            from aether.gateway.discord import build_bot

            bot = build_bot(agent, settings)
            tasks.append(asyncio.create_task(bot.start(settings.discord_bot_token)))
            console.print("[green]Discord gateway up.[/]")

        if not tasks:
            console.print("[yellow]No platforms configured. Configure TELEGRAM_BOT_TOKEN or DISCORD_BOT_TOKEN.[/]")
            return

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                pass
        await stop_event.wait()

        scheduler.shutdown()
        await evo.stop()
        for t in tasks:
            t.cancel()

    asyncio.run(main())


@app.command("evolve")
def evolve_cmd(
    project: Path = typer.Option(Path.cwd()),
) -> None:
    """Run a single self-evolution cycle and exit."""
    _setup_logging()
    agent = Agent(project_root=project)

    async def main() -> None:
        await agent.initialize()
        evo = SelfEvolution(agent)
        result = await evo.run_once()
        if result is None:
            console.print("[yellow]No skills meet the evolution threshold yet.[/]")
        else:
            console.print(f"[green]Evolved {result['skill']}.[/]")
            console.print(result["report"])

    asyncio.run(main())


def _telegram_delivery_factory(application):
    """Return a delivery function bound to the running Telegram application."""
    from aether.gateway.telegram import send_status_message

    async def deliver(deliver_to: str, user_id: str, text: str) -> None:
        if deliver_to != "telegram":
            return
        try:
            chat_id = int(user_id)
        except ValueError:
            return
        await send_status_message(application, chat_id, text)

    return deliver


if __name__ == "__main__":
    app()
