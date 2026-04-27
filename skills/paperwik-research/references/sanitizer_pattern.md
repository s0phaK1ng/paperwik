# Phase 4 Sanitizer — Citation Verification Pattern (paperwik 2-tier)

paperwik action item **A5**. Invoked by the Editor after all section
drafts are in. Verifies that every citation in the final document is
grounded in a real source chunk, not a hallucination.

> **paperwik runs the 2-tier cascade: Tier 1 (deterministic rapidfuzz)
> → Tier 3 (LLM-as-judge).** This is the paperwik subset of CoWork's
> 3-tier asymmetric cascade — CoWork's Tier 2 (local DeBERTa-v3 NLI
> served via the `verify_nli` MCP tool on a NUC) is NUC-dependent and
> not applicable on a friend-and-family install. The simpler 2-tier
> behavior is functionally equivalent to running the CoWork engine
> with `DEEP_RESEARCH_ZSC_ENABLED=false`. See `DIVERGENCES_FROM_COWORK.md`
> for the explicit mapping.

---

## Why This Exists

LLMs structurally invent citations. This cannot be fixed by prompting. It
must be fixed by a deterministic post-synthesis verification pass that
treats citation validation as a compilation error, not a writing-style
preference.

Without the Sanitizer, ~10–30% of citations in a deep research document
are subtly wrong: invented URLs, misattributed quotes, claims attached to
sources that don't actually support them. A wiki full of these becomes
worse than no wiki at all.

The Sanitizer's job is to fail loudly on every invalid citation and force
a micro-correction before the document leaves the engine.

---

## Input

- Every `drafts/<section_id>.md` in the run directory (written by
  `scripts/parse_section_response.py` from each section-writer subagent's
  inline response — see `references/section_writer_prompt.md` v2)
- The full `chunks.json` from Phase 2 (the source of truth)
- Optional: `drafts/_summaries/*.txt` for the contradiction pass

## Output

- A cleaned `final.md` produced by `scripts/stitch_final.py` with verified
  citations — all `[chunk_id]` references resolve to real chunks, and
  every claim's chunk text actually supports the claim
- A cascading `verification_report.json` (Tier 1) →
  `verification_report_v3.json` (Tier 1 + Tier 3 merged via
  `scripts/tier3_judge.py merge`) listing every citation checked, its
  score, and any corrections applied
- If any citation fails after correction, the entire run fails loudly —
  no silent writes of broken documents

---

## The Algorithm

### Step 1 — Concatenate drafts in outline order

Performed inside `scripts/stitch_final.py` (called in Phase 4 step 6 of
`SKILL.md`). Reads `drafts/s1.md`, `s2.md`, ... in the order defined by
`plan.section_outline`. Interpolates the H2 `## <title>` header before
each section's body.

### Step 2 — Extract every citation

`scripts/sanitizer.py` parses the concatenated draft. Every `[chunk_id]`
or `[chunk_id, chunk_id, ...]` is a citation instance. For each instance
it captures:
- The chunk ID(s) cited
- The surrounding sentence (the "claim") — extends 1 sentence back from
  the citation to its nearest sentence-ending punctuation
- The section it appears in

### Step 3 — Tier 1: Deterministic rapidfuzz match

For each (claim, chunk_id) pair, `scripts/sanitizer.py` runs:

```python
score = rapidfuzz.fuzz.partial_ratio(claim, chunk.text)
```

- Score ≥ 70 → **PASS** (claim is strongly grounded)
- Score 40–69 → **AMBIGUOUS** (escalate to Tier 3)
- Score < 40 → **FAIL** (escalate to Tier 3)

Additionally: extract noun phrases from the claim. A claim with zero
noun-phrase overlap with the chunk is automatically AMBIGUOUS regardless
of fuzzy score.

Output: `verification_report.json` with PASS/AMBIGUOUS/FAIL verdicts.

### Step 4 — Tier 3: LLM-as-judge (paperwik direct escalation)

> **paperwik skips CoWork's Tier 2 (local DeBERTa-v3 NLI on NUC):** every
> AMBIGUOUS or FAIL pair from Tier 1 escalates DIRECTLY to Tier 3. CoWork's
> Tier 2 catches ~65% of these locally (saving Task subagent calls); for
> paperwik's friend-and-family scale (1–2 deep-research runs per week),
> the extra ~30 Task subagent calls per run are within Pro subscription
> budget and don't justify NUC infrastructure.

The Editor runs:

```bash
PAPERWIK_PLUGIN="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/marketplaces/paperwik}"
uv run "$PAPERWIK_PLUGIN/scripts/tier3_judge.py" prepare --run-dir <run_dir>
```

This filters `verification_report.json` to escalation-needing pairs and
writes `tier3_input.json`. Then the Editor spawns ONE Task subagent (with
`model: "haiku"` per paperwik's hybrid routing) using the prompt from
`references/tier3_judge_prompt.md`. The judge subagent batches ALL
escalations into a single response and returns verdicts inline:

```
---BEGIN_VERDICTS---
[
  {"id": 0, "verdict": "SUPPORTED", "rationale": "..."},
  {"id": 1, "verdict": "PARTIAL",   "rationale": "..."},
  ...
]
---END_VERDICTS---
```

Verdict semantics:
- **SUPPORTED** → accept, mark PASS in the merged report
- **PARTIAL** → accept with a `†` marker appended to the citation;
  verification_report notes "partial support"
- **CONTRADICTED** → hard error, escalate to Step 5 correction
- **UNRELATED** → hard error, escalate to Step 5 correction

After the subagent returns, the Editor extracts the JSON from the markers,
writes it to `tier3_verdicts.json`, then runs:

```bash
uv run "$PAPERWIK_PLUGIN/scripts/tier3_judge.py" merge --run-dir <run_dir>
```

to fold verdicts into `verification_report_v3.json`.

### Step 5 — Correct CONTRADICTED / UNRELATED cases

For each FAIL case (Tier 3 verdict CONTRADICTED or UNRELATED):

1. **Attempt substitution** — search `chunks.json` for a chunk whose text
   has rapidfuzz score ≥ 70 against the claim. If one exists, swap the
   bad citation for the good one. Log the substitution in the report.
2. **Attempt weakening** — if no substitute exists, spawn a lightweight
   Task subagent (`model: "haiku"`) with:

   ```
   Rewrite the following CLAIM so that it is directly supported by the SOURCE.
   You may weaken or qualify the claim but you must not introduce new facts.
   Return ONLY the rewritten sentence.

   CLAIM: "<original>"
   SOURCE: "<chunk text>"
   ```

3. **Escalate to deletion** — if neither substitution nor weakening succeeds,
   delete the claim entirely and log it. If more than 5% of claims require
   deletion, halt the run and report to the user — the section probably
   needs re-drafting.

### Step 6 — Contradiction pass (optional, conditional)

Read `drafts/_summaries/*.txt` (one per section). For each pair of
sections, ask a lightweight Task subagent (`model: "haiku"`):

```
Do these two summaries contain any direct factual contradiction?

SUMMARY A: "<summary of section A>"
SUMMARY B: "<summary of section B>"

If yes, describe it in one sentence. If no, reply "NONE".
```

For every non-NONE response, the Editor surfaces the contradiction in a
new `## Contradictions` H2 section appended after the body and before
`## Sources`. Format:

```
## Contradictions

- Section **s3** (X) and section **s5** (Y) report conflicting claims on
  Z — s3 says A [s3_c2], s5 says B [s5_c4]. The discrepancy likely
  reflects [brief analysis].
```

If no contradictions are found, the section is omitted entirely.

### Step 7 — Output

`scripts/stitch_final.py` writes the fully verified document to:

- `runs/<run_id>/final.md` (the authoritative output)
- `~/Paperwik/Vault/Inbox/deep_research_<slug>_<date>.md` (the copy the
  ingest pipeline picks up)

The verification appendix in `final.md` reports:
- Tier 1 counts (PASS / AMBIGUOUS / FAIL)
- Tier 3 verdicts (SUPPORTED / PARTIAL / CONTRADICTED / UNRELATED)
- Cascade version: `paperwik-2tier` (vs. CoWork's `v3` 3-tier)

`run_verdict` is `clean` if `fatal_errors == 0` and
`deletions / total_citations <= 0.05`. Otherwise `dirty` — and the engine
returns an error to the user rather than silently writing the output.

---

## Tuning Notes

- Fuzzy threshold 70 was chosen empirically for English technical prose.
  Lower (50–60) for topics with a lot of proper nouns; higher (75–80) for
  purely numerical claims.
- The Tier 3 judge prompt is deliberately terse (see
  `references/tier3_judge_prompt.md` for the full template) — it batches
  many escalations into a single subagent call to amortize the overhead.
- Substitution threshold matches Tier 1 (70) to avoid the Sanitizer
  accepting a substitute it would itself have flagged.
- If a run consistently produces FAIL rates > 20%, the section-writer
  prompt needs tightening — probably the chunk routing is giving writers
  material they can't actually use.

---

## Why paperwik runs the 2-tier subset (not 3-tier)

CoWork's Tier 2 is a local DeBERTa-v3 NLI classifier (`framework/classify.py`)
served as the `verify_nli` MCP tool on the workspace's NUC server. It
auto-resolves ~65% of AMBIGUOUS/FAIL pairs in ~150 ms each, saving Task
subagent invocations.

paperwik's deployment target is a non-technical Windows user with no
NUC, no MCP server, and no local NLI model. Building a portable Tier 2
that runs on the user's laptop would require: distributing a quantized
DeBERTa-v3 ONNX model (~100–200 MB), wiring it through `classify.py`
infrastructure paperwik doesn't have, and dealing with the same
transitive-dep failure modes that haunted v0.6.0–v0.6.6 of the project
router's classifier (paperwik's own ONNX-based classifier).

The simpler 2-tier (Tier 1 → Tier 3) is the pragmatic answer:
- ~30 extra Task subagent calls per run vs. CoWork's NUC-served pipeline
- For 1–2 runs per week (paperwik's friend-and-family scale), this is
  well within Claude Pro budget
- Functionally equivalent to running the CoWork engine with
  `DEEP_RESEARCH_ZSC_ENABLED=false`

If paperwik's user ever sets up a local NLI model, the Tier 2 step can be
back-ported by lifting `scripts/tier2_verify.py` from CoWork — but that's
v0.8.x territory, not in scope for v0.5.0 of the research skill.

---

## Version History

- **v1 (2026-04-24, paperwik action item #408)** — Initial paperwik port
  from CoWork deep-research v1. Tier 1 + LLM-judge two-tier verification,
  substitution + weakening corrections, contradiction pass.
- **v2 (2026-04-27, paperwik action item to absorb CoWork v1.1+v1.2)** —
  Documented paperwik's 2-tier subset explicitly. Added references to
  `scripts/tier3_judge.py` (v1.1) for Tier 3 prepare/merge orchestration
  and `scripts/stitch_final.py` (v1.1) for final-doc assembly. Documented
  the paperwik-vs-CoWork cascade divergence.
