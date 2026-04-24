---
name: research
description: >
  This skill should be used when the user asks to "research X thoroughly",
  "do deep research on Y", "write a deep research report on Z", "get me a
  long writeup on X", "produce a research doc on Y", "investigate X in
  depth", or "deep dive on X". Produces a 3,000-8,000 word synthesis document
  with 15+ cited sources, YAML frontmatter, H2/H3 structure, and a Sources
  table -- dropped into the Vault/Inbox/ for the `ingest` skill to absorb.
  DO NOT TRIGGER on short factual questions ("what is X"), on "ingest this"
  (that's the `ingest` skill), on general notes or journaling, or on the
  user typing something that reads like an Obsidian page title rather than
  a research topic. Takes ~10 minutes and consumes a meaningful chunk of
  the user's weekly Claude subscription budget -- the skill always shows a
  cost/time confirmation gate before running.
version: 0.4.0
---

# Research — paperwik's deep-research skill

Execute a 4-phase hierarchical research loop using only Claude Code native
primitives: WebSearch, WebFetch, Task subagents, and the SubagentStop hook.
Produce a markdown file that lands in the user's Vault/Inbox/ and is then
picked up by the `ingest` skill like any other source.

## Phase 0 — Pre-flight (MANDATORY, before any engine work)

### 0a. Show the one-time model-routing advisory (if this is the first run)

Check for sentinel: `~/Paperwik/.claude/skills/state/research-advisory-shown`.
If it does NOT exist:

```
TIP: Paperwik's research engine always runs on Sonnet (for synthesis) and
Haiku (for search). This is by design -- it keeps your weekly Claude budget
intact. If you've picked Opus in the model dropdown, that's fine; it doesn't
change what the research itself uses. (This tip only shows once.)
```

Then create the sentinel file (empty is fine) so this advisory never repeats.

### 0b. Up-front cost/time confirmation gate

Show the user an estimate and ASK before proceeding:

```
A research run on "<topic>" will:
  - take ~8-12 minutes of wall-clock time
  - consume roughly 2-4 hours of your weekly Sonnet budget (you have 40-80)
  - use roughly 30-50 prompts of your 5-hour window (you have ~45)
  (Haiku time for web search is cheaper and doesn't count against Sonnet.)

If you're already close to your weekly cap, you may want to wait. Proceed? (yes/no)
```

If the user says no, stop. If they say yes or something equivalent, continue.

### 0c. Enforce Windows wake-lock

Invoke `scripts/wake_lock.py enforce` before the engine starts. Wrap the
4-phase engine in `try`; in `finally`, invoke `scripts/wake_lock.py release`.
Non-negotiable: dad's laptop will sleep during the run without this.

```bash
PAPERWIK_PLUGIN="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/marketplaces/paperwik}"
uv run "$PAPERWIK_PLUGIN/scripts/wake_lock.py" enforce
```

---

## Why This Exists

Gemini Deep Research produces excellent 5,000-word synthesis documents via
its web UI -- but that's a 5-step manual workflow per research task (copy
prompt, paste into UI, wait 20-60 min, download, drag into Inbox). This
skill replaces that workflow with an in-session capability that uses only
Claude Code's built-in tools.

The output is a markdown file matching the format paperwik's `ingest` skill
already absorbs -- so the existing ingestion flow works without modification.

---

## Design Principles

1. **Claude-only.** No external LLM APIs (Gemini, OpenAI). No external
   search APIs (Brave, Exa, Tavily, Perplexity). Orchestration, retrieval,
   synthesis, and verification all run through Claude Code's native
   primitives. Users need ONLY their Claude Code subscription. (paperwik
   decision equivalent of CoWork #304)

2. **Hierarchical synthesis via Task subagents.** A 5,000-word document is
   NOT produced by asking for 5,000 words. It's produced by spawning one
   Task subagent per section, each with an isolated fresh context window
   containing only the sources relevant to that section. This defeats
   context rot and is the direct analog of Gemini Deep Research's
   proprietary hierarchical logic. (paperwik decision equivalent of CoWork #306)

3. **Hybrid model routing (paperwik-specific, DEVIATES from CoWork #304).**
   PLANNER, SECTION WRITERS, and EDITOR pin `model: "sonnet"`. SEARCHER
   (bulk relevance filtering -- pattern-matching, not synthesis) pins
   `model: "haiku"`. Stretches Pro's 40-80 weekly Sonnet hours by ~1.5-2x
   and cuts wall-clock ~30%. Every Task call explicitly specifies `model:`
   -- NEVER rely on parent inheritance, because if the user has Opus
   selected in the Desktop picker (possible on Pro as of Opus 4.7 GA
   2026-04-16), inheritance would dispatch to Opus and burn budget ~3x
   faster.

4. **Default 3 section writers, not 10.** Pro has ~45 prompts per 5-hour
   window. A 3-writer run fits comfortably inside one window. Expand to
   8-12 only if the user explicitly asks for a longer document. (paperwik
   decision #438)

5. **Citation verification is mandatory, not optional.** LLMs invent
   citations. Prompt engineering cannot fix this. Every claim in the final
   document passes a post-synthesis verification step that compares it to
   the source it cites. Mismatches force a micro-correction pass. See
   `references/sanitizer_pattern.md`.

6. **File-based handoff contract.** The engine exposes exactly one output:
   a markdown file dropped into `~/Paperwik/Vault/Inbox/`. **No other skill,
   hook, or script may depend on this engine's internals.** When a native
   Research Mode API stabilizes (12-24 month horizon), the backend swaps
   with a single API call; nothing downstream changes. (paperwik decision
   equivalent of CoWork #307; see `references/backend_swap_contract.md`)

7. **Transitional scaffolding mindset.** This engine is expected to be
   retired when native primitives stabilize. Every component is swappable.

---

## The 4-Phase Loop

### Phase 1 — Plan (Decomposer, Sonnet)

Spawn ONE Task subagent with `model: "sonnet"`:

```
Agent({
  description: "Research planner for <topic>",
  subagent_type: "general-purpose",
  model: "sonnet",
  prompt: <planner prompt from references/planner_prompt.md with topic substituted>
})
```

Requirements:
- 10-20 sub-questions (planner's job to decompose)
- 3-12 sections in the outline (default 3 for paperwik; the planner MUST
  respect the user's section-count preference if expressed)
- Each section has a `source_routing_hints` field telling the Searcher
  which sub-questions' results should feed this section

The planner does NOT execute any searches. Planning first, searching second.
See `references/planner_prompt.md` for the full prompt contract.

Write plan.json to `~/Paperwik/.claude/skills/state/deep-research/runs/<run_id>/plan.json`.

### Phase 2 — Search (Retriever, Haiku)

Spawn ONE Task subagent with `model: "haiku"`:

```
Agent({
  description: "Research searcher -- relevance filtering for <topic>",
  subagent_type: "general-purpose",
  model: "haiku",
  prompt: <searcher prompt from references/search_contract.md with plan.json>
})
```

For each sub-question:
1. Run Claude Code's `WebSearch` tool
2. Select top 3-5 promising URLs
3. `WebFetch` each URL, extract clean markdown
4. Chunk each document via `scripts/chunk_text.py` (~500 tokens per chunk)
5. Assign each chunk a unique alphanumeric ID (format: `s{section_id}_c{n}`)
6. Route each chunk to the section(s) its sub-question feeds

Output: `chunks.json` in the run directory. Typical volume: 20-50 searches
per run; 30-80 chunks in the final filtered set.

See `references/search_contract.md`.

### Phase 3 — Synthesize (Section Writers, Sonnet, in parallel)

Before spawning, write `pending_sections.json` to the run directory listing
the `section_id`s the Editor is waiting for.

For each section in the outline, spawn a Task subagent IN PARALLEL:

```
Agent({
  description: "Section writer: <section title>",
  subagent_type: "general-purpose",
  model: "sonnet",
  prompt: <section writer prompt from references/section_writer_prompt.md,
           with section_id, title, intent, target length, and chunks
           routed to this section substituted>
})
```

Spawn all sections in ONE message for parallel execution. Paperwik default
is 3 subagents; max 10 (Claude Code hard cap). Each subagent writes its
draft to `drafts/<section_id>.md` in the run directory.

**Do NOT poll for completion.** The SubagentStop hook
(`plugin/hooks/subagent_stop.py`) detects draft-file completion via the
filesystem sentinel pattern (bug #7881 workaround) and writes a
`ready_to_stitch` sentinel when all drafts are in. Wait for the sentinel
to exist before proceeding to Phase 4.

See `references/section_writer_prompt.md`.

### Phase 4 — Stitch + Sanitize (Editor, Sonnet)

Once the `ready_to_stitch` sentinel appears:

1. **Concatenate** drafts in outline order into a single document with H2
   section headers interpolated.
2. **Run the Sanitizer** (`scripts/sanitizer.py`): for every `[chunk_id]`
   citation in the text, compare the claim against the source chunk's text
   via deterministic fuzzy matching. AMBIGUOUS and FAIL cases escalate to
   LLM-as-judge Task subagents pinned to `model: "haiku"` (lightweight
   classification). See `references/sanitizer_pattern.md`.
3. **Contradiction pass** (optional): extract atomic claims across
   sections; surface direct contradictions in a dedicated `## Contradictions`
   H2 rather than silently resolving them.
4. **Generate the filename** via `scripts/slug_from_topic.py` -- produces
   dad-readable `"Cognitive Health Strategies - 2026-04-24.md"` style.
5. **Validate output format** via `scripts/output_validator.py`: YAML
   frontmatter + H2/H3 structure + Sources table presence. Blocks write on
   any violation.
6. **Write** the final document to `~/Paperwik/Vault/Inbox/<slug>.md`.

The `ingest` skill (or a user saying "ingest this") will pick it up from
there.

---

## Output Format Contract (NON-NEGOTIABLE)

Per paperwik decision equivalent of CoWork #305, every output MUST have:

**1. YAML frontmatter:**
```yaml
---
topic: "<user's topic>"
date: "YYYY-MM-DD"
research_tool: "paperwik-research-skill/v0.4.0"
cost: <null | float dollars if measurable>
sources_count: <integer>
---
```

**2. Body with standardized H2/H3 headers** -- required sections:
- `## Context` -- what question this answers, why it matters
- `## Findings` -- the substantive synthesis (this holds most of the word count)
- `## Contradictions` -- any inter-source conflicts surfaced (omit if none)
- `## Gaps & Caveats` -- what the research could not resolve, single-source claims,
  unverified assertions

**3. Closing Sources table:**
```markdown
## Sources

| ID | URL | Title | Access date |
|----|-----|-------|-------------|
| s1_c1 | https://... | ... | 2026-04-24 |
...
```

`scripts/output_validator.py` enforces this contract; the skill refuses to
write an output that violates it.

---

## State Layout

All per-run state lives under:

```
~/Paperwik/.claude/skills/state/deep-research/
|-- runs/
|   `-- <run_id>/
|       |-- plan.json              # Phase 1 output
|       |-- chunks.json            # Phase 2 output (all retrieved + filtered)
|       |-- pending_sections.json  # list of section_ids for Editor to wait on
|       |-- drafts/                # Phase 3 per-section outputs
|       |   |-- s1.md
|       |   `-- ...
|       |-- subagent_registry.json # audit-only (bug #7881 -- don't depend on it)
|       |-- ready_to_stitch        # sentinel written by subagent_stop.py hook
|       |-- verification_report.json  # Sanitizer output
|       `-- final.md               # Phase 4 final document (also copied to Inbox)
|-- latest_run_id.txt
`-- research-advisory-shown        # sentinel for Phase 0a (one-time advisory)
```

---

## Invariants (Do Not Violate)

1. **No polling.** The main session never loops asking "is the subagent
   done?" Use the filesystem sentinel (`ready_to_stitch`) exclusively.
2. **One engine entrypoint.** This SKILL.md is the only way to invoke the
   engine. Other skills/scripts must not call internal phases directly.
3. **No external API keys required.** If you find yourself wanting to
   require one, stop -- file it as an RFC against the architecture instead.
4. **Output contract is fixed.** Change the decision first if the format
   needs to evolve. Never silently drift.
5. **Every Task call pins `model:`.** Never rely on parent-model
   inheritance. Sonnet for PLANNER/WRITERS/EDITOR; Haiku for SEARCHER and
   the Sanitizer's LLM-judge calls.
6. **Always show Phase 0 advisories + cost gate** before engaging the
   engine. Non-technical users have zero budget intuition.

---

## DO NOT TRIGGER on these phrases

The `research` skill is the heavy-weight option. These other requests
should NOT trigger it:

- "ingest this" / "add this source" -- that's the `ingest` skill
- "what is X" / "explain X" / "summarize X" -- normal Q&A, not a research run
- "find X in my wiki" -- that's a wiki query, not new research
- "undo that" -- that's the `undo` skill
- "scrub X from my wiki" -- that's the `redact` skill
- "check my wiki for problems" / "lint" -- that's the `lint` skill
- "how do I use Paperwik" / "what can you do" -- that's the `paperwik-help` skill
- "rebuild the index" -- that's the `rebuild-index` skill

If the user asks something that could go either way, default to the
lighter-weight skill (or plain Q&A) and only invoke `research` when the
request is unambiguous: "research X thoroughly", "do deep research on Y",
"write me a long writeup on Z", "produce a research doc on X".

---

## Hook Registration

The SubagentStart and SubagentStop hooks live at `plugin/hooks/subagent_{start,stop}.py`
and are registered in the vault's `.claude/settings.local.json` (NOT in
plugin.json, per Claude Code bug #10412 which causes Stop-style hooks
registered via plugin.json to silently fail).

The paperwik installer (step c4 in `install.ps1`) merges the hook stanzas
into the vault's `settings.local.json` at install time, preserving all
other keys (user-added permissions, other hooks). No manual JSON editing
required.

The hook scripts are stdlib-only (no external deps), but all paperwik
scripts use the `uv run` pattern for consistency.

---

## Version History

- **v0.4.0 (2026-04-24, paperwik action items #414-422)** -- Initial
  paperwik port from CoWork's deep-research v1. Adaptations: skill renamed
  to `research`; drop target `~/Paperwik/Vault/Inbox/`; hybrid model
  routing (Sonnet synthesis / Haiku retrieval); default 3 section writers;
  wake-lock + slug generator; up-front cost/time gate + one-time advisory;
  explicit `model:` pinning in every Task call; hook registration moved to
  vault-level `settings.local.json` per bug #10412.
