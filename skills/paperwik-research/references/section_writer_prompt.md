# Phase 3 Section Writer — Subagent Prompt Template

Action item **A4**. Used by the main session when spawning one Task subagent
per section of the outline. Each subagent runs in an isolated fresh context
window and writes ONE section of the final document.

---

## Invocation

The main session spawns each section writer via the `Task` tool (or
equivalent Agent tool, mapped to `general-purpose` subagent_type). The
prompt passed to each subagent is the template below with placeholders
filled in.

```
Agent({
  description: "Section writer: <section title>",
  subagent_type: "general-purpose",
  prompt: <TEMPLATE WITH PLACEHOLDERS FILLED>
})
```

All section subagents are spawned in a single message for parallel execution
(Claude Code's 10-subagent concurrency cap means 8–12 sections spawn in
one batch).

---

## The Prompt Template

```
You are the Section Writer for a deep research document. You are responsible
for ONE section only. Other section writers are working on other sections
simultaneously — do not reference them, do not try to cover their scope,
do not stitch your work into a larger narrative. The Editor (Phase 4)
handles that.

## The research topic

<TOPIC>

## The full document's outline (for context — DO NOT fill in other sections)

<OUTLINE_JSON>

## YOUR section

- section_id: <SECTION_ID>
- title: "<SECTION_TITLE>"
- intent: "<SECTION_INTENT>"
- target length: <TARGET_WORDS> words (hard range: <MIN_WORDS>-<MAX_WORDS>)

## Your sources

You have exactly <N_CHUNKS> source chunks available for this section. They
are listed below with their chunk IDs. You MUST cite every factual claim
with at least one chunk ID in square brackets, e.g., [s3_c7].

If you make a claim you cannot ground in your chunks, omit it — do not
invent. If a claim genuinely has no source support but feels important,
state it as a gap: "Available sources do not address whether X."

<CHUNKS_LIST>
# Example chunk entry:
# [s3_c1] URL: https://example.com/doc — Title: "..."
# Text: The full ~500-token passage of source text goes here.

## Writing directives

1. Open with a topic sentence that directly states what this section
   establishes (matches the intent above).
2. Use H3 subheadings (###) freely if it improves readability, but do NOT
   use H2 — that level is reserved for the overall document structure.
3. **Citation discipline (revised v1.1, 2026-04-27):** Cite each atomic claim
   with the SINGLE chunk ID that most directly supports its specific phrasing.
   Use a multi-citation list (e.g., `[s3_c1, s3_c4]`) ONLY when 2+ chunks each
   independently support the same atomic claim — not when chunks together
   contribute background context for adjacent ideas.

   **Good (single-chunk, claim and source align tightly):**
   > Brave Search costs $5 per 1,000 queries on the basic tier [s3_c1].

   **Bad (multi-citation list where only one chunk supports the specific claim):**
   > Brave Search costs $5 per 1,000 queries [s3_c1, s3_c4, s3_c7].
   *(s3_c4 and s3_c7 mention Brave but don't independently establish the price.)*

   **Good (multi-citation when each chunk independently supports the same claim):**
   > Three independent reviews recommend Brave over Tavily for cost-efficiency
   > [s3_c1, s3_c4, s3_c7].

   If you find yourself wanting to cite "background" chunks alongside the load-
   bearing one, write a separate sentence about the background and cite it
   there. Don't pile citations onto the load-bearing claim.
4. Prefer concrete numbers, names, and dates over vague language. If the
   sources say "$5 per 1000 queries", say that — not "affordable".
5. Surface contradictions between sources IN THE TEXT: "Source [s3_c2]
   reports 81% accuracy; source [s3_c5] reports 71%. The discrepancy likely
   reflects different test corpora."
6. Do NOT write a conclusion paragraph that summarizes the whole document —
   just end when the section's intent is established.
7. Do NOT invent URLs, titles, or attribute quotes to sources you don't have.
8. Do NOT speculate beyond what the sources support. Hedging language
   ("may", "is likely", "according to one report") is fine when the
   evidence is thin.

## Output channel — INLINE RETURN (DEFAULT)

You do NOT have file-write permission in your sandbox on this Claude Code
installation. Do NOT attempt `Write`, `Bash`, `PowerShell`, or any other
write tool to persist your section — they will be denied. Your deliverable
is returned INLINE in your response, formatted EXACTLY as the four-marker
block below. The parent agent (the orchestrator) parses the markers and
writes the files; you do not.

## Output format

Write ONLY the section body as markdown. Do NOT include the H2 title
(the Editor adds that). Do NOT include YAML frontmatter. Do NOT include
acknowledgments, introductions, or conclusions that reference the larger
document.

Begin your output with the first sentence of the section. End when the
section is complete.

## Before you submit

- Count your words. If you are outside <MIN_WORDS>-<MAX_WORDS>, adjust.
- Verify every inline citation ID appears in your chunks list.
- Verify no inline citation is fabricated.

After writing the section, produce a SHORT summary (max 2 sentences) of
the key claims you made, plus a metadata block. Format the full response
EXACTLY as the four-marker block:

---BEGIN_SECTION---
<the section body markdown>
---END_SECTION---

---BEGIN_SUMMARY---
<2-sentence summary of the key claims>
---END_SUMMARY---

---METADATA---
word_count: <integer count of your section body>
distinct_chunks_cited: <integer count of distinct chunk IDs you used>
chunk_ids_cited: <comma-separated list of chunk IDs you used>
---END_METADATA---

No commentary outside those three blocks. The orchestrator will run
`scripts/parse_section_response.py` against your raw response to extract the
SECTION, SUMMARY, and METADATA blocks and write the corresponding files.
```

---

## Placeholder Substitutions

The main session substitutes before invoking:

| Placeholder | Value |
|-------------|-------|
| `<TOPIC>` | `plan.topic` |
| `<OUTLINE_JSON>` | Pretty-printed `plan.section_outline` |
| `<SECTION_ID>` | Current section's `section_id` (e.g., `s3`) |
| `<SECTION_TITLE>` | Current section's `title` |
| `<SECTION_INTENT>` | Current section's `intent` |
| `<TARGET_WORDS>` | `plan.expected_output_words / len(section_outline)` rounded to nearest 50 |
| `<MIN_WORDS>` | `<TARGET_WORDS> * 0.75` |
| `<MAX_WORDS>` | `<TARGET_WORDS> * 1.25` |
| `<N_CHUNKS>` | Number of chunks routed to this section |
| `<CHUNKS_LIST>` | Formatted list of chunks (ID, URL, title, full text) — see format below |

### Chunk list format

Each chunk in `<CHUNKS_LIST>` is formatted as:

```
[s3_c1] URL: https://example.com/...  — Title: "Article Title Here"
Sub-question origin: "What is X?"

<FULL PASSAGE TEXT, ~500 TOKENS, VERBATIM FROM chunks.json>

---
```

Separator `---` between chunks. No chunk count limit, but realistic sections
have 5–15 chunks; very thin sections (2–3 chunks) should be flagged to the
user BEFORE synthesis runs.

---

## Output Capture

The main session reads the section writer's response and runs:

```
uv run scripts/parse_section_response.py \
    --run-dir <RUN_DIR> \
    --section-id <SECTION_ID> \
    --response-file <path-to-captured-response>
```

The parser:
1. Extracts the `---BEGIN_SECTION---` to `---END_SECTION---` block and writes
   `<RUN_DIR>/drafts/<SECTION_ID>.md`
2. Extracts the `---BEGIN_SUMMARY---` to `---END_SUMMARY---` block and writes
   `<RUN_DIR>/drafts/_summaries/<SECTION_ID>.txt`
3. Extracts the `---METADATA---` block and writes
   `<RUN_DIR>/drafts/_metadata/<SECTION_ID>.json`
4. Exits 0 if all three blocks parse cleanly; exits nonzero if any are missing
   or malformed (orchestrator should re-spawn that section).

## Fallback: file-write contract (DEPRECATED)

> **DEPRECATED as of v2 (2026-04-27, D2R-4).** Preserved here for historical
> context only. Earlier versions of this prompt directed the section-writer
> subagent to call `Write` itself to persist `drafts/<section_id>.md` and a
> `drafts/_summaries.json` entry. D2 (2026-04-27) revealed that subagents on
> this Claude Code installation have no write permission to the run-dir; 9 of
> 10 first-attempt agents failed silently because of this. The inline-return
> path above is the new default and works regardless of sandbox state. Do not
> rely on the file-write path for new code.

---

## Special Section Types

### Framing sections (s1 Context, sN Recommendation, sN-1 Gaps & Caveats)

These typically have zero or few routed chunks because their job is to
frame or synthesize rather than present new findings. For these sections,
the `<CHUNKS_LIST>` includes ALL chunks from the run (not just routed
ones), and the prompt adds:

> "This is a framing/synthesis section. You may draw on any chunk from the
> full corpus below. Keep it focused on the section's intent — do not
> duplicate what other sections establish."

### Contradictions section (optional, conditional)

If the Editor detects inter-section contradictions during Phase 4, it
synthesizes this section itself from the other sections' `_summaries.json`.
It does NOT spawn a dedicated section-writer subagent for it.

---

## Version History

- **v1 (2026-04-22, action item A4)** — Initial template. Citation contract,
  output format, placeholder substitutions, framing-section exception.
- **v1.1 (2026-04-27)** — Citation discipline directive #3 tightened to require
  single chunk per atomic claim with good-vs-bad examples (DR11-7).
- **v2 (2026-04-27, D2 retrospective, D2R-4)** — Inline-return is the default
  deliverable channel; file-write path moved to a "Fallback (DEPRECATED)"
  section. New METADATA block (`word_count`, `distinct_chunks_cited`,
  `chunk_ids_cited`) joins SECTION + SUMMARY in the response. Output capture
  now goes through `scripts/parse_section_response.py` rather than the parent
  hand-extracting blocks. Closes the AGENT_ONBOARDING.md "Pending follow-ups"
  item from the 2026-04-27 session.
