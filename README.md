# Aether

A self-evolving multi-platform agent built on the **Claude Agent SDK**.
Hermes-equivalent feature set: persistent memory across sessions, skills the
agent reads/creates/evolves, parallel subagent delegation, multi-platform
gateway (CLI + Telegram + Discord), cron scheduling with cross-platform
delivery, and a post-session self-evolution loop.

One process, one human, many platforms, one continuous relationship.

## Feature map (Hermes ↔ Aether)

| Hermes Agent | Aether |
|---|---|
| Agent-curated memory + nudges | `aether/memory.py` `facts` table + `MEMORY.md` curation |
| FTS5 cross-session recall | `MemoryStore.search_messages` (SQLite FTS5 virtual table) |
| Honcho dialectic user modeling | `user_models` table + `update_user_profile` tool |
| Skills (autonomous creation, self-improvement) | `aether/skills.py` + `mcp__aether__create_skill` / `edit_skill` |
| `agentskills.io` standard (SKILL.md frontmatter) | Same — see `.claude/skills/*/SKILL.md` |
| Subagents (isolated, parallel) | `aether/subagents.py` + filesystem `.claude/agents/*.md` |
| Gateway (Telegram, Discord, …) | `aether/gateway/{cli,telegram,discord}.py` |
| Tool streaming to chat platforms | `aether/streaming.py` + per-platform live edits |
| Built-in cron scheduler | `aether/scheduler.py` (APScheduler + croniter) |
| Self-evolution (DSPy + GEPA) | `aether/self_evolution.py` (subagent-driven, gates: 15KB cap, version bumps) |
| MCP server integration | Built on the SDK's first-class MCP support |

## Quick deploy on a VPS

```bash
# 1. Clone
git clone https://github.com/expvibelab/finance-dashboard.git aether
cd aether

# 2. Configure
cp .env.example .env
$EDITOR .env   # set ANTHROPIC_API_KEY and at least one platform token

# 3. Run
docker compose up -d
docker compose logs -f
```

## Required env vars

```
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=...           # optional
TELEGRAM_ALLOWED_USERS=12345,67  # comma-separated chat IDs
DISCORD_BOT_TOKEN=...            # optional
```

See `.env.example` for the full list.

## Running locally without Docker

```bash
pip install -e .
cp .env.example .env
$EDITOR .env

# Pick one
aether chat              # interactive REPL
aether telegram          # Telegram bot
aether discord           # Discord bot
aether all               # every configured gateway concurrently
aether evolve            # one self-evolution pass, then exit
```

## Architecture

```
┌─────────────┐  ┌──────────┐  ┌─────────┐
│ Telegram    │  │ Discord  │  │  CLI    │   gateways stream tool calls
└──────┬──────┘  └─────┬────┘  └────┬────┘   live to each platform
       │               │            │
       └───────────────┼────────────┘
                       │
                ┌──────▼──────┐
                │   Router    │
                └──────┬──────┘
                       │
                ┌──────▼──────────────────────────────┐
                │ Agent Core                          │
                │  • ClaudeSDKClient (Claude Agent SDK)│
                │  • System prompt = CLAUDE.md +      │
                │    MEMORY.md + per-user facts +     │
                │    user model                       │
                │  • Hooks: PreTool/PostTool stream   │
                │    every action to subscribers      │
                └──┬───────────┬─────────────┬────────┘
                   │           │             │
            ┌──────▼─────┐ ┌──▼──────┐ ┌─────▼─────┐
            │  Memory    │ │ Skills  │ │ Subagents │
            │ (SQLite +  │ │ (.claude│ │ (.claude/ │
            │   FTS5)    │ │ /skills)│ │  agents)  │
            └────────────┘ └─────────┘ └───────────┘
                   ▲                         ▲
                   │                         │
            ┌──────┴───────┐         ┌───────┴────────┐
            │ Cron         │         │ Self-Evolution │
            │ Scheduler    │         │ Loop (hourly)  │
            └──────────────┘         └────────────────┘
```

## How "self-evolving" actually works

1. Every tool call is recorded in SQLite (`messages.tool_calls`).
2. Every skill invocation goes through the `Skill` tool; we increment
   `skill_uses` per slug.
3. A background `SelfEvolution` task runs hourly. It picks the lowest
   success-rate skill that's been used `>= AETHER_EVOLVE_MIN_USES` times.
4. It dispatches the `skill-evolver` subagent against that skill. The
   subagent reads recent transcripts via `recall`, identifies one failure
   mode, and edits the SKILL.md via `mcp__aether__edit_skill`.
5. The registry validates: ≤15KB, frontmatter intact, version bumped.
6. Next time the skill triggers, it's the new version.

## How "never forgets" actually works

- Every user message and assistant reply is persisted to `messages`.
- The `messages_fts` virtual table indexes content for sub-second recall.
- `mcp__aether__recall` is exposed to the agent. The system prompt in
  `CLAUDE.md` tells it to recall before answering anything contextual.
- Curated facts (high-signal extracts) are stored in `facts` and injected
  into the system prompt every turn.
- A rolling user-model summary lives in `user_models` and is also injected.

## Skills it ships with

| Slug | Trigger |
|---|---|
| `recall-before-answering` | User references prior context |
| `capture-durable-fact` | User shares a stable preference / decision |
| `create-new-skill` | After completing a generalisable task |
| `delegate-to-subagent` | When work splits cleanly into a subtask |
| `schedule-recurring-task` | "Remind me to / every X" requests |

## Subagents it ships with

| Name | Use |
|---|---|
| `researcher` | Read-only investigation |
| `coder` | Bounded code edits |
| `memory-curator` | Periodic memory housekeeping |
| `skill-evolver` | Drives the self-evolution loop |
| `scheduler-runner` | Internal — runs scheduled prompts |

## Tools the agent has on top of the standard SDK toolkit

All under the `mcp__aether__` namespace:

- `remember`, `recall`, `forget`, `list_facts`, `update_user_profile`
- `create_skill`, `edit_skill`, `list_skills`, `delete_skill`
- `schedule`, `list_schedules`, `cancel_schedule`

## Slash commands (CLI gateway)

`/new`, `/reset`, `/skills`, `/memory`, `/status`, `/help`, `/quit`

## Tests

```bash
pip install -e ".[dev]"
pytest -q
```

## Roadmap

The shipped feature set is a 1:1 functional match for the headline Hermes
capabilities. Upcoming polish:

- Voice transcription pre-stage (Whisper) for Telegram voice notes.
- Slack & WhatsApp adapters using the same router.
- Per-user model selection via `/model`.
- DSPy-based skill optimisation as an opt-in alternative to the subagent loop.
