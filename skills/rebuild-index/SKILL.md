---
name: rebuild-index
description: >
  Rebuild knowledge.db from the markdown source of truth. Use when the
  database is missing, corrupted, restored from a backup that has stale
  data, or when retrieval quality suddenly tanks for no obvious reason.
  Triggers on phrases like "rebuild the index", "regenerate knowledge.db",
  "my search is broken — rebuild it", "my index got corrupted",
  "restore the retrieval database from my notes". Iterates every .md file
  in the vault, re-chunks, re-embeds, re-extracts entities, and rewrites
  knowledge.db. Safe to run — the markdown files are untouched.
allowed-tools: Read, Glob, Grep, Bash
---

# rebuild-index

Regenerate `knowledge.db` from the markdown files in the vault.

The markdown files are the source of truth. `knowledge.db` is a derived
cache — delete it anytime and it can be rebuilt from the `.md` files. This
skill does exactly that.

## Triggers

- "rebuild the index"
- "regenerate knowledge.db"
- "my search is broken — rebuild the database"
- "restore the retrieval index from my notes"
- "my index got corrupted"

## When to run

- After restoring the vault from a cloud backup where `knowledge.db` is stale
  or missing (it's in `.gitignore` so won't be version-controlled).
- After retrieval quality suddenly tanks — a corrupted FTS index or
  embedding table can cause this and isn't obvious.
- After a major version upgrade that changes the schema.
- Never as routine maintenance — this is a heavy operation.

## Flow

### 1. Warn the user

Tell them up front:

> Rebuilding the retrieval index from your markdown files. This will:
> - Re-read every `.md` file in your `Knowledge/` folder (~10–60 seconds
>   depending on size).
> - Re-embed every chunk via fastembed (~5 minutes per 1000 chunks on CPU).
> - Re-extract entities via the Claude API (~1 minute per 100 chunks,
>   costs a small number of tokens on your Claude Pro plan).
>
> Your markdown files are NOT modified. Only `knowledge.db` is rewritten.
>
> Proceed?

Wait for yes.

### 2. Move the existing DB aside

```bash
cd "%USERPROFILE%\Knowledge"
if exist knowledge.db move knowledge.db knowledge.db.bak-<timestamp>
```

Keep the backup around until the rebuild succeeds — if rebuild fails, the
user has a safety net.

### 3. Let the scaffolder recreate the empty schema

```bash
del "%USERPROFILE%\Knowledge\.claude\.scaffolded"
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/scaffold-vault.py"
```

This creates an empty `knowledge.db` with the full schema. The scaffolder is
idempotent for everything except the DB — removing the sentinel forces a
fresh DB init.

### 4. Walk the vault, re-index each file

Glob every `.md` file under `Knowledge/` except the special meta files
(`CLAUDE.md`, `Welcome.md`, `index.md`, `log.md`, `decisions.md`). For
each file, call the indexer:

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/index_source.py" --source "<path>" --project "<folder name>"
```

Report progress every 50 files: *"Rebuilt X of Y files, Z chunks indexed so
far..."*

### 5. Rebuild project centroids

After all chunks are indexed, compute each project's average embedding
across its chunks and store as `centroid_embedding`:

```bash
uv run python -c "
from pathlib import Path
import os, sqlite3
import sys
sys.path.insert(0, os.environ['CLAUDE_PLUGIN_ROOT'] + '/scripts')
from embeddings import from_blob, mean_vector, to_blob

db = Path(os.environ['USERPROFILE']) / 'Knowledge' / 'knowledge.db'
conn = sqlite3.connect(str(db))
for row in conn.execute('SELECT DISTINCT project FROM chunks').fetchall():
    project = row[0]
    chunks = conn.execute('SELECT embedding FROM chunks WHERE project=? AND embedding IS NOT NULL', (project,)).fetchall()
    vecs = [from_blob(c[0]) for c in chunks if c[0]]
    if vecs:
        centroid = mean_vector(vecs)
        conn.execute('UPDATE projects SET centroid_embedding=? WHERE name=?', (to_blob(centroid), project))
conn.commit()
conn.close()
print('Centroids rebuilt.')
"
```

### 6. Verify and clean up

Run a smoke query against the rebuilt DB:

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/search.py" "test query from rebuild" 3
```

If the smoke test returns ≥1 result, delete the backup:

```bash
del "%USERPROFILE%\Knowledge\knowledge.db.bak-<timestamp>"
```

If it returns zero results, restore the backup and tell the user the
rebuild failed with the specific error:

```bash
move knowledge.db.bak-<timestamp> knowledge.db
```

### 7. Append to log.md

```
## [YYYY-MM-DD HH:MM] rebuild-index | N files reprocessed, M chunks indexed
```

## Rules

- **Never touch `.md` files during a rebuild.** The markdown is the source
  of truth; any edits during rebuild indicate a bug.
- **Always keep the `.bak` until the rebuild is verified.**
- **If rebuild takes longer than 15 minutes**, checkpoint progress and let
  the user interrupt gracefully.
- **Cost transparency:** before starting, estimate the Claude-API token
  cost for entity extraction (count chunks × ~1K tokens each) and show it
  to the user: *"Rebuild will use approximately X,000 Claude API tokens.
  Proceed?"* — especially important if the vault is large.
