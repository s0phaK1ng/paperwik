---
name: paperwik-undo
description: >
  Undo the last change. Triggers on phrases like "undo that", "undo the last
  change", "roll that back", "revert that", "put it back the way it was",
  "that wasn't what I wanted — revert", "undo my last edit", "back out that
  last change". Uses the silent Git autosave committed by the PostToolUse
  hook; runs `git checkout HEAD~1` on the specified file, or the most recently
  changed file if unspecified.
allowed-tools: Bash, Read, Glob
---

# revert-state

The user wants to undo a recent change. Every file mutation in the wiki gets
silently committed to Git by the PostToolUse hook, so undo is always
available — you just have to identify the right commit.

## Triggers

- "undo that"
- "undo the last change"
- "roll that back" / "revert that"
- "put it back the way it was"
- "that wasn't right — undo it"

## Flow

### 1. Identify the target file

- If the user's phrase names a specific file or topic, resolve it via Glob or
  Grep. If ambiguous, ask **one** clarifying question with the 2–3 most recent
  candidates.
- If the user says "the last change" without specifying, look at
  `git log --oneline` (safe-git-subset-allowed) and find the most recent
  commit's modified files.

### 2. Show what will be reverted

Before running the undo, tell the user exactly what's about to change:

> I'll revert `<file>` from its current state to what it was before my last
> change (`<commit-short-hash>` at `<timestamp>`). The previous content
> started with: "<first 100 chars>". Proceed?

If the user types "yes" / "go" / "do it" / similar explicit confirmation,
proceed. If they hedge, wait for clarity.

### 3. Execute the revert

Use the safe-git subset (PreToolUse governor allows this):

```bash
cd "%USERPROFILE%\Paperwik"
git checkout HEAD~1 -- "<relative file path>"
```

### 4. Commit the revert as a new commit (not a reset)

The PostToolUse hook will auto-commit once you've modified the file, but make
sure the subsequent Silent-Commit run labels it correctly by having the user's
revert as the most recent mutation. Nothing extra to do — just confirm the
file changed.

### 5. Confirm to the user

> Reverted `<file>`. The previous version is now current. The change you
> undid is still in Git history if you need it back — just say "redo that".

*(Note: redo isn't implemented in v1; if the user asks, say you'll capture it
as a feature request and in the meantime they can open the file's Git history
in Obsidian's File Recovery plugin.)*

## Limits

- **Only one step of undo per invocation.** If the user wants to walk back
  further ("actually go back three changes"), ask them to approve each step
  individually. Never bulk-revert without per-step confirmation.
- **Never revert `knowledge.db`, `.git/`, `.obsidian/`, or `.claude/`.** The
  allow list blocks these anyway, but don't try.
- **If Git says the file has no prior version** (first commit, or file was
  just created), tell the user: *"This file doesn't have a prior version yet
  — it was created in the change you just made. If you want to remove it
  entirely, I can delete it; say 'delete it'."*

## Output

Always include:
- What file was reverted
- The new first line / first sentence of its content (so user sees it's
  actually what they expected)
- Brief confirmation that Git still has the undone version
