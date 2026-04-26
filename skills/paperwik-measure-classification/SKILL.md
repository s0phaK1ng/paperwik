---
name: paperwik-measure-classification
description: >
  Run the v0.6.0 zero-shot classification benchmark and emit a top-1 accuracy
  report. Triggers on phrases like "measure classification", "check zsc
  accuracy", "run the classification benchmark", "is zsc still working", or
  any explicit ask to evaluate paperwik's source-type / project-routing
  accuracy. Self-contained — does NOT require a real vault, an active
  knowledge.db, or any user content. Reads plugin/tests/zsc_benchmark.json,
  invokes classify.py + source_classifier.py directly, computes accuracy,
  appends a one-line summary to Paperwik-Diagnostics.log.
allowed-tools: Read, Bash
---

# paperwik-measure-classification

Compute project-routing top-1 accuracy and source-type top-1 accuracy from
the bundled benchmark, then append a one-line entry to the diagnostics log.

## When to trigger

- User asks "measure classification accuracy" / "how good is the ZSC routing"
- Weekly cadence — invoked by the same Task Scheduler trigger that runs the
  retrieval-eval harness (`paperwik-measure-retrieval`); piggybacks on that
  cron, no new infrastructure
- After upgrading the model or the hypothesis template, to confirm there's
  no regression vs. the prior week's run

## When NOT to trigger

- During the user's normal ingest/query flow — this skill is for periodic
  measurement, not real-time decisions
- If `plugin/tests/zsc_benchmark.json` is missing (the install is incomplete;
  tell the user to re-run the installer)

## Flow

### 1. Locate the benchmark + scripts

```bash
PAPERWIK_PLUGIN="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/marketplaces/paperwik}"
BENCH="$PAPERWIK_PLUGIN/tests/zsc_benchmark.json"
CLASSIFY="$PAPERWIK_PLUGIN/scripts/classify.py"
SOURCE_CLASSIFIER="$PAPERWIK_PLUGIN/scripts/source_classifier.py"

if [ ! -f "$BENCH" ]; then
    echo "Benchmark file missing: $BENCH"
    exit 1
fi
```

### 2. Run the two evaluations

For each of the 20 documents in `zsc_benchmark.json`:

**Source-type top-1 accuracy** — invoke `source_classifier.py`:

```bash
echo "$content_excerpt" | uv run "$SOURCE_CLASSIFIER" --stdin
# Compare returned 'type' field against expected_source_type
```

**Project-routing top-1 accuracy** — invoke `classify.py` directly with
the benchmark's `expected_projects` list as candidate labels (multi-label,
default template):

```bash
uv run "$CLASSIFY" --text "$content_excerpt" \
    --labels "Cognitive Health,Family History,Municipal Bonds,Omega-3 Research,Personal Finance,Home Maintenance" \
    --multi-label
# Top result's label vs. expected_project
```

Tally hits and misses across the 20 docs.

### 3. Compute accuracy + emit report

Compute:
- `source_type_top1 = source_hits / 20`
- `project_routing_top1 = project_hits / 20`

Targets (from handoff §7):
- Source classification: ≥ 90% top-1
- Project routing: ≥ 80% top-1

If either target is missed by ≥ 5% from the prior recorded run (read
`Paperwik-Diagnostics.log` to find the most recent classification entry),
flag a regression in the report.

### 4. Append to Paperwik-Diagnostics.log

```bash
LOG="$HOME/Paperwik/Paperwik-Diagnostics.log"
TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "$TS | classification | source_top1=$source_acc project_top1=$project_acc | $regression_flag" >> "$LOG"
```

### 5. Report to user

A 3-5 sentence summary:
- The two accuracies (with the targets noted)
- Whether either flagged a regression
- Where the log entry is
- One actionable next step IF a regression fired (e.g., "consider re-running
  with the latest model" / "check whether the benchmark needs refreshing")

## Notes

- The benchmark is a v0.6.0 PLACEHOLDER. Real signal comes after the user
  has ingested for a month and the benchmark is refreshed with 20 of their
  actual documents. Until then, treat absolute numbers with skepticism;
  trend-vs-prior-run is the meaningful signal.
- This skill MUST NOT touch the user's vault, knowledge.db, or any project
  folder. It only reads the benchmark file + appends one log line.
- First invocation per machine pays the model-download + quantize cost
  (~30-60s). Subsequent invocations reuse the cached INT8 model.
