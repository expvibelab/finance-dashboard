---
name: Delegate To Subagent
description: Use when a task naturally splits into a focused subtask that can be handed off in one prompt. Especially for open-ended research (use researcher) or focused code changes with clear specs (use coder). Avoids polluting the main context with intermediate exploration.
version: 0.1.0
---

# Delegate To Subagent

## When to delegate
- Research that will read 5+ pages of context the parent doesn't need to retain.
- A bounded code change with a clear acceptance criterion.
- Parallelizable workstreams (kick off two delegates concurrently).

## When NOT to delegate
- The task hinges on conversation context the subagent won't have.
- The work is small enough that delegation overhead exceeds the win.
- You'd want to iterate with the user mid-task.

## Procedure

1. Choose the subagent: `researcher` (read-only investigation), `coder`
   (writes code), or define a one-off via the `Agent` tool.
2. Write a self-contained prompt. The subagent has no memory of this
   conversation — include all relevant facts, file paths, constraints.
3. State the expected output format ("under 200 words", "as a JSON object",
   "as a unified diff").
4. Invoke via the `Agent` tool with `subagent_type` set.
5. After it returns, summarise the result in your own voice — don't just paste.

## Parallelism

If two pieces of work are independent, dispatch both subagents in a single
turn (multiple `Agent` tool calls in one message). They'll run concurrently.

## Common mistakes

- Vague prompts produce vague results. Be specific.
- Forgetting to mention file paths the subagent needs to read.
- Using a delegate when the parent could just call the underlying tool directly.
