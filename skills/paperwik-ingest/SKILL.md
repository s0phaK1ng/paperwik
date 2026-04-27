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

## Pre-flight checklist (v0.6.1 — read this BEFORE you start)

By the end of this skill, you MUST have produced **four** outputs. If any is
missing when you reach the Self-check step, you skipped a step — go back and
fix it before reporting to the user.

| # | Required output | Set by |
|---|-----------------|--------|
| 1 | `source_type` value captured (one of: academic / article / newsletter / social / journal / reference) | **Step 2** |
| 2 | Summary page YAML frontmatter contains a `source_type:` field with that value | **Step 6** |
| 3 | For new projects (`is_new=true`): `Vault/Projects/<Project>/.paperwik/label.txt` is non-empty (one descriptive sentence) | **Step 5** |
| 4 | Indexer ran and returned a chunks count | **Step 8** |

A v0.6.0 sandbox ingest silently shipped without #1, #2, and #3 — the agent
followed v0.5.x muscle memory through a flow that didn't yet exist. v0.6.1
restructures the steps below so this is no longer easy to do. Treat the
numbered steps as a hard contract.

---

## Flow

### Step 1. Locate the source

Glob `Vault/Inbox/` for files newer than the wiki's last ingest log entry (check
`log.md` tail). If multiple candidates, ask the user which one. If exactly one
recent file, proceed.

### Step 2. Classify the source TYPE — MANDATORY

> **MANDATORY — do not proceed past this step until you have captured `source_type` and `confidence`.** The next step (subagent dispatch) consumes the `source_type` to tailor its extraction prompt; the eventual summary page's YAML carries the value forward; missing this step means downstream output is wrong, not just slightly off.

Run zero-shot classification on the source. Fast (~100-300 ms after first-run
model warmup):

```bash
PAPERWIK_PLUGIN="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/marketplaces/paperwik}"
uv run "$PAPERWIK_PLUGIN/scripts/source_classifier.py" \
    --file "$INBOX_FILE" \
    --filename "$(basename "$INBOX_FILE")"
```

Output is JSON: `{"type": "...", "confidence": 0.xx}`. Capture both. The
type is one of: `academic`, `article`, `newsletter`, `social`, `journal`,
`reference`.

**Edge cases:**

- If `confidence < 0.40`, treat type as `article` (the safe default) but
  mention the low confidence in your final report so the user knows it's
  borderline.
- If the classifier crashes or returns malformed JSON, retry once. If it
  fails again, treat type as `article` and continue — DO NOT block ingest
  on classifier failure. Note the failure in your final report.

**First ingest only:** the classifier downloads (~738 MB FP32) and quantizes
(~150 MB INT8 final) the ONNX model. Takes ~30-60 seconds and is silent. After
that, every subsequent ingest reuses the cached INT8 model in
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

### Step 4. Route the source to the correct project folder

Determine the target project folder via the project router. The plugin's
Python scripts live inside Claude Code's plugin cache — on Windows that's
`$HOME/.claude/plugins/marketplaces/paperwik/scripts/` (equivalently
`$USERPROFILE\.claude\plugins\marketplaces\paperwik\scripts\`).
`$CLAUDE_PLUGIN_ROOT` is set for some Claude Code hook contexts but
is NOT reliably exported to the skill's bash shell — use the explicit
path or the fallback pattern below:

```bash
PAPERWIK_PLUGIN="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/marketplaces/paperwik}"
uv run "$PAPERWIK_PLUGIN/scripts/project_router.py" "$INBOX_FILE"
```

The router returns JSON with `project_name`, `project_id`, `is_new`,
`max_similarity`, and (v0.6.0+) `routed_via`. The `routed_via` field is
`"zsc"`, `"cosine"`, or `"first"` — useful for the diagnostics log but
not for user messaging. Respect the routing decision silently — do not ask
the user where to file. If `is_new=true`, announce the new folder: *"I've
created a new project folder called 'X' because this source doesn't fit
any existing topic closely."*

### Step 5. Generate descriptive label for new projects — MANDATORY (when `is_new=true`)

> **MANDATORY when `is_new=true` — do not proceed past this step until `<Project>/.paperwik/label.txt` is non-empty.** Empty labels disable ZSC routing for that project FOREVER (the project will silently always fall through to cosine), defeating half the v0.6.0 routing improvement.

When the router reports `is_new=true`, it has already created
`Vault/Projects/<Project>/.paperwik/label.txt` as an empty placeholder.
Your job: generate a ONE-SENTENCE descriptive label and write it there.

The label is what the ZSC router compares future sources against, so the
more topical and specific the better:

- ❌ Bad:  `Notes about science`
- ✅ Good: `Research on dietary interventions for cognitive decline in adults over 60.`
- ❌ Bad:  `Articles I read`
- ✅ Good: `Practical guides for home-improvement DIY projects on older houses.`

Constraints: plain UTF-8 text, one sentence, **no trailing newline**, target
60–180 characters.

```bash
LABEL_FILE="$USERPROFILE/Paperwik/Vault/Projects/<Project>/.paperwik/label.txt"
printf '%s' 'Research on dietary interventions for cognitive decline in adults over 60.' > "$LABEL_FILE"
```

When `is_new=false` (filing into an existing project), skip this step — the
existing label, if any, was set on the project's first ingest. Existing
projects whose `label.txt` is empty (e.g. v0.5.x projects that pre-date
v0.6.0) are silently skipped by the ZSC router and fall through to cosine;
that's acceptable degradation.

### Step 6. Write the summary page

Create a new markdown file at
`%USERPROFILE%\Paperwik\Vault\Projects\<project_name>\<slug-of-title>.md`.
Use the frontmatter and structure from Step 3. Use standard markdown links —
`[Other Page](../Project/Other-Page.md)` — not wikilinks.

**Verify** the YAML frontmatter contains a `source_type:` field whose value
equals the type from Step 2. This is pre-flight check #2.

### Step 7. Create or update entity pages

For each entity the subagent identified:

- If a matching entity page exists in the target project folder (or
  cross-project via grep), update it: add a "Source:" backlink to the new
  summary page + any new facts the source provides.
- Otherwise, create a new entity page named after the entity at
  `Vault\Projects\<project>\Entities\<Entity Name>.md` with a stub:
  who/what/why, tagged appropriately (`#person`, `#concept`, `#paper`,
  `#organization`).

### Step 8. Hand off to the indexer

Run the indexer script to chunk the source, embed via fastembed, extract
entities into the graph, and persist to `knowledge.db`. Use the same
`$PAPERWIK_PLUGIN` resolution pattern as Step 4:

```bash
PAPERWIK_PLUGIN="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/marketplaces/paperwik}"
uv run "$PAPERWIK_PLUGIN/scripts/index_source.py" --source "<path>" --project "<project_name>"
```

Capture the `chunks` count from the indexer's JSON output. This is pre-flight
check #4.

**Low-memory note (v0.6.1):** the indexer caps fastembed's batch size at
4 by default to avoid the ONNX MatMul OOM that hits 4 GB Windows Sandboxes.
On big-RAM machines you can override via `PAPERWIK_EMBED_BATCH_SIZE=32`
(or higher) for faster ingest. Don't worry about this in routine use.

### Step 9. Update `index.md` and `log.md`

- `index.md`: rely on Dataview — no manual edits needed; the Dataview query
  picks up the new page automatically. But verify by reading `index.md`
  afterwards.
- `log.md`: append a new entry:
  `## [YYYY-MM-DD HH:MM] ingest | <project_name> | <source title>`

### Step 10. Move the source out of `Vault/Inbox/`

Move the ingested file to `Vault/Projects/<project_name>/_sources/<filename>`
so the Inbox only ever contains pending items. Never delete the original — the
user can always re-read it if the summary misses something.

### Step 11. Self-check — verify the four pre-flight outputs

> Before reporting to the user, run these four checks. If any FAILS, do NOT report success — go back to the offending step, fix it, and re-run the check.

```bash
SUMMARY_PAGE="$USERPROFILE/Paperwik/Vault/Projects/<Project>/<slug>.md"
LABEL_FILE="$USERPROFILE/Paperwik/Vault/Projects/<Project>/.paperwik/label.txt"

# Check 1: source_type was captured (you have it as a shell variable from Step 2)
[ -n "$SOURCE_TYPE" ] && echo "✓ source_type=$SOURCE_TYPE" || echo "✗ MISSING source_type — go back to Step 2"

# Check 2: summary page YAML has source_type
grep -q "^source_type:" "$SUMMARY_PAGE" && echo "✓ YAML has source_type" || echo "✗ MISSING source_type in YAML — go back to Step 6"

# Check 3 (new projects only): label.txt is non-empty
if [ "$IS_NEW" = "true" ]; then
    [ -s "$LABEL_FILE" ] && echo "✓ label.txt populated ($(wc -c < "$LABEL_FILE") bytes)" || echo "✗ EMPTY label.txt — go back to Step 5"
fi

# Check 4: indexer reported a chunks count (you captured this from Step 8's output)
[ -n "$CHUNKS_COUNT" ] && [ "$CHUNKS_COUNT" -gt 0 ] && echo "✓ indexer ran ($CHUNKS_COUNT chunks)" || echo "✗ MISSING chunks count — go back to Step 8"
```

If all four pass, proceed to Step 12. If any fails, the offending step was
skipped or partially executed; fix it before reporting.

### Step 12. Report back to the user

Brief, concrete report:
- Where it was filed
- Source type and confidence (from Step 2)
- For new projects: the descriptive label you wrote (from Step 5)
- How many entity pages were created vs. updated
- How many chunks landed in the index (from the indexer's output, Step 8)
- Any notable cross-references ("this mentions researcher X who appears in 3
  other reports")

Never say "done" without these specifics. The user should see the graph grow
in Obsidian's sidebar as you work — mention that if it's the first ingest.

---

## Rules

- **One ingest at a time.** If multiple files await, process them sequentially
  and report at the end. Do not parallelize — it breaks the log and the
  project router's online learning.
- **Never ingest content the user hasn't placed in `Vault/Inbox/`.** If they paste
  a URL, offer to fetch + save it into `Vault/Inbox/` first.
- **Always run source classification before subagent dispatch.** (v0.6.1) The
  subagent's extraction prompt depends on it; the YAML frontmatter carries
  it; downstream queries filter on it. Skipping Step 2 silently breaks
  three downstream consumers.
- **Always populate `.paperwik/label.txt` when creating a new project.** (v0.6.1)
  An empty label silently disables ZSC routing for that project forever.
  Skipping Step 5 turns a default-on feature off without warning.
- **Always run the project router.** Never pick a folder heuristically. The
  router is the learning system.
- **Never delete the raw source after ingest.** Keep it in `<project>/_sources/`.
- **If any step fails, stop and report cleanly.** Do not partially ingest —
  broken ingests leave the graph inconsistent.
- **If Self-check (Step 11) fails, do not report success to the user.** Go
  back to the offending step. The four pre-flight outputs are a hard
  contract; missing any one is a failed ingest, not a quirky one.
