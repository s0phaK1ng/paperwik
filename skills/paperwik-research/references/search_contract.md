# Phase 2 Searcher — Retrieval Contract

Action item **A3**. Executed by the main session after Phase 1 produces a plan.

---

## Input

The JSON plan produced by Phase 1 (see `planner_prompt.md`). Specifically:
- `sub_questions[]` — drives the WebSearch calls
- `section_outline[].source_routing_hints[]` — maps retrieved chunks to sections

## Output

When the orchestrator spawns multiple search subagents in parallel, each one
writes its own file at:

```
.claude/skills/state/deep-research/runs/<run_id>/chunks/searcher_<N>.json
```

After all searchers complete, the orchestrator runs `scripts/merge_chunks.py`
which normalizes, de-duplicates, sorts, and writes the unified
`runs/<run_id>/chunks.json`.

### Canonical chunk schema (STRICT)

**Each searcher subagent's output MUST be a JSON list of objects matching
this schema EXACTLY — no key renames, no nested envelopes, no extras.**

```json
[
  {
    "chunk_id": "s3_c1",
    "section_id": "s3",
    "source_url": "https://example.com/article",
    "source_title": "Article Title Here",
    "fetched_at": "2026-04-27T15:30:00Z",
    "sub_question_origin": "What is X?",
    "text": "<~500-token passage of clean text — the actual chunk body>"
  },
  ...
]
```

The seven keys are non-negotiable. The merge step (`scripts/merge_chunks.py`)
will normalize known historical drift (key renames, nested `chunks` envelope —
see the script's docstring for the four variants it accepts) but will fail
loudly on unmappable variants. **Drift is wasted work; produce canonical JSON
the first time.**

Per-key requirements:
- **`chunk_id`**: `s<section>_c<n>` where `<section>` matches `section_id` and
  `<n>` is a positive integer counting per section. Unique within the searcher's
  output (the merger globally de-duplicates across searchers).
- **`section_id`**: Must match a section in the run's `plan.json`.
- **`source_url`**: Absolute URL (`http://` or `https://`).
- **`source_title`**: Page title or "Unknown" if not extractable. Not empty.
- **`fetched_at`**: ISO-8601 UTC timestamp. Approximate-now is fine.
- **`sub_question_origin`**: The sub-question text from `plan.json` that drove
  this fetch. `"(not recorded)"` is acceptable as a fallback but discouraged.
- **`text`**: The chunk body. ~500 tokens preferred but the chunker decides.
  Must not be empty.

The companion `sources.json` (deduplicated metadata) is OPTIONAL — the
Sources table in the final document can be reconstructed from `chunks.json`
during stitching, so this file is only written if the orchestrator wants it
for debugging.

---

## The Protocol

### Step 1 — Run WebSearch per sub-question

For each `sub_question` in the plan, invoke Claude Code's `WebSearch` tool.

```
WebSearch({ query: "<sub_question>" })
```

From each search result, select the top 3–5 URLs that are most likely to
answer the sub-question. Heuristics for selection:
- Prefer authoritative domains (official docs, peer-reviewed, well-known
  publications) over SEO-optimized blog aggregators
- Prefer recent sources (2025–2026) over older material — unless the topic
  is historical
- Deduplicate by domain when possible (don't grab 5 URLs from the same site)
- Skip obvious content farms, login-walled previews, and Pinterest-style
  aggregators

**Budget cap:** 50 URLs TOTAL across all sub-questions. If the plan has 20
sub-questions × 5 URLs each = 100 URLs, the Searcher must prune to 50 by
scoring on source quality.

### Step 2 — WebFetch each selected URL

For each selected URL, invoke `WebFetch`:

```
WebFetch({ url: "<url>", prompt: "Extract the full body text of this page as
clean markdown. Preserve headings. Strip navigation, footers, ads,
cookie banners, subscribe-prompts, related-posts sidebars, and comment
sections. Preserve inline code blocks verbatim. Preserve tables as markdown
tables. Return ONLY the extracted content." })
```

Handle failures:
- 404 / unreachable → log to `search_errors.log`, skip
- Paywall / login wall → the WebFetch model usually returns a truncated
  stub; detect "this content is behind a paywall" substrings and drop the
  result
- Very long pages (>30K chars) → the prompt already constrains to the body;
  if the fetched content is suspiciously truncated, log a warning

### Step 3 — Chunk each fetched document

Invoke the helper script `scripts/chunk_text.py`:

```bash
uv run scripts/chunk_text.py \
    --section-id s3 \
    --source-url <url> \
    --source-title <title> \
    --sub-question-origin "<sub_question>" \
    --text-file <path-to-fetched-markdown> \
    --chunk-size-tokens 500 \
    --output-append <chunks.json>
```

The chunker assigns sequential IDs (`s<section>_c<n>`) counting per-section.

### Step 4 — Route each chunk to section(s)

After all searches and chunking complete, for each chunk decide which
section(s) it feeds using the plan's `source_routing_hints`. A chunk can
appear under multiple sections if its sub_question_origin matches multiple
hints.

Write the routed chunks to `chunks.json` in the run directory.

### Step 5 — Emit routing summary

Print (not write) a summary to stdout so the orchestrator can sanity-check
before spawning Phase 3 subagents:

```
SEARCH COMPLETE — run_id=<id>
  sub_questions executed: 12
  URLs fetched: 38 (budget: 50)
  URLs failed: 2 (see search_errors.log)
  chunks total: 67
  chunks per section: s1=0, s2=8, s3=14, s4=9, s5=11, s6=15, s7=10, s8=0, s9=0
  sections with 0 chunks: s1, s8, s9 (expected — framing/synthesis sections)
  sections with <5 chunks: none
```

If any non-framing section ends up with <5 chunks, the orchestrator must
decide: (a) run additional targeted searches for that section's routing hints,
or (b) accept and let the section writer work from a thin source base. Default
to (a) unless the search budget is exhausted.

---

## Budget & Rate-Limit Handling

- WebSearch and WebFetch calls count against the user's Claude Code
  subscription. The engine should never exceed 50 total URL fetches per run
  without user approval for a larger run.
- If throttling is detected (search results empty, WebFetch returning
  "rate limited"), pause 30 seconds and retry once. If retry also fails,
  log and continue with partial results — do not halt the run.

---

## Version History

- **v1 (2026-04-22, action item A3)** — Initial retrieval contract. Budget
  cap, chunking invocation, routing algorithm, error handling. Depends on
  `scripts/chunk_text.py`.
- **v2 (2026-04-27, action item D2R-3, D2 retrospective)** — Added strict
  canonical chunk schema with per-key requirements. Output reshaped: each
  searcher writes its own `chunks/searcher_<N>.json`; orchestrator runs
  `scripts/merge_chunks.py` to produce the unified `chunks.json`. Closes the
  D2-surfaced problem of 4 search subagents producing 4 different shapes for
  the same logical chunk.
