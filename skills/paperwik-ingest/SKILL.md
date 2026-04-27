---
name: paperwik-ingest
description: >
  Process a source document from the user's Vault/Inbox/ folder and weave it into the
  wiki. Triggers on phrases like "ingest this", "process the new source",
  "add this to my notes", "file this article", "read this for me and file it",
  or any request that asks the agent to integrate fresh material into the
  knowledge base. This is the core product operation; spend the effort to do
  it well.
allowed-tools: Read, Glob, Grep, Write, Edit, Bash, Agent
---

# ingest-source

You are about to process a new source and weave it into the user's knowledge
base. This skill is the central product operation — do it thoroughly, not
quickly.

**Layout** (Paperwik v0.2 onward):

```
%USERPROFILE%\Paperwik\          ← system root (cwd for Claude Code)
    CLAUDE.md, knowledge.db, log.md, index.md, eval.json, .claude\
    Vault\                       ← Obsidian's vault (user-facing only)
        Welcome.md
        Inbox\                   ← user drops sources here
        Projects\                ← all project folders nest here
            <Project Name>\      ← created by the router
                <Page>.md
                Entities\
                _sources\        ← original source files moved here after ingest
                .paperwik\       ← agent-owned ZSC metadata (label.txt)
```

When you write user-facing content (project pages, entity pages, sources),
write under `Vault\Projects\<Project>\`. When you read system files (log.md,
index.md, knowledge.db), they're at the system root.

## Triggers

- "ingest this" / "ingest the new source"
- "process the file in my Inbox"
- "add this article to my notes"
- "read this for me and file it"
- "file this PDF"
- Any request that asks the agent to integrate new material into the wiki

## When NOT to trigger

- User asks a simple question about existing content → use query flow, not ingest
- User asks to "remember" something conversationally → use auto-file-chat at end of turn, not ingest
- File in `Vault/Inbox/` is a binary format we can't read (images without OCR, proprietary formats) → tell the user what's missing

---

## Pre-flight checklist (v0.6.2 — read this BEFORE you start)

By the end of this skill, you MUST have produced **four** outputs. If any is
missing when you reach the Self-check step, you skipped a step — go back and
fix it before reporting to the user.

| # | Required output | Set by |
|---|-----------------|--------|
| 1 | `source_type` value captured (one of: academic / article / newsletter / social / journal / reference) | **Step 2** — returned in router JSON |
| 2 | Summary page YAML frontmatter contains a `source_type:` field with that value | **Step 5** |
| 3 | For new projects (`is_new=true`): `Vault/Projects/<Project>/.paperwik/label.txt` is a real one-sentence description (does NOT start with `TODO:`) | **Step 4** |
| 4 | Indexer ran and returned a chunks count | **Step 7** |

v0.6.0 / v0.6.1 sandboxes shipped without #1, #2, #3 because the agent
followed v0.5.x muscle memory and skipped the classification + label steps
that prose-tightening was supposed to enforce. v0.6.2 fixes this
**architecturally**: source classification now happens *inside* the router,
so Step 2 cannot be skipped without skipping routing entirely.

---

## Flow

### Step 1. Locate the source

Glob `Vault/Inbox/` for files newer than the wiki's last ingest log entry (check
`log.md` tail). If multiple candidates, ask the user which one. If exactly one
recent file, proceed.

If the user gave you a URL or file path outside `Vault/Inbox/`, copy the
content into `Vault/Inbox/<slug>.md` first so the rest of the flow has a
canonical input path — then proceed.

### Step 2. Route — MANDATORY (this also classifies the source TYPE)

> **MANDATORY — run this BEFORE writing any project pages, entity pages, or summary content.** The router's JSON output carries both the project assignment AND the source_type. Skipping or running it late means you've already committed to a project name and source_type that the system never validated.

Determine the target project folder + the source's structural type via the
project router:

```bash
PAPERWIK_PLUGIN="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/marketplaces/paperwik}"
uv run "$PAPERWIK_PLUGIN/scripts/project_router.py" "$INBOX_FILE"
```

The router returns JSON with these fields:

```json
{
  "project_name": "...",
  "project_id": 1,
  "is_new": true,
  "max_similarity": 0.42,
  "routed_via": "cosine_cold_start",
  "source_type": "article",
  "source_type_confidence": 0.87
}
```

**Capture all of these** — they drive the rest of the flow:

- `project_name` → where you'll write the summary page (Step 5) and entity
  pages (Step 6).
- `is_new` → whether you need to populate `.paperwik/label.txt` (Step 4).
- `routed_via` → `"zsc"` (label-based match), `"cosine"` (embedding match),
  `"cosine_cold_start"` (only 1 prior project; created a new one for safety),
  or `"first"` (very first project ever). Useful for your final report.
- `source_type` → goes into the summary page's YAML frontmatter (Step 5)
  AND into the subagent's extraction prompt (Step 3). One of: `academic`,
  `article`, `newsletter`, `social`, `journal`, `reference`.
- `source_type_confidence` → if < 0.40, mention low confidence in your
  final report.

**Respect the routing decision.** Do not override the router's project
assignment based on your own topical read. v0.6.2's cold-start rule
(force-new-project when there's only 1 existing project unless cosine ≥ 0.85)
already addresses the false-positive case that v0.6.1 had to override around.
If the assignment still seems wrong after that, file a bug — don't override
inline.

If `is_new=true`, announce the new folder: *"I've created a new project
folder called 'X' because this source doesn't fit any existing topic
closely."*

**First ingest only:** the embedded classifier downloads (~738 MB FP32) and
quantizes (~150 MB INT8 final) the ONNX model. Takes ~30-60 seconds and is
silent. After that, every subsequent ingest reuses the cached INT8 model in
`~/.cache/huggingface/hub/.paperwik-int8/`.

### Step 3. Delegate to a subagent

Ingest is token-heavy. Spawn a sub-agent via the Agent tool to do the heavy
reading and extraction. **Parameterize the subagent's prompt by the
`source_type` from Step 2** — extraction shape varies by document format:

| Type | Subagent extraction focus |
|------|---------------------------|
| `academic` | methodology, findings, limitations, datasets, citations |
| `article` | thesis sentence + key arguments + concrete examples + author POV |
| `newsletter` | summary stripped of subscribe/footer/ad chrome; the actionable items only |
| `social` | preserve verbatim as a quoted block; capture author + platform + thread context |
| `journal` | personal-journaling structure: date, topics-of-the-day, mood/tone |
| `reference` | searchable index style — minimal editing; capture canonical terms + cross-refs |

Then ask the subagent to:

- Read the full source file.
- Identify the key claims, findings, methods, entities, and cited sources
  (per the type-specific focus above).
- Draft a summary page (200-500 words) with a title, YAML frontmatter
  (`created`, `source`, `tags`, **`source_type`**), a 1-paragraph abstract,
  and the key points as a bullet list. The `source_type` value MUST equal
  the value from Step 2 — do not let the subagent override it.
- Identify 5–20 distinct entities worth tracking (researchers, concepts,
  papers, organizations).
- Return those as structured data to the parent.

### Step 4. Populate descriptive label for new projects — use `populate_label.py`

> **(v0.6.4)** Hand-writing `.paperwik/label.txt` was unreliable across v0.6.0–v0.6.3 sandbox testing — the agent kept leaving the TODO marker in place. v0.6.4 routes label generation through a dedicated tool that validates the label and refuses TODO/empty/too-short input. The indexer (Step 7) will now REFUSE to run if any project's label is still in TODO state.

When the router reports `is_new=true` (or when filing into an existing
project whose label still starts with `TODO:`), generate a one-sentence
descriptive label and write it via:

```bash
PAPERWIK_PLUGIN="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/marketplaces/paperwik}"
uv run "$PAPERWIK_PLUGIN/scripts/populate_label.py" \
    --project "<project_name>" \
    --label "<one descriptive sentence, 60-180 chars, must NOT start with TODO:>"
```

Examples of good labels:

- ✅ `Research on dietary interventions for cognitive decline in adults over 60.`
- ✅ `Practical guides for home-improvement DIY projects on older houses.`
- ✅ `Open-source ORDBMS internals: MVCC, replication, partitioning, pgvector.`

Examples that the tool will REJECT:

- ❌ `TODO: ...` (still has the placeholder marker)
- ❌ `Notes about science` (too short, not topical)
- ❌ `Articles I read about various things` (vague)
- ❌ Empty or whitespace-only string

The tool validates and writes; you don't need to verify the file content
manually. If the call exits non-zero, fix the `--label` argument and re-run.

When `is_new=false` AND the existing label is real (no TODO marker, length
> 20 chars), skip this step entirely — leave the existing label alone.

### Step 5. Write the summary page — use `write_summary.py`

> **(v0.6.4)** Hand-writing summary YAML was unreliable across v0.6.0–v0.6.3 sandbox testing — the agent kept omitting `source_type:`. v0.6.4 routes summary generation through a dedicated tool that requires `source_type` as input and emits a properly-populated YAML frontmatter. The indexer (Step 7) will now REFUSE to run if no summary in the project has `source_type:` in its YAML.

Don't hand-write the summary page. Instead, assemble a JSON spec and call
`write_summary.py`:

```bash
PAPERWIK_PLUGIN="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/marketplaces/paperwik}"
SPEC_FILE=$(mktemp --suffix=.json)
cat > "$SPEC_FILE" << 'EOF'
{
  "project": "PostgreSQL",
  "source_type": "article",
  "source": "https://grokipedia.com/page/PostgreSQL",
  "source_title": "PostgreSQL — Grokipedia",
  "title": "Grokipedia Overview",
  "tags": ["postgresql", "database", "sql", "ordbms", "oss"],
  "body": "Encyclopedic overview of PostgreSQL: history, architecture, ...\n\n## Definition\n\n..."
}
EOF
uv run "$PAPERWIK_PLUGIN/scripts/write_summary.py" --json "$SPEC_FILE"
```

**Required spec fields:** `project`, `source_type`, `title`, `body`.
**`source_type`** MUST equal the value from the router's JSON output in
Step 2 (one of: academic / article / newsletter / social / journal /
reference). The tool validates and refuses unknown source types.

The tool prints `{"path": "...", "source_type": "..."}` on success.
Capture `path` for use in Step 7 (indexer takes the source path, but you
need to know the summary path for Step 6 entity-page cross-references).

You CAN still write the body in markdown freely (cross-links to entity
pages, code blocks, headings, etc.). The tool generates only the YAML
frontmatter; the body is yours. Use standard markdown links —
`[Other Page](../Project/Other-Page.md)` — not wikilinks.

### Step 6. Create or update entity pages

For each entity the subagent identified:

- If a matching entity page exists in the target project folder (or
  cross-project via grep), update it: add a "Source:" backlink to the new
  summary page + any new facts the source provides.
- Otherwise, create a new entity page named after the entity at
  `Vault\Projects\<project>\Entities\<Entity Name>.md` with a stub:
  who/what/why, tagged appropriately (`#person`, `#concept`, `#paper`,
  `#organization`).

### Step 7. Hand off to the indexer

Run the indexer script to chunk the source, embed via fastembed, extract
entities into the graph, and persist to `knowledge.db`:

```bash
PAPERWIK_PLUGIN="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/marketplaces/paperwik}"
uv run "$PAPERWIK_PLUGIN/scripts/index_source.py" --source "<path>" --project "<project_name>"
```

Capture the `chunks` count from the indexer's JSON output. This is pre-flight
check #4.

**v0.6.4: indexer refuses to run if Steps 4 and 5 weren't done correctly.**
Specifically, the indexer pre-flight checks fail with exit code 3 and a
`"kind": "preflight_failed"` JSON error if:

- The project's `.paperwik/label.txt` is empty or still starts with `TODO:`
  → fix by running `populate_label.py` (Step 4).
- The project's directory has summary `.md` files but none contain a
  `source_type:` YAML field → fix by regenerating the summary via
  `write_summary.py` (Step 5).

The error message tells you exactly which fix to apply. Address it and
re-run the indexer; do NOT pass `--skip-preflight` (that flag exists
only for migration / fix-up scenarios, never for normal ingest).

**Low-memory note (v0.6.1+):** the indexer caps fastembed's batch size at
4 by default to avoid the ONNX MatMul OOM that hits 4 GB Windows Sandboxes.
On big-RAM machines you can override via `PAPERWIK_EMBED_BATCH_SIZE=32`
(or higher) for faster ingest. Don't worry about this in routine use.

**v0.6.3: chunker hard cap.** Pathological large paragraphs (an 18 KB
paragraph in the v0.6.2 sandbox crashed ONNX) are now post-processed and
split on whitespace boundaries to stay under `MAX_CHUNK_CHARS = 2000`.
Transparent to you; just expect slightly more chunks on big paragraphs.

**v0.6.3: indexer self-heals the projects table.** If a project name was
never registered via the router (e.g., manual fix-up flows), the indexer
now writes the projects-table row from the chunk embeddings during this
step. Transparent; no action needed.

### Step 8. Update `index.md` and `log.md`

- `index.md`: rely on Dataview — no manual edits needed; the Dataview query
  picks up the new page automatically. But verify by reading `index.md`
  afterwards.
- `log.md`: append a new entry:
  `## [YYYY-MM-DD HH:MM] ingest | <project_name> | <source title>`

### Step 9. Move the source out of `Vault/Inbox/`

Move the ingested file to `Vault/Projects/<project_name>/_sources/<filename>`
so the Inbox only ever contains pending items. Never delete the original — the
user can always re-read it if the summary misses something.

### Step 10. Self-check — verify the four pre-flight outputs

> Before reporting to the user, run these four checks. If any FAILS, do NOT report success — go back to the offending step, fix it, and re-run the check.

```bash
SUMMARY_PAGE="$USERPROFILE/Paperwik/Vault/Projects/<Project>/<slug>.md"
LABEL_FILE="$USERPROFILE/Paperwik/Vault/Projects/<Project>/.paperwik/label.txt"

# Check 1: source_type captured from router output (Step 2)
[ -n "$SOURCE_TYPE" ] && echo "✓ source_type=$SOURCE_TYPE" || echo "✗ MISSING source_type — go back to Step 2"

# Check 2: summary page YAML has source_type
grep -q "^source_type:" "$SUMMARY_PAGE" && echo "✓ YAML has source_type" || echo "✗ MISSING source_type in YAML — go back to Step 5"

# Check 3 (new projects only): label.txt populated AND not still a TODO marker
if [ "$IS_NEW" = "true" ]; then
    if [ ! -s "$LABEL_FILE" ]; then
        echo "✗ EMPTY label.txt — go back to Step 4"
    elif head -c 5 "$LABEL_FILE" | grep -q "^TODO:"; then
        echo "✗ label.txt still has TODO marker — go back to Step 4 and write a real label"
    else
        echo "✓ label.txt populated ($(wc -c < "$LABEL_FILE") bytes)"
    fi
fi

# Check 4: indexer reported a chunks count (you captured this from Step 7's output)
[ -n "$CHUNKS_COUNT" ] && [ "$CHUNKS_COUNT" -gt 0 ] && echo "✓ indexer ran ($CHUNKS_COUNT chunks)" || echo "✗ MISSING chunks count — go back to Step 7"
```

If all four pass, proceed to Step 11. If any fails, the offending step was
skipped or partially executed; fix it before reporting.

### Step 11. Report back to the user

Brief, concrete report:
- Where it was filed (project name + `routed_via`)
- Source type and confidence (from Step 2)
- For new projects: the descriptive label you wrote (from Step 4)
- How many entity pages were created vs. updated
- How many chunks landed in the index (from Step 7)
- Any notable cross-references ("this mentions researcher X who appears in 3
  other reports")

Never say "done" without these specifics. The user should see the graph grow
in Obsidian's sidebar as you work — mention that if it's the first ingest.

---

## Rules

- **One ingest at a time.** If multiple files await, process them sequentially
  and report at the end. Do not parallelize — it breaks the log and the
  project router's online learning.
- **Always run the project router FIRST** (Step 2), before writing any
  project pages, entity pages, or summary content. The router's output is
  the source of truth for both project assignment AND source_type. Don't
  pick a project name from the source's title — wait for the router.
- **Respect the router's project assignment.** Do not override based on
  your own topical read. v0.6.2's cold-start rule already handles the
  "only one prior project" false-positive case. If the assignment still
  seems wrong, file a bug — don't override inline.
- **Use `populate_label.py` to write `.paperwik/label.txt` — never hand-write it.** (v0.6.4)
  The tool validates the label and refuses TODO/empty/too-short input.
  Hand-writing the file is the failure mode v0.6.0–v0.6.3 sandboxes
  consistently hit. The indexer (Step 7) refuses to run if any project
  is still in TODO state.
- **Use `write_summary.py` to write summary pages — never hand-write them.** (v0.6.4)
  The tool requires `source_type` as input and emits proper YAML
  frontmatter. The indexer refuses to run if no summary in the project
  has `source_type:` in its YAML.
- **Source_type comes from the router** (v0.6.2), not from the subagent.
  Pass it into the subagent's prompt AND into the `write_summary.py` JSON
  spec. The subagent's drafted abstract + key points become the `body`
  field of the spec; everything else (frontmatter) is the tool's job.
- **Never ingest content the user hasn't placed in `Vault/Inbox/`.** If they
  give you a URL, fetch the page and save it into `Vault/Inbox/` first
  (Step 1).
- **Never delete the raw source after ingest.** Keep it in `<project>/_sources/`.
- **If any step fails, stop and report cleanly.** Do not partially ingest —
  broken ingests leave the graph inconsistent.
- **If Self-check (Step 10) fails, do not report success to the user.** Go
  back to the offending step. The four pre-flight outputs are a hard
  contract; missing any one is a failed ingest, not a quirky one.
- **`--skip-preflight` on the indexer is for migration / fix-up only.** Never
  use it during normal ingest. The pre-flight is the architectural
  enforcement that fixed v0.6.0–v0.6.3's silent agent-skip failure mode.
