---
name: paperwik-lint
description: >
  Periodic wiki health check. Triggers on phrases like "lint my wiki",
  "check the wiki for problems", "wiki health check", "find orphans",
  "find contradictions", "clean up my wiki", "audit my notes", "what's
  broken", "review my knowledge base". Scans for contradictions between
  pages, stale claims superseded by newer sources, orphan pages with no
  inbound links, entities mentioned but missing their own page, and
  projects inactive long enough to archive. Reports findings; makes fixes
  only on explicit request.
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
---

# lint-wiki

Run a health check over the user's vault. Report — don't silently fix.

## Triggers

- "lint my wiki"
- "check the wiki for problems"
- "clean up my wiki"
- "audit my notes"
- "what's broken"
- "wiki health check"

## Flow

Pass through the vault collecting issues in these five buckets. Do them in
parallel where possible (Glob + Grep are cheap) and aggregate findings
before reporting.

### 1. Orphan pages (no inbound links)

For each `.md` file in the active project folders (not `Vault/Inbox/`, `Vault/Archive/`,
or top-level meta files): Grep the entire vault for references to the page's
filename. If zero matches besides the file itself, flag as orphan.

Exception: new pages (created within the last 7 days) — flag but don't alarm,
since they may be mid-integration.

### 2. Entities without pages

Query the entity graph:

```bash
# $CLAUDE_PLUGIN_ROOT is not reliably exported to skill shells; fall back to install path
PAPERWIK_PLUGIN="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/marketplaces/paperwik}"
uv run "$PAPERWIK_PLUGIN/scripts/lint_entities.py"
```

*(If `lint_entities.py` doesn't exist yet, fall back to Grep: find every
`#person` `#paper` `#concept` `#organization` tag usage, then check if an
entity page exists in `<project>/Entities/<name>.md`.)*

Entities mentioned in ≥3 sources but without a dedicated page are the
highest-value flags — they're clearly worth tracking.

### 3. Stale claims

Heuristic: when a summary page contains a specific factual claim ("X is 20%"
or "Y was published in 2022") AND a newer page (same project, more recent
`created` frontmatter) contains a conflicting claim, flag both.

Do this only if the user's vault has ≥10 pages total — below that, this check
is noisy.

### 4. Internal contradictions

Cross-page contradictions are hard to detect programmatically. Use a lightweight
LLM pass: for each pair of entity pages with the same `normalized_name` but
different `description` fields, compare briefly and flag real conflicts
(not just wording differences).

Budget this to ≤5 comparison pairs per lint run — the user won't thank you
for a 30-minute lint.

### 5. Inactive projects

Query `projects` table in `knowledge.db`:

```bash
uv run -c "
import sqlite3, os, datetime
conn = sqlite3.connect(os.path.expanduser('~/Paperwik/Vault/Projects/knowledge.db'))
cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=180)).isoformat()
rows = conn.execute('SELECT name, last_activity_ts FROM projects WHERE archived=0 AND last_activity_ts < ?', (cutoff,)).fetchall()
for r in rows:
    print(f'{r[0]} (last activity: {r[1]})')
"
```

Flag candidates for the user. Only auto-archive (via `auto_archive_inactive`
in project_router.py) if the user explicitly confirms.

## Report format

```markdown
# Lint report — <date>

## Summary
- Pages scanned: N
- Issues found: M

## Orphan pages (<count>)
- `<project>/<page.md>` — no inbound links
- ...

## Entities without pages (<count>, sorted by mention count)
- **<name>** (PERSON) — mentioned in N sources

## Stale claims (<count>)
- `<page A>` says "X" — superseded by `<page B>` which says "Y" (<date>)

## Internal contradictions (<count>)
- Entity `<name>` has different descriptions in `<page A>` and `<page B>`

## Inactive projects (<count>)
- **<project>** — last activity <N days> ago. Archive?
```

End with: *"Want me to fix any of these? Tell me which and I'll handle them
one at a time."* — do not bulk-fix without per-item confirmation.

## Rules

- **Never delete or archive without explicit user confirmation.**
- **Never rewrite factual claims the user authored.** If you disagree with a
  claim, flag it as a question, not a correction.
- **Cap the lint at 5 minutes of work.** If the vault is huge, sample the
  most recently touched 200 pages and note what was skipped.
- Always append the lint event to `log.md`: `## [YYYY-MM-DD HH:MM] lint | N
  issues found, 0 fixed`.
