---
name: ingest-source
description: >
  Process a source document from the user's _Inbox/ folder and weave it into the
  wiki. Triggers on phrases like "ingest this", "process the new source",
  "add this to my notes", "file this article", "read this for me and file it",
  or any request that asks the agent to integrate fresh material into the
  knowledge base. This is the core product operation; spend the effort to do
  it well.
allowed-tools: Read, Glob, Grep, Write, Edit, Bash, Agent
---

# ingest-source

You are about to process a new source and weave it into the user's single-vault
knowledge base at `%USERPROFILE%\Knowledge\`. This skill is the central
product operation — do it thoroughly, not quickly.

## Triggers

- "ingest this" / "ingest the new source"
- "process the file in my _Inbox"
- "add this article to my notes"
- "read this for me and file it"
- "file this PDF"
- Any request that asks the agent to integrate new material into the wiki

## When NOT to trigger

- User asks a simple question about existing content → use query flow, not ingest
- User asks to "remember" something conversationally → use auto-file-chat at end of turn, not ingest
- File in `_Inbox/` is a binary format we can't read (images without OCR, proprietary formats) → tell the user what's missing

## Flow

### 1. Locate the source

Glob `_Inbox/` for files newer than the wiki's last ingest log entry (check
`log.md` tail). If multiple candidates, ask the user which one. If exactly one
recent file, proceed.

### 2. Delegate to a subagent

Ingest is token-heavy. Spawn a sub-agent via the Agent tool to do the heavy
reading and extraction. Prompt it to:

- Read the full source file.
- Identify the key claims, findings, methods, entities, and cited sources.
- Draft a summary page (200-500 words) with a title, YAML frontmatter
  (`created`, `source`, `tags`, `source_type`), a 1-paragraph abstract, and
  the key points as a bullet list.
- Identify 5–20 distinct entities worth tracking (researchers, concepts,
  papers, organizations).
- Return those as structured data to the parent.

### 3. Route the source to the correct project folder

Before writing anything, determine the target project folder via the
project router:

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/project_router.py" "$INBOX_FILE"
```

The router returns JSON with `project_name`, `project_id`, `is_new`, and
`max_similarity`. Respect its decision silently — do not ask the user where to
file. If `is_new=true`, announce the new folder: *"I've created a new project
folder called 'X' because this source doesn't fit any existing topic closely."*

### 4. Write the summary page

Create a new markdown file at
`%USERPROFILE%\Knowledge\<project_name>\<slug-of-title>.md`. Use the frontmatter
and structure from step 2. Use standard markdown links — `[Other Page](../Project/Other-Page.md)` — not wikilinks.

### 5. Create or update entity pages

For each entity the subagent identified:

- If a matching entity page exists in the target project folder (or
  cross-project via grep), update it: add a "Source:" backlink to the new
  summary page + any new facts the source provides.
- Otherwise, create a new entity page named after the entity
  (`<project>/Entities/<Entity Name>.md`) with a stub: who/what/why,
  tagged appropriately (`#person`, `#concept`, `#paper`, `#organization`).

### 6. Hand off to the indexer

Run the indexer script to chunk the source, embed via fastembed, extract
entities into the graph, and persist to `knowledge.db`:

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/index_source.py" --source "<path>" --project "<project_name>"
```

*(If `index_source.py` does not yet exist, call `scripts/graph.py` directly
with the source text chunks and let it populate the entity tables. The
chunks + embeddings will be handled by search.py when it runs queries.)*

### 7. Update `index.md` and `log.md`

- `index.md`: rely on Dataview — no manual edits needed; the Dataview query
  picks up the new page automatically. But verify by reading `index.md`
  afterwards.
- `log.md`: append a new entry:
  `## [YYYY-MM-DD HH:MM] ingest | <project_name> | <source title>`

### 8. Move the source out of `_Inbox/`

Move the ingested file to `<project_name>/_sources/<filename>` so the Inbox
only ever contains pending items. Never delete the original — the user can
always re-read it if the summary misses something.

### 9. Report back to the user

Brief, concrete report:
- Where it was filed
- How many entity pages were created vs. updated
- How many chunks landed in the index (from the indexer's output)
- Any notable cross-references ("this mentions researcher X who appears in 3
  other reports")

Never say "done" without these specifics. The user should see the graph grow
in Obsidian's sidebar as you work — mention that if it's the first ingest.

## Rules

- **One ingest at a time.** If multiple files await, process them sequentially
  and report at the end. Do not parallelize — it breaks the log and the
  project router's online learning.
- **Never ingest content the user hasn't placed in `_Inbox/`.** If they paste
  a URL, offer to fetch + save it into `_Inbox/` first.
- **Always run the project router.** Never pick a folder heuristically. The
  router is the learning system.
- **Never delete the raw source after ingest.** Keep it in `<project>/_sources/`.
- **If any step fails, stop and report cleanly.** Do not partially ingest —
  broken ingests leave the graph inconsistent.
