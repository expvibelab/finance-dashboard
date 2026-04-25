---
name: Create New Skill
description: Use after you complete a non-trivial task that you'll likely face variants of in the future. Captures the procedure as a persistent skill the agent can autoload next time. Triggered by reflection, not user request.
version: 0.1.0
---

# Create New Skill

After finishing a task, ask yourself:
> If a similar request came in next week, would I want to reread my own notes?

If yes, create a skill.

## Procedure

1. Pick a slug: 2–4 lower-case-hyphenated words. Be specific
   (`debug-flaky-pytest` over `debug-tests`).
2. Write the **description** as a precise trigger. The agent uses this string
   to decide when to autoload the skill — vague descriptions = useless skills.
   Format: "Use when …".
3. Write the **body** in markdown for your future self:
   - Steps (numbered).
   - Decision rules (when to branch).
   - Common failure modes.
   - Anti-patterns.
   Keep it under 15KB; tighter is better.
4. Call `mcp__aether__create_skill` with `name`, `description`, `body`,
   optional `slug`.
5. Tell the user briefly: "Saved a skill for next time: `<slug>`."

## Quality bar

- A skill that just says "do the obvious thing" has no value — delete it.
- A skill should encode something you'd otherwise relearn the hard way.
- If you can express it in three lines, it's not skill-worthy yet.
