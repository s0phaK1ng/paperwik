#!/usr/bin/env bash
# paperwik-research synthetic test harness — runs the full v0.5.0 contract
# chain (merge_chunks → parse_section_response × 3 → stitch_final →
# output_validator) against fixed fixtures. Exit 0 on full success; 1 if any
# step fails or output diverges from snapshots; 2 on harness setup failure.
#
# Usage:  bash run_harness.sh
# Run from inside plugin/tests/research_harness/.

set -euo pipefail

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$HARNESS_DIR/../.." && pwd)"
SCRIPTS="$PLUGIN_ROOT/scripts"
FIXTURES="$HARNESS_DIR/fixtures"
EXPECTED="$HARNESS_DIR/expected"

# Use a /tmp run dir so re-runs don't accumulate in the repo
RUN_DIR="${TMPDIR:-/tmp}/paperwik_research_harness_run_$$"
DROP_DIR="$RUN_DIR/_drop"

cleanup() { rm -rf "$RUN_DIR" 2>/dev/null || true; }
trap cleanup EXIT

# Helper: print + exit non-zero
fail() { echo ">>> HARNESS FAIL: $*" >&2; exit 1; }

echo "=== paperwik-research synthetic harness ==="
echo "  plugin root:  $PLUGIN_ROOT"
echo "  scripts dir:  $SCRIPTS"
echo "  fixtures dir: $FIXTURES"
echo "  run dir:      $RUN_DIR"
echo

# Sanity checks
[ -d "$SCRIPTS" ] || fail "scripts dir not found: $SCRIPTS"
for s in merge_chunks.py parse_section_response.py stitch_final.py output_validator.py; do
    [ -f "$SCRIPTS/$s" ] || fail "missing script: $s"
done
[ -d "$FIXTURES" ] || fail "fixtures dir not found"

# ----- Set up run directory ----------------------------------------------
echo "[setup] Building run directory $RUN_DIR"
mkdir -p "$RUN_DIR/chunks" "$DROP_DIR"
cp "$FIXTURES/synthetic_plan.json" "$RUN_DIR/plan.json"
cp "$FIXTURES/synthetic_searcher_1.json" "$RUN_DIR/chunks/searcher_1.json"

# ----- Step 1: merge_chunks ----------------------------------------------
echo
echo "[step 1/5] merge_chunks.py"
uv run "$SCRIPTS/merge_chunks.py" --run-dir "$RUN_DIR" \
    || fail "merge_chunks.py exited non-zero"
[ -f "$RUN_DIR/chunks.json" ] || fail "merge_chunks did not write chunks.json"
[ -f "$RUN_DIR/pending_sections.json" ] || fail "merge_chunks did not write pending_sections.json"
echo "[step 1/5] OK"

# ----- Step 2: parse_section_response × 3 --------------------------------
echo
echo "[step 2/5] parse_section_response.py × 3 (valid responses)"
for sid in s1 s2 s3; do
    uv run "$SCRIPTS/parse_section_response.py" \
        --run-dir "$RUN_DIR" \
        --section-id "$sid" \
        --response-file "$FIXTURES/synthetic_subagent_response_${sid}.txt" \
        || fail "parse_section_response.py exited non-zero for $sid (should have parsed cleanly)"
    [ -f "$RUN_DIR/drafts/${sid}.md" ] || fail "draft missing for $sid"
    [ -f "$RUN_DIR/drafts/_summaries/${sid}.txt" ] || fail "summary missing for $sid"
    [ -f "$RUN_DIR/drafts/_metadata/${sid}.json" ] || fail "metadata missing for $sid"
done
echo "[step 2/5] OK"

# ----- Step 3: parse_section_response on malformed (should EXIT 1) ------
echo
echo "[step 3/5] parse_section_response.py on malformed fixture (must exit 1)"
set +e
uv run "$SCRIPTS/parse_section_response.py" \
    --run-dir "$RUN_DIR" \
    --section-id "s9" \
    --response-file "$FIXTURES/synthetic_subagent_response_malformed.txt" \
    >/dev/null 2>&1
MALFORMED_EXIT=$?
set -e
if [ "$MALFORMED_EXIT" != "1" ]; then
    fail "parse_section_response.py should exit 1 on malformed input, got $MALFORMED_EXIT"
fi
# Confirm no s9 draft was written (parser should refuse to produce output)
[ ! -f "$RUN_DIR/drafts/s9.md" ] || fail "parser wrote drafts/s9.md despite malformed input"
echo "[step 3/5] OK (exit code 1 as expected, no draft written)"

# ----- Step 4: stitch_final ----------------------------------------------
echo
echo "[step 4/5] stitch_final.py"
uv run "$SCRIPTS/stitch_final.py" \
    --run-dir "$RUN_DIR" \
    --drop-target "$DROP_DIR" \
    --research-tool "paperwik-research-harness/v0.5.0" \
    --date "2026-04-27" \
    || fail "stitch_final.py exited non-zero"
[ -f "$RUN_DIR/final.md" ] || fail "stitch_final did not write final.md"
DROPS=("$DROP_DIR"/deep_research_*.md)
[ -f "${DROPS[0]}" ] || fail "stitch_final did not write a drop-target file"
echo "[step 4/5] OK"

# ----- Step 5: output_validator ------------------------------------------
echo
echo "[step 5/5] output_validator.py"
uv run "$SCRIPTS/output_validator.py" --file "$RUN_DIR/final.md" \
    || fail "output_validator.py rejected the synthetic final.md (see stderr above)"
echo "[step 5/5] OK"

# ----- Snapshot comparison (if expected/ exists) -------------------------
if [ -d "$EXPECTED" ] && [ -f "$EXPECTED/final.md" ]; then
    echo
    echo "[snapshot] Comparing run output against expected/ snapshots"
    DIVERGED=0
    for rel in chunks.json pending_sections.json drafts/s1.md drafts/s2.md drafts/s3.md \
               drafts/_summaries/s1.txt drafts/_summaries/s2.txt drafts/_summaries/s3.txt \
               drafts/_metadata/s1.json drafts/_metadata/s2.json drafts/_metadata/s3.json \
               final.md; do
        if ! diff -q "$EXPECTED/$rel" "$RUN_DIR/$rel" >/dev/null 2>&1; then
            echo "  DIFF: $rel" >&2
            DIVERGED=1
        fi
    done
    if [ "$DIVERGED" = "1" ]; then
        echo
        echo ">>> One or more outputs diverged from expected/ snapshots." >&2
        echo "    If the change is intentional, refresh snapshots with:" >&2
        echo "      cp -r $RUN_DIR/{chunks.json,pending_sections.json,drafts,final.md} $EXPECTED/" >&2
        echo "    Otherwise, this is a regression — debug before committing." >&2
        exit 1
    fi
    echo "[snapshot] All 13 snapshot files match expected/"
else
    echo
    echo "[snapshot] No expected/ snapshots present yet."
    echo "  Initial baseline can be captured with:"
    echo "    mkdir -p $EXPECTED/drafts/_summaries $EXPECTED/drafts/_metadata"
    echo "    cp $RUN_DIR/chunks.json $RUN_DIR/pending_sections.json $EXPECTED/"
    echo "    cp $RUN_DIR/drafts/{s1,s2,s3}.md $EXPECTED/drafts/"
    echo "    cp $RUN_DIR/drafts/_summaries/{s1,s2,s3}.txt $EXPECTED/drafts/_summaries/"
    echo "    cp $RUN_DIR/drafts/_metadata/{s1,s2,s3}.json $EXPECTED/drafts/_metadata/"
    echo "    cp $RUN_DIR/final.md $EXPECTED/"
fi

echo
echo "=== HARNESS PASS — all 5 contract steps + malformed rejection succeeded ==="
exit 0
