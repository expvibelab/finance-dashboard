---
name: Recall Before Answering
description: Use whenever the user references something they told you previously, asks "remember when", mentions a name or project they expect you to know, or asks a question whose answer depends on prior context. Searches past sessions and surfaces the relevant snippet before answering.
version: 0.1.0
---

# Recall Before Answering

When the user's question hinges on past context, follow this procedure:

1. Identify the **anchor term** — the name, topic, or event that should match
   prior conversations. Keep it short (1–4 words).
2. Call `mcp__aether__recall` with that anchor and `limit: 8`.
3. Skim the results for the highest-confidence match. Look for messages where
   the user actually stated the fact, not where you (the assistant) speculated.
4. Also call `mcp__aether__list_facts` — curated facts are higher signal than
   raw transcripts.
5. Compose your answer using the recalled context, citing it briefly: "You
   mentioned earlier that …".
6. If nothing relevant turns up, say so honestly and ask for clarification.

## Failure modes to avoid
- Don't recall on every turn — only when context is genuinely needed.
- Don't paste raw recall results back to the user; weave them into prose.
- Don't recall for in-session memory; you already have the current session.

## Calibration
Recall is cheap. Skipping recall when needed is expensive — it makes you look
amnesiac. When in doubt, recall.
