---
name: Capture Durable Fact
description: Use when the user shares a stable preference, a biographical detail, a project context, a naming convention, or a decision they expect you to remember. Persists the fact via mcp__aether__remember so it's available in future sessions.
version: 0.1.0
---

# Capture Durable Fact

Trigger on signals like:
- "I prefer X" / "I always X" / "From now on X"
- "My name is …", "I work at …", "I'm building …"
- "Call me X", "Use Y for Z"
- The user correcting you about something they previously stated

## Procedure

1. Decide whether the fact is **durable**. Skip if it's:
   - A one-off task description
   - Speculation or a hypothetical
   - Information about a third party
2. Choose a category from: `preference`, `bio`, `project`, `convention`,
   `decision`, `relationship`, `tool`. Pick the closest fit.
3. Phrase the fact in one declarative sentence, in third person about the user.
   Good: "User prefers TypeScript over JavaScript for new projects."
   Bad: "I should use TypeScript."
4. Call `mcp__aether__remember` with `fact`, `category`, and a `confidence`
   between 0.5 (inferred) and 0.9 (stated explicitly).
5. Acknowledge in one short sentence: "Noted." or "Got it — saved."

## Anti-patterns

- Don't store the same fact twice. If a fact contradicts an existing one, call
  `mcp__aether__list_facts` first; if you find the prior, use `mcp__aether__forget`
  on it before saving the new one.
- Don't store every casual mention. Aim for facts that will plausibly matter
  in 30 days.
