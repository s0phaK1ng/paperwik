# Phase 1 Planner — Prompt Contract

Action item **A2**. Used by the main session to decompose a research topic into
sub-questions and a section outline BEFORE any web search fires.

---

## Input

A single string: the user's research topic. May be a single sentence or a
paragraph. Examples:

- "Deep research agents in 2026 — architecture, frameworks, how to build one in Claude Code"
- "Obsidian vs Notion for personal knowledge management with AI integration"
- "What are the current best practices for zero-downtime PostgreSQL upgrades on self-hosted infrastructure"

## Output

A single JSON object matching this schema exactly. No prose, no markdown
fences, no explanation — just the JSON object:

```json
{
  "topic": "<verbatim copy of the user's topic>",
  "framing": "<one or two sentences stating the angle this research will take>",
  "sub_questions": [
    "<specific, web-searchable question #1>",
    "<specific, web-searchable question #2>",
    ...
  ],
  "section_outline": [
    {
      "section_id": "s1",
      "title": "<H2 heading text for this section>",
      "intent": "<one sentence describing what this section must establish>",
      "source_routing_hints": ["<sub-question text that feeds this section>", "..."]
    },
    ...
  ],
  "expected_output_words": <integer between 3000 and 8000>,
  "notes": "<optional: planner's self-commentary on tradeoffs or risks>"
}
```

### Hard requirements

- **Sub-questions:** minimum 10, maximum 20. Each must be a concrete web-searchable
  question — not a topic heading, not an abstract. Example of good:
  *"What is the default timeout in milliseconds for Claude Code's PreToolUse hook
  in version 2.x?"* Example of bad: *"Claude Code hook system"*.
- **Sections:** minimum 6, maximum 12. Each section gets its own parallel synthesis
  subagent later, and the total word count divides across sections — so fewer
  sections = longer per-section drafts (up to ~800 words) and more sections = shorter
  (down to ~400 words). Default to 8–10 for a balanced document.
- **Source routing hints:** every section must list AT LEAST ONE sub-question that
  feeds it. A sub-question can feed more than one section. Every sub-question
  should appear in at least one section's routing hints, or the planner is wasting
  a search budget.
- **Section IDs** follow the format `s<integer>` starting at `s1`, strictly sequential.
- **`expected_output_words`** is the target for the final document after stitching.
  Default to 5000. Raise to 6000–8000 only if the topic is genuinely unusually broad.

### Mandatory sections

Every plan must include these sections (the titles may be adapted for voice, but
the intent must match):

- **Context** — why this question, what triggered it, what decision it informs
- **Findings** — the substantive body (may span multiple sections in the outline;
  the planner decides how to split)
- **Gaps & Caveats** — what the research could not resolve, single-source claims,
  areas of ambiguity

**Contradictions** section is conditional: include it ONLY if the planner anticipates
that sources may conflict (most technical or policy topics will; pure factual
compilations often won't). The Sanitizer adds or removes this section based on
what the actual synthesis surfaces.

---

## The Prompt

The main session executes the Planner phase by running this prompt against
itself (or a dedicated Task subagent). The prompt is:

```
You are the Planner in a deep-research pipeline. Your job is to decompose the
user's research topic into a set of sub-questions and a section outline — but
you DO NOT execute any searches. Planning is strictly separated from retrieval.

Read the design principles of this pipeline:
- Every sub-question must be independently web-searchable.
- The section outline drives parallel section-writer subagents downstream.
  Each section will be written with ONLY the sources its routing hints pull in.
- Good plans produce diverse, complementary sub-questions that cover the topic
  from multiple angles (technical, economic, operational, historical, comparative)
  where relevant.
- Bad plans repeat the same question in different words, or propose sections
  that can't actually be filled by any of the sub-questions.

Topic: <INSERT USER'S TOPIC VERBATIM>

Return ONLY the JSON object described in the schema below. No prose. No
markdown fences. If the topic is ambiguous, make a reasonable assumption
and note it in the "notes" field — do not ask clarifying questions, do not
return an error.

<INSERT JSON SCHEMA FROM THIS DOC>
```

---

## Few-Shot Examples

### Good plan

**Input:** "How should I choose between PostgreSQL and SQLite for a single-user desktop knowledge management app in 2026?"

```json
{
  "topic": "How should I choose between PostgreSQL and SQLite for a single-user desktop knowledge management app in 2026?",
  "framing": "Compare the two databases across the dimensions that matter for a single-user desktop-bundled deployment: bundling/installation friction, concurrent access, vector search support, backup/portability, and maintenance burden.",
  "sub_questions": [
    "What is the installed-size and packaging footprint of SQLite vs PostgreSQL for Windows desktop applications in 2026?",
    "How does sqlite-vec compare to pgvector on query latency and recall for a vector index of 1-10 million rows?",
    "What concurrency guarantees does SQLite WAL mode provide for a single writer plus multiple readers?",
    "Which popular desktop applications (e.g., Obsidian, Signal, browser bookmarks) have migrated from PostgreSQL to SQLite or vice versa, and why?",
    "What is the operational overhead of running an embedded PostgreSQL in a desktop app (e.g., via libpq + postgres.app)?",
    "How portable is a SQLite database file across Windows, macOS, and Linux compared to a PostgreSQL dump?",
    "What backup and rollback strategies work for SQLite files opened by a long-running process?",
    "Does pgvector outperform sqlite-vec on HNSW index builds for a 500K-row corpus, and by how much?",
    "What Windows Credential Manager or DPAPI integrations exist for SQLite vs PostgreSQL connection strings?",
    "How do schema migrations compare — Alembic against PostgreSQL vs sqlite-utils or hand-rolled for SQLite?"
  ],
  "section_outline": [
    {"section_id": "s1", "title": "Context", "intent": "Frame the decision: single-user, desktop, Windows-first, knowledge management scale.", "source_routing_hints": []},
    {"section_id": "s2", "title": "Bundling & install", "intent": "Compare installation friction and package size.", "source_routing_hints": ["installed-size and packaging footprint", "operational overhead of running an embedded PostgreSQL"]},
    {"section_id": "s3", "title": "Vector search comparison", "intent": "Evaluate sqlite-vec vs pgvector for the wiki's retrieval needs.", "source_routing_hints": ["sqlite-vec compare to pgvector on query latency", "pgvector outperform sqlite-vec on HNSW"]},
    {"section_id": "s4", "title": "Concurrency & durability", "intent": "Address the single-writer / multiple-reader scenario and crash safety.", "source_routing_hints": ["WAL mode", "backup and rollback strategies"]},
    {"section_id": "s5", "title": "Portability & backup", "intent": "Compare file-copy portability vs dump/restore.", "source_routing_hints": ["portable is a SQLite database file", "backup and rollback"]},
    {"section_id": "s6", "title": "Real-world precedent", "intent": "Reference concrete desktop apps that chose one or the other.", "source_routing_hints": ["popular desktop applications"]},
    {"section_id": "s7", "title": "Operational burden", "intent": "Day-to-day maintenance comparison.", "source_routing_hints": ["operational overhead", "schema migrations compare"]},
    {"section_id": "s8", "title": "Recommendation", "intent": "Synthesize — which database and why.", "source_routing_hints": []},
    {"section_id": "s9", "title": "Gaps & Caveats", "intent": "Flag unresolved dimensions and single-source claims.", "source_routing_hints": []}
  ],
  "expected_output_words": 5000,
  "notes": "Sections s1, s8, s9 have empty source_routing_hints because they are framing/synthesis sections that draw from all retrieved sources; the section-writer prompts will receive the full chunk index for those."
}
```

### Bad plan (to avoid)

- Sub-questions that are just topic headings ("database comparison", "vector search")
- Sections that the sub-questions can't fill ("Section: Migration scripts" with zero routing hints)
- More than 20 sub-questions (budget blown; synthesis gets noisy)
- Fewer than 6 sections (each section would have to absorb too much context — violates the hierarchical-synthesis principle)
- Redundant sub-questions that phrase the same question three ways

---

## Error Handling

If the planner returns non-JSON or JSON that fails schema validation:
1. Re-run the prompt with an added directive: `"Your previous output was
   rejected by the schema validator. Error: <error>. Return ONLY the JSON
   object, no prose, no fences."`
2. If the second attempt also fails, log the failure to
   `.claude/skills/state/deep-research/runs/<run_id>/planner_errors.log` and
   halt the run with a message to the user explaining that the Planner
   phase failed — do NOT proceed to Phase 2 with a broken plan.

---

## Version History

- **v1 (2026-04-22, action item A2)** — Initial contract. Schema, mandatory
  sections, few-shot examples, error handling. Ported verbatim from CoWork
  source at 2026-04-24 (action item #408).
