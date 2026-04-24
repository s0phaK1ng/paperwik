# Phase 2 Searcher — Retrieval Contract

Action item **A3**. Executed by the main session after Phase 1 produces a plan.

---

## Input

The JSON plan produced by Phase 1 (see `planner_prompt.md`). Specifically:
- `sub_questions[]` — drives the WebSearch calls
- `section_outline[].source_routing_hints[]` — maps retrieved chunks to sections

## Output

A single file at `.claude/skills/state/deep-research/runs/<run_id>/chunks.json`
containing a list of chunk records:

```json
[
  {
    "chunk_id": "s3_c1",
    "section_id": "s3",
    "source_url": "https://...",
    "source_title": "...",
    "fetched_at": "2026-04-22T15:30:00Z",
    "text": "<~500-token passage of clean text>",
    "sub_question_origin": "<the sub-question that surfaced this source>"
  },
  ...
]
```

Plus a parallel file `sources.json` with deduplicated source metadata:

```json
[
  {"source_id": 1, "url": "https://...", "title": "...", "first_seen": "2026-04-22T15:30:00Z"},
  ...
]
```

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
  `scripts/chunk_text.py`. Ported verbatim from CoWork source at 2026-04-24
  (action item #408).
