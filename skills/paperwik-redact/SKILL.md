---
name: paperwik-redact
description: >
  Permanently purges a topic, name, file, or phrase from the user's vault AND
  from its git history. Use when the user says things like "redact X",
  "scrub X", "remove all traces of X", "delete and forget X", "wipe X",
  "gdpr me X", "burn X from history", "make it like X never existed", or
  otherwise asks to irreversibly erase content (not just move to Archive or
  delete a single note). Because a PostToolUse hook auto-commits every change,
  ordinary deletion leaves recoverable history — this skill is the only
  correct way to truly remove content. Always prefers conversational
  confirmation gates over silent execution.
allowed-tools: Bash, Read, Glob, Grep
---

# redact-history

You are helping a non-technical user permanently remove content from their
Obsidian vault. The vault is under `%USERPROFILE%\Paperwik\`. A PostToolUse
hook silently commits every file change to git, so plain deletion does NOT
erase anything — the content remains in git history. This skill is the ONLY
correct path for true erasure.

**Never run the redaction script without walking the user through the full
confirmation flow below.** Never invent or shortcut confirmation tokens.
Never redact `.claude/`, `.obsidian/`, `.git/`, `.gitignore`, `knowledge.db`,
or anything outside the current vault.

## When to trigger

Trigger on natural-language phrases including (non-exhaustive):

1. "redact X" / "redact my notes about X"
2. "scrub X" / "scrub all mentions of X"
3. "remove all traces of X" / "wipe every mention of X"
4. "delete and forget X" / "make it like X never existed"
5. "gdpr me X" / "right-to-be-forgotten X"
6. "burn X from history" / "nuke X"
7. "permanently delete X" / "irreversibly remove X"
8. "purge X"

Do NOT trigger on plain "delete this note" or "archive X" — those are ordinary
edits and the auto-commit hook handles them. This skill is exclusively for
*irreversible* removal including from git history.

## Conversation flow

### Step 1 — Disambiguate the target

The user's phrase gives you a topic. Use `Glob` / `Grep` inside the vault
(NEVER outside) to see what exists. Ask clarifying questions if ambiguous.
Resolve to ONE of: a literal path relative to vault root, a filename glob,
or a content-match list (pre-resolve via `Grep`, then pass individual paths).

### Step 2 — Preview (first confirmation gate)

Before ANY destructive action, run the script in dry-run mode:

```bash
# $CLAUDE_PLUGIN_ROOT is not reliably exported to skill shells; fall back to install path
PAPERWIK_PLUGIN="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/marketplaces/paperwik}"
powershell -NoProfile -ExecutionPolicy Bypass -File "$PAPERWIK_PLUGIN/scripts/redact-history.ps1" -TargetPattern "<pattern>" -ConfirmationToken "DRYRUN"
```

The script returns `key=value` lines including `matched_files`, `matched_list`,
`commits_to_rewrite`, `status=dryrun_ok`. Show the user the full file list
and commit count verbatim.

To proceed, accept ONLY explicit phrases: `yes, purge` / `yes purge it` /
`confirmed, purge` / `proceed with purge`. Re-prompt on soft confirmations
(`ok`, `sure`, `yeah`): *"I need an explicit confirmation because this is
irreversible. Please type `yes, purge` to proceed, or `cancel` to abort."*

### Step 3 — High-risk second gate

Escalate to a SECOND confirmation if:
- `matched_files` > 20
- User phrase contained: "everything", "all my notes", "the whole wiki",
  "nuke it", "burn it down", "wipe the vault"
- Pattern resolves to a top-level directory

Prompt: *"This is a large redaction (N files, M commits). To confirm, please
type the exact name of this wiki: **`Paperwik`**"* — exact case-sensitive
match required.

### Step 4 — Execute

Invoke the script for real; pass the user's literal confirmation phrase as
`-ConfirmationToken`.

### Step 5 — Report back

Read the `status=ok` output and tell the user:
- Files purged and commits rewritten
- Audit ID (short hex — for later reference if they ever dispute the action)
- Tombstone location (`.claude/tombstones.jsonl`)
- 30-day cloud auto-expiry notice with an offer to open the cloud recycle
  bin:
  - OneDrive: `https://onedrive.live.com/?id=recyclebin`
  - Google Drive: `https://drive.google.com/drive/trash`

Also: remind the user that the agent itself will now refuse to search for,
reconstruct, or describe the redacted content — that's the tombstone check in
action. If they ever need it back and the cloud copy has aged out, it's
gone.

## Refusal cases (script returns `status=refused`)

- `reason=not_a_vault` · `reason=pattern_traversal` · `reason=pattern_internal`
- `reason=no_matches` · `reason=tool_missing` · `reason=not_a_git_repo`

If the script refuses, relay the reason plainly to the user. Do not try to
work around it.

## Invariants

- Never pass user-supplied strings into the shell unquoted.
- Never set `-ConfirmationToken` to anything other than what the user
  literally typed, or `DRYRUN`.
- Never redact multiple vaults in one call (we only have one).
- Never attempt elevated/admin execution.
- If the script exits non-zero (it shouldn't — errors come back as
  `status=error`), treat as hard error and do not claim success.
