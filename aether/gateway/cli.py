"""Interactive REPL gateway. Renders tool calls inline as the agent works."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel

from aether.core import Agent
from aether.gateway.router import GatewayRouter, IncomingMessage
from aether.streaming import StreamEvent

console = Console()


SLASH_COMMANDS = {
    "/new": "Start a fresh session.",
    "/reset": "Same as /new.",
    "/skills": "List installed skills.",
    "/memory": "List facts the agent remembers about you.",
    "/status": "Show the current session info.",
    "/help": "Show this help.",
    "/quit": "Exit.",
}


async def run_cli(agent: Agent, user_id: str = "local") -> None:
    router = GatewayRouter(agent)
    console.print(
        Panel.fit(
            "[bold cyan]Aether[/] — type [bold]/help[/] for commands, [bold]/quit[/] to exit.",
            border_style="cyan",
        )
    )

    while True:
        try:
            line = await asyncio.to_thread(_read_input)
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]bye.[/]")
            return

        line = line.strip()
        if not line:
            continue

        if line.startswith("/"):
            cmd = line.split()[0]
            if cmd in {"/quit", "/exit"}:
                return
            if cmd == "/help":
                _print_help()
                continue
            if cmd in {"/new", "/reset"}:
                await agent.reset_session(user_id, "cli")
                console.print("[green]Session reset.[/]")
                continue
            if cmd == "/skills":
                for s in agent.skills.list_skills():
                    console.print(f"  [bold]{s.slug}[/] v{s.version} — {s.description}")
                continue
            if cmd == "/memory":
                facts = await agent.memory.list_facts(user_id)
                if not facts:
                    console.print("[dim](no facts)[/]")
                for f in facts:
                    cat = f"[{f.category}] " if f.category else ""
                    console.print(f"  • {cat}{f.fact}")
                continue
            if cmd == "/status":
                sess = await agent.memory.latest_session_for_user(user_id, "cli")
                if sess:
                    console.print(
                        f"session={sess.id[:8]} messages={sess.message_count}"
                    )
                else:
                    console.print("[dim](no active session)[/]")
                continue
            console.print(f"[red]unknown command: {cmd}[/]")
            continue

        await _run_with_live_output(router, line, user_id)


async def _run_with_live_output(
    router: GatewayRouter, prompt: str, user_id: str
) -> None:
    msg = IncomingMessage(user_id=user_id, source="cli", text=prompt)
    activity_lines: list[str] = []

    async def consume(event: StreamEvent) -> None:
        if event.kind == "tool_call":
            activity_lines.append(f"[dim]→ {event.render()}[/dim]")
            console.print(activity_lines[-1])
        elif event.kind == "subagent":
            console.print(f"[magenta]{event.render()}[/magenta]")
        elif event.kind == "error":
            console.print(f"[red]{event.render()}[/red]")

    response = await router.dispatch_with_streaming(msg, consume)
    if response.text:
        console.print(Markdown(response.text))
    if response.cost_usd:
        console.print(
            f"[dim]cost ${response.cost_usd:.4f} · "
            f"in {response.input_tokens} / out {response.output_tokens} tokens[/]"
        )


def _read_input() -> str:
    sys.stdout.write("\n› ")
    sys.stdout.flush()
    return sys.stdin.readline()


def _print_help() -> None:
    for cmd, desc in SLASH_COMMANDS.items():
        console.print(f"  [bold]{cmd}[/] — {desc}")
