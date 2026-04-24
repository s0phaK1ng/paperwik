---
name: measure-retrieval
description: >
  Run the retrieval quality eval harness against the 20-question set in
  eval.json. Computes NDCG@10 / MRR / Recall@5. Also called automatically
  by the weekly cron. Triggers on phrases like "measure retrieval",
  "check retrieval quality", "run the eval", "how well is search working",
  "retrieval metrics", "run eval harness".
allowed-tools: Bash, Read
---

# measure-retrieval

Run the retrieval eval harness and report metrics.

## Triggers

- "measure retrieval" / "run the eval" / "run the retrieval eval"
- "how well is search working"
- "retrieval quality check"
- Automatic: weekly cron (`hooks/weekly-eval-cron.ps1`)

## Flow

### 1. Verify eval.json has questions

```bash
uv run python -c "
import json, pathlib, os
p = pathlib.Path(os.environ['USERPROFILE']) / 'Paperwik' / 'eval.json'
data = json.loads(p.read_text(encoding='utf-8'))
print(f\"questions: {len(data.get('questions', []))}\")"
```

If there are 0 questions, tell the user: *"Your eval set is empty. During
our day-one training I captured 20 questions — if that didn't happen, we
should do it now. The eval is only meaningful against questions you actually
want to ask your wiki."*

### 2. Run the eval

```bash
# $CLAUDE_PLUGIN_ROOT is not reliably exported to skill shells; fall back to install path
PAPERWIK_PLUGIN="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/marketplaces/paperwik}"
uv run "$PAPERWIK_PLUGIN/scripts/retrieval_eval.py"
```

The script prints a one-line summary to stdout (NDCG@10, MRR, Recall@5) and
stores per-run metrics in the `eval_runs` table of `knowledge.db`.

### 3. Compare to baseline

Read `knowledge.db` for the previous run's metrics (second-most-recent row in
`eval_runs`). If any metric has dropped by ≥0.05 since the last run:

- Alert is already written to `Documents\Paperwik-Diagnostics.log` by the
  eval script.
- Report the drop to the user: *"Retrieval quality dropped this week —
  NDCG@10 went from 0.65 to 0.58. Likely causes: a recent ingest introduced
  conflicting content, or a retrieval component is misbehaving. Want me to
  run an ablation pass to find which component is responsible?"*

### 4. Ablation (optional, user-triggered)

If the user says yes, run the eval once per toggle-off in
`retrieval_config.json`:
1. Read current config.
2. For each enabled component (vector_search, bm25_search, reranker,
   graph_search, query_decomposition, rrf_fusion), temporarily set it
   false, re-run the eval, record the delta, set it back to true.
3. Report: *"Component X is the biggest negative delta when disabled —
   probably it's pulling its weight. Component Y is a slight positive when
   disabled — consider turning it off."*

Ablation is slow (6× eval runs) so only do this on explicit request.

### 5. Append to log.md

```
## [YYYY-MM-DD HH:MM] eval | NDCG@10=0.672 MRR=0.541 Recall@5=0.810
```

## Rules

- **Never modify retrieval_config.json without user confirmation** after
  ablation. Report findings, propose changes, wait.
- **Report metrics as absolute values**, not just "looks good." The whole
  point is numbers.
- **If eval.json has fewer than 5 questions**, note that the metrics are
  unreliable. Encourage the user to add more during normal use.
