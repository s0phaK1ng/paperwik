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
  model: "sonnet",
  prompt: <TEMPLATE WITH PLACEHOLDERS FILLED>
})
```

**IMPORTANT (paperwik-specific):** the `model: "sonnet"` parameter is
MANDATORY in every section-writer Task call. Never omit it. Never rely on
parent-model inheritance — if the user's main chat is set to Opus (Pro tier
now exposes Opus 4.7 in the model picker), inheritance would dispatch
subagents to Opus and burn the user's weekly budget ~3x faster than the
intended Sonnet routing.

All section subagents are spawned in a single message for parallel execution
(Claude Code's 10-subagent concurrency cap means 3–12 sections spawn in
one batch; paperwik default is 3).

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
3. Cite every factual claim inline with its chunk ID. A claim that synthesizes
   multiple sources cites all of them: [s3_c1, s3_c4, s3_c7].
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

After writing the section, also produce a SHORT summary (max 2 sentences)
of the key claims you made. Format the full response as:

---BEGIN_SECTION---
<the section body markdown>
---END_SECTION---

---BEGIN_SUMMARY---
<2-sentence summary of the key claims>
---END_SUMMARY---
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

The main session reads the section writer's response and:
1. Extracts the `---BEGIN_SECTION---` to `---END_SECTION---` block
2. Writes it to `.claude/skills/state/deep-research/runs/<run_id>/drafts/<section_id>.md`
3. Extracts the `---BEGIN_SUMMARY---` to `---END_SUMMARY---` block
4. Appends it to `drafts/_summaries.json` for the Editor's reference

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
  Ported from CoWork source at 2026-04-24 (action item #408). The only
  paperwik-specific adaptation is the MANDATORY `model: "sonnet"` directive
  in the Invocation section — rationale in SKILL.md.
