# paperwik-research synthetic test harness

End-to-end smoke test for the deep-research v0.5.0 contract chain. Exercises
the four scripts that v0.7.0 absorbed from CoWork v1.1+v1.2 without burning
any real Pro budget on WebSearch/WebFetch/Task subagent invocations.

## What this catches

Code-level bugs in:

- `scripts/merge_chunks.py` — strict 7-key canonical schema enforcement, drift
  variant normalization
- `scripts/parse_section_response.py` — four-marker block extraction, malformed
  response rejection (exit 1, not silent pass)
- `scripts/stitch_final.py` — outline-ordered section concatenation, YAML
  frontmatter assembly, Sources table generation
- `scripts/output_validator.py` v1.1 — relaxed body-format contract (Context
  first, Sources present, ≥3 other H2 in between, topic-specific names allowed,
  trailing appendices like `## Verification` permitted)

## What this does NOT catch

- Sub-agent sandbox write restrictions in Claude Desktop's Code tab — only a
  real D1 run (per `v0.7.x_dial_in_plan.md` Phase 4) exercises this
- Model routing — the `model:` pinning is in SKILL.md, not in any of the
  scripts the harness invokes
- Real WebSearch/WebFetch quality
- Real Tier 3 LLM-judge verdict quality on Haiku

## Layout

```
research_harness/
  README.md                 ← this file
  run_harness.sh            ← entry point
  fixtures/
    synthetic_plan.json
    synthetic_searcher_1.json
    synthetic_subagent_response_s1.txt
    synthetic_subagent_response_s2.txt
    synthetic_subagent_response_s3.txt
    synthetic_subagent_response_malformed.txt
  expected/
    chunks.json              ← captured after first successful run
    pending_sections.json
    drafts/{s1,s2,s3}.md
    drafts/_summaries/{s1,s2,s3}.txt
    drafts/_metadata/{s1,s2,s3}.json
    final.md
```

## Usage

From the plugin root:

```bash
cd plugin/tests/research_harness/
bash run_harness.sh
```

Exit codes:

- `0` — all 5 contract steps passed; outputs match `expected/` snapshots
- `1` — at least one contract step failed; see stderr for the offending step
- `2` — fatal harness error (missing fixtures, etc.)

## Synthetic topic

The fixtures simulate a research run on **"Pour-over vs espresso: home coffee
brewing methods compared"** — a 3-section plan (Context / Pour-over for the
home / Espresso for the home), 10 chunks across 4 source URLs, citation
density that exercises the validator's chunk-id-resolves-to-Sources-row check.

The body content is plausible but not verified against real coffee
literature — claims are deliberately representative-not-true so the harness
can't be confused with a real research run if someone finds it in `expected/final.md`.

## Refreshing snapshots

If a legitimate change to one of the four scripts changes the expected output
(e.g., a v0.7.1 patch that adjusts the YAML frontmatter format):

1. Run the harness once to confirm the failure is the expected diff
2. `cp /tmp/research_harness_run/* expected/`
3. Commit the snapshot refresh in the same commit as the code change

Never refresh snapshots blindly without reading the diff.

## Maintenance

Owned by the paperwik agent. Add a new fixture pair when:

- A new script joins the contract chain (e.g., a v0.8.x Tier 2 NLI port)
- A v0.7.x patch fixes a contract-edge-case that's worth pinning into the
  regression baseline
