---
name: Schedule Recurring Task
description: Use when the user asks for a reminder, a daily/weekly digest, a recurring report, or any task phrased like "every X". Creates a cron schedule via mcp__aether__schedule and confirms it back in plain English.
version: 0.1.0
---

# Schedule Recurring Task

## Trigger phrases
- "remind me to …"
- "every morning …", "every Monday …", "weekly …"
- "send me a daily summary of …"
- "check on X every hour"

## Procedure

1. Translate the cadence to a 5-field cron expression. Use the user's local
   schedule unless they specify UTC. Examples:
   - daily 9am: `0 9 * * *`
   - hourly: `0 * * * *`
   - Mondays at 8am: `0 8 * * 1`
2. Choose `deliver_to`. Default to the platform you're talking on
   (`telegram`, `discord`, `cli`). Use `none` for silent jobs whose results
   only update memory.
3. Compose the **prompt** as if it were a fresh user request. The scheduled
   run starts a clean session, so the prompt must be self-contained:
   include all parameters the future you will need.
4. Call `mcp__aether__schedule` with `cron`, `prompt`, `deliver_to`.
5. Confirm in one sentence: "Scheduled — every weekday at 9am I'll send the
   digest. Cancel with `/schedules` and the id."

## Cancel & list
- `mcp__aether__list_schedules` — show all active jobs for the current user.
- `mcp__aether__cancel_schedule` — disable by id (short prefix works).
