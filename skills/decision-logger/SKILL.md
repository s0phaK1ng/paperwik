---
name: decision-logger
description: >
  Capture user decisions into decisions.md automatically. Triggers when the
  user uses decision-making language like "let's go with X", "I've decided
  to use X", "I'll go with X", "decided — we're doing X", "going forward,
  we're using X", "final answer: X", "settle on X", "commit to X".
  Offers to append a structured decision line; never silently writes
  without agreeing with the user.
allowed-tools: Read, Write, Edit
---

# decision-logger

Detect and capture user decisions into a per-vault decisions log.

## Triggers

Listen for decision-making phrases in the user's messages:

- "let's go with X" / "I'll go with X"
- "I've decided to use X" / "decided — we're using X"
- "going forward, X" / "from now on, X"
- "final answer: X"
- "settle on X" / "commit to X"
- "stick with X"
- "Henderson isn't credible for this" (a decision to exclude)
- "the keto approach it is"

Do NOT trigger on passive/hypothetical language like "we might use X" or
"what if we tried Y" — those aren't decisions.

## Flow

When triggered:

1. **Confirm you heard a decision**, briefly:
   *"Sounds like a decision — want me to log it?"*

2. **If the user confirms** (yes / go / log it / sure):
   - Look for `%USERPROFILE%\Paperwik\decisions.md`. If it doesn't exist,
     create it with a header block:

   ```markdown
   ---
   created: 2026-04-22
   tags: [decisions, meta]
   ---

   # Decisions

   Append-only log of decisions the user has committed to. Each entry has
   a timestamp, a short title, and the reasoning if the user supplied any.
   ```

   - Append a new entry:

   ```markdown
   ## [YYYY-MM-DD] <short decision title>

   **Context:** <one sentence — what was being decided>
   **Chosen:** <what the user picked>
   **Rationale:** <if user explained why>
   ```

3. **If the user declines** (no / not yet / let me think), just drop it.
   Never log without explicit assent.

## What counts as a "short decision title"

- "Going keto for 30 days"
- "Using Gemini Deep Research as primary source"
- "Excluding Henderson reports"
- "Henceforth, all health research goes in Cognitive Health folder"

## What to IGNORE

- Decisions about Claude Code settings or the wiki mechanics ("let's use
  markdown links") — those are infrastructure; the decisions.md log is for
  user's own subject-matter decisions.
- Jokes / rhetorical decisions ("I've decided the meeting was a waste").
- Decisions the user immediately reverses in the same message.

## Rules

- **Never silently log.** Always ask first.
- **Never edit a prior decision.** If the user reverses, append a new
  entry that references the prior one:
  *"**Supersedes:** decision from 2026-04-15 (X). Actually going with Y."*
- **The log is the user's, not the agent's.** Don't log decisions about
  how the agent should behave — those go in
  `.claude/skills/state/active_context.md` instead.
