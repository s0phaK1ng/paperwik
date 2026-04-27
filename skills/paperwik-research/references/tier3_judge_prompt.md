# Tier 3 LLM-Judge — Subagent Prompt Template

Action item **D2R-1** (D2 retrospective, 2026-04-27). Used by the main session
when spawning the Tier 3 LLM-as-Judge subagent during the Sanitizer cascade
(see `references/sanitizer_pattern.md` Step 4b).

This file fills the gap left in v1.1: `scripts/tier3_judge.py` references this
path in its docstring but it didn't exist on disk. D2 ran with the prompt
inlined ad-hoc; this file captures the working version so future runs reference
it instead of reinventing.

---

## Invocation

The main session spawns the Tier 3 judge via the `Task` tool after running
`scripts/tier3_judge.py prepare`, which writes `tier3_input.json`:

```
Agent({
  description: "Tier 3 LLM-judge — return inline",
  subagent_type: "general-purpose",
  prompt: <THIS PROMPT WITH PLACEHOLDERS FILLED>,
  run_in_background: true
})
```

There is exactly ONE judge subagent per run — it batches all escalations into
a single response.

---

## The Prompt Template

```
You are the Tier 3 LLM-as-Judge for a deep-research output sanitizer cascade.
The Tier 1 (rapidfuzz) and Tier 2 (local NLI model) tiers escalated <N>
claim-source pairs to you because they couldn't be auto-resolved. Your job is
to make the final verdict on each pair.

## Read your input here

  <RUN_DIR>/tier3_input.json

It is a JSON array of <N> items. Each has:
- `id`: integer, 0..N-1
- `chunk_id`: source chunk reference (e.g. "s3_c4")
- `claim`: the sentence in the document that cited this chunk
- `source`: the relevant passage from the cited source (truncated to ~600 chars)
- `zsc`: the local NLI model's scores (entailment, neutral, contradiction)
- `contradiction_hint` (optional, on items where the local model leaned toward
   contradiction with confidence ≥0.70): the local model said "contradiction"
   but D1 evidence shows this signal is often a false positive on long multi-
   clause claims, so you should scrutinize but NOT default to CONTRADICTED.

## Your task

For each item, return one of these four verdicts:

- **SUPPORTED** — the source clearly supports the claim's specific phrasing
- **PARTIAL** — the source supports the gist but not every detail (e.g. claim
  says "20-80%" and source says "30-70%"), OR the source supports the claim
  plus the citation is one of several valid sources for it
- **CONTRADICTED** — the source actively says something incompatible with the
  claim
- **UNRELATED** — the source is about a different topic and does not bear on
  the claim

Be fair: most academic-quality citations in real research are SUPPORTED or
PARTIAL. CONTRADICTED is rare and should only be used when the source genuinely
says the opposite. UNRELATED is for off-topic source-claim pairings.

## Output schema

A JSON array EXACTLY matching this schema, one entry per input item, in input
order:

```json
[
  {"id": 0, "verdict": "SUPPORTED", "rationale": "<1 short sentence>"},
  {"id": 1, "verdict": "PARTIAL", "rationale": "<1 short sentence>"},
  ...
]
```

Keep rationales short (one sentence). Include all N items in input order — do
not skip any.

## DELIVERABLE CHANNEL OVERRIDE

You do NOT have file-write permission in your sandbox. Do NOT attempt Write,
Bash, PowerShell, or any other write tool — they will all be denied. Return
your JSON array INLINE in your response, formatted EXACTLY as:

  ---BEGIN_VERDICTS---
  [
    {"id": 0, "verdict": "...", "rationale": "..."},
    ...
    {"id": <N-1>, "verdict": "...", "rationale": "..."}
  ]
  ---END_VERDICTS---

The parent agent will parse those markers and write `tier3_verdicts.json`. No
commentary outside the markers.
```

---

## Placeholder Substitutions

| Placeholder | Value |
|-------------|-------|
| `<N>` | Number of items in `tier3_input.json` (run-specific) |
| `<RUN_DIR>` | The absolute path to the run directory |

---

## Output Capture

After the judge subagent returns:

1. Extract the `---BEGIN_VERDICTS---` to `---END_VERDICTS---` block from the
   response.
2. Validate the JSON array length matches the input file's length.
3. Write the array (without markers) to `<RUN_DIR>/tier3_verdicts.json`.
4. Run `scripts/tier3_judge.py merge --run-dir <RUN_DIR>` to fold verdicts
   into `verification_report_v3.json`.

The Editor uses `verification_report_v3.json` to drive Phase 4e (stitching)
and Phase 4f (validation).

---

## Empirical Notes (D2, 2026-04-27)

D2's Tier 3 escalations: 49 pairs (43 ZSC_AMBIGUOUS + 6
ZSC_AMBIGUOUS_CONTRADICTION_HINT). Judge returned 42 SUPPORTED + 7 PARTIAL +
0 CONTRADICTED + 0 UNRELATED. The 0-CONTRADICTED outcome confirmed v1.1's
asymmetric cascade design — every contradiction-hint flagged by Tier 2 was a
false positive on review, exactly as predicted.

Wall-clock time: ~65 seconds for one judge subagent processing 49 items. Cost:
1 Task subagent invocation on the user's Claude subscription.

---

## Version History

- **v1 (2026-04-27, action item D2R-1)** — Initial template extracted from D2's
  working ad-hoc prompt. Closes the gap left by v1.1 build (referenced this
  path but file didn't exist).
