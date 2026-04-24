# Phase 4 Sanitizer — Citation Verification Pattern

Action item **A5**. Invoked by the Editor after all section drafts are in.
Verifies that every citation in the final document is grounded in a real
source chunk, not a hallucination.

---

## Why This Exists

LLMs structurally invent citations. This cannot be fixed by prompting. It
must be fixed by a deterministic post-synthesis verification pass that
treats citation validation as a compilation error, not a writing-style
preference.

Without the Sanitizer, ~10–30% of citations in a deep research document
are subtly wrong: invented URLs, misattributed quotes, claims attached to
sources that don't actually support them. A wiki or knowledge base full of
these becomes worse than no wiki at all.

The Sanitizer's job is to fail loudly on every invalid citation and force
a micro-correction before the document leaves the engine.

---

## Input

- Every `drafts/<section_id>.md` in the run directory
- The full `chunks.json` from Phase 2 (the source of truth)
- Optional: `drafts/_summaries.json` for the contradiction pass

## Output

- A cleaned `final.md` with verified citations — all `[chunk_id]` references
  resolve to real chunks, and every claim's chunk text actually supports the
  claim
- A `verification_report.json` listing every citation checked, its score,
  and any corrections applied
- If any citation fails after correction, the entire run fails loudly — no
  silent writes of broken documents

---

## The Algorithm

### Step 1 — Concatenate drafts in outline order

Read drafts/s1.md, s2.md, ... in the order defined by `plan.section_outline`.
Interpolate the H2 `## <title>` header before each section's body.

### Step 2 — Extract every citation

Parse the concatenated draft. Every `[chunk_id]` or `[chunk_id, chunk_id, ...]`
is a citation instance. For each instance, capture:
- The chunk ID(s) cited
- The surrounding sentence (the "claim") — extend 1 sentence back from the
  citation to its nearest sentence-ending punctuation
- The section it appears in

### Step 3 — For each (claim, chunk_id) pair, run deterministic verification

**Fuzzy match:** use `rapidfuzz.partial_ratio(claim, chunk.text)` to score
how well the claim's key phrases appear in the cited chunk.

- Score ≥ 70 → **PASS** (claim is strongly grounded)
- Score 40–69 → **AMBIGUOUS** (escalate to Step 4)
- Score < 40 → **FAIL** (escalate to Step 4)

Additionally: extract noun phrases from the claim (via spaCy if available, or
simple regex fallback). For each noun phrase, check if it appears (exact or
stem match) in the chunk. A claim with zero noun-phrase overlap is
automatically AMBIGUOUS regardless of fuzzy score.

### Step 4 — LLM-as-judge for AMBIGUOUS and FAIL cases

For each flagged claim, spawn a lightweight Task subagent with this prompt:

```
You are a citation verifier. Given a CLAIM and a SOURCE passage, return
one of three verdicts:

SUPPORTED — the source directly supports the claim
PARTIAL   — the source is related but does not directly support the specific claim as stated
CONTRADICTED — the source contradicts the claim
UNRELATED — the source is about a different topic

CLAIM: "<the sentence containing the citation>"
SOURCE: "<the chunk's full text>"

Return a single line: "VERDICT: <one of the four> | REASON: <one sentence>"
```

**Paperwik-specific:** this LLM-judge Task call MUST use `model: "haiku"` —
it's a lightweight classification task called many times per run, ideal for
Haiku 4.5's speed + cost profile. Do NOT omit the model parameter.

Interpret the verdict:
- **SUPPORTED** → accept, mark PASS
- **PARTIAL** → accept with caveat: the citation stays but a `†` marker is
  appended, and the verification_report notes "partial support"
- **CONTRADICTED** → this is a hard error, mark FAIL
- **UNRELATED** → this is a hard error, mark FAIL

### Step 5 — Correct FAIL cases

For each FAIL case:
1. **Attempt substitution** — search the full chunks.json for a chunk whose
   text has rapidfuzz score ≥ 70 against the claim. If one exists, swap the
   bad citation for the good one. Log the substitution in verification_report.
2. **Attempt weakening** — if no substitute exists, rewrite the claim to a
   weaker form grounded in what the cited chunk actually says. Spawn a
   lightweight Task subagent (model: "haiku") with:

   ```
   Rewrite the following CLAIM so that it is directly supported by the SOURCE.
   You may weaken or qualify the claim but you must not introduce new facts.
   Return ONLY the rewritten sentence.

   CLAIM: "<original sentence>"
   SOURCE: "<chunk text>"
   ```

3. **Escalate** — if neither substitution nor weakening succeeds, delete the
   claim entirely and log it. If more than 5% of claims require deletion,
   halt the run and report to the user — the whole section may need
   re-drafting.

### Step 6 — Contradiction pass (optional, conditional)

Read `drafts/_summaries.json`. For each pair of sections, ask a lightweight
Task subagent (model: "haiku"):

```
Do these two summaries contain any direct factual contradiction?

SUMMARY A: "<summary of section A>"
SUMMARY B: "<summary of section B>"

If yes, describe it in one sentence. If no, reply "NONE".
```

For every non-NONE response, surface the contradiction in a new `## Contradictions`
section appended after `## Findings` and before `## Gaps & Caveats`. Format:

```
## Contradictions

- Section **s3** (Vector search comparison) and section **s5** (Portability
  & backup) report conflicting claims on X — s3 says A [s3_c2], s5 says
  B [s5_c4]. The discrepancy likely reflects [brief analysis].
```

If the Editor added this section and no contradictions were found, omit
the `## Contradictions` section entirely.

### Step 7 — Output

Write the fully verified document to:

- `runs/<run_id>/final.md` (the authoritative output)
- `<configured_drop_target>/<dad-readable-slug> - <date>.md` (the copy the
  ingestion pipeline picks up — for paperwik this is
  `~/Paperwik/Vault/Inbox/`)

Generate `verification_report.json` next to `final.md` with entries like:

```json
{
  "total_citations": 82,
  "pass": 74,
  "partial": 6,
  "substituted": 2,
  "weakened": 0,
  "deleted": 0,
  "fatal_errors": 0,
  "run_verdict": "clean",
  "details": [
    {"claim": "...", "chunk_id": "s3_c4", "fuzzy_score": 92, "verdict": "PASS"},
    ...
  ]
}
```

`run_verdict` is `clean` if `fatal_errors == 0` and `deleted / total_citations <= 0.05`.
Otherwise `dirty` — and the engine returns an error to the user rather than
silently writing the output.

---

## Tuning Notes

- Fuzzy threshold 70 was chosen empirically for English technical prose.
  Lower (50–60) for topics with a lot of proper nouns (names, products);
  higher (75–80) for purely numerical claims.
- The LLM-as-judge prompt is deliberately terse — it's called many times per
  run, so latency and cost matter. Do not balloon it with examples. Using
  Haiku 4.5 (not Sonnet) compounds the savings.
- Substitution threshold is the same as the initial pass (70) to avoid
  the Sanitizer accepting a substitute it would itself have flagged.
- If a run consistently produces FAIL rates > 20%, the section-writer prompt
  needs tightening — probably the chunk routing is giving writers material
  they can't actually use.

---

## Version History

- **v1 (2026-04-22, action item A5)** — Initial algorithm. Fuzzy + LLM-judge
  two-tier verification, substitution + weakening corrections, contradiction
  pass. Scripts to follow: `scripts/sanitizer.py`. Ported from CoWork source
  at 2026-04-24 (action item #408). Paperwik-specific adaptations: LLM-judge
  Task calls pinned to `model: "haiku"` (classification tasks, not synthesis)
  and drop-target path updated to `~/Paperwik/Vault/Inbox/`.
