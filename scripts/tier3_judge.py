#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Tier 3 of the Sanitizer cascade — prepare a batched LLM-judge input file.

This script is the deterministic-Python half of Tier 3. It reads the Tier 2
report, filters to escalation-needing pairs (ZSC_AMBIGUOUS and
ZSC_AMBIGUOUS_CONTRADICTION_HINT), looks up source chunks, and writes a
compact `tier3_input.json` that the Editor (main Claude Code session) feeds
to a Task subagent acting as the LLM-as-judge.

The actual LLM-judge invocation happens in the Editor's session via the
`Agent` (Task) tool — that part is NOT in this script. This script only
prepares the input + reads back the verdicts.

Usage:
    # Step 1: prepare input
    uv run scripts/tier3_judge.py prepare \\
        --run-dir /path/to/runs/<run_id>

    # Step 2 (Editor does this in-session, not here):
    #   spawn a Task subagent with the prompt at references/tier3_judge_prompt.md
    #   (file present as of D2R-1, 2026-04-27 — was missing in v1.1)
    #   subagent returns verdicts inline in ---BEGIN_VERDICTS---/---END_VERDICTS---
    #   markers; parent parses and writes tier3_verdicts.json

    # Step 3: merge verdicts back into the verification report
    uv run scripts/tier3_judge.py merge \\
        --run-dir /path/to/runs/<run_id>

Reads:
    {run-dir}/verification_report_v2.json   (Tier 1 + Tier 2 merged)
    {run-dir}/chunks.json                   (corpus, for source lookup)

Writes (prepare):
    {run-dir}/tier3_input.json              (compact list for the LLM-judge)

Writes (merge):
    {run-dir}/verification_report_v3.json   (Tier 1 + 2 + 3 merged)

Exit codes:
    0  success
    1  no escalations needed
    2  fatal error
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ESCALATION_VERDICTS = ("ZSC_AMBIGUOUS", "ZSC_AMBIGUOUS_CONTRADICTION_HINT")


def cmd_prepare(run_dir: Path) -> int:
    """Build tier3_input.json from verification_report_v2.json escalations."""
    report_path = run_dir / "verification_report_v2.json"
    chunks_path = run_dir / "chunks.json"
    if not (report_path.exists() and chunks_path.exists()):
        print(f"ERROR: missing verification_report_v2.json or chunks.json in {run_dir}",
              file=sys.stderr)
        return 2

    report = json.loads(report_path.read_text(encoding="utf-8"))
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    chunk_lookup = {c["chunk_id"]: c for c in chunks}

    escalations = [d for d in report["details"]
                   if d.get("tier2_verdict") in ESCALATION_VERDICTS]

    if not escalations:
        print("No escalations needed — Tier 2 resolved everything")
        return 1

    items = []
    for i, d in enumerate(escalations):
        chunk = chunk_lookup.get(d["chunk_id"], {})
        item = {
            "id": i,
            "chunk_id": d["chunk_id"],
            "claim": d["claim"][:300],
            "source": chunk.get("text", "")[:600],
            "zsc": d.get("tier2_nli", {}),
        }
        # Pass the contradiction hint to the LLM-judge as a hint to scrutinize harder
        if d.get("tier2_verdict") == "ZSC_AMBIGUOUS_CONTRADICTION_HINT":
            item["contradiction_hint"] = (
                "The local NLI model leaned toward 'contradiction' "
                f"(confidence {d.get('tier2_nli', {}).get('contradiction', 0):.2f}). "
                "Verify carefully — D1 showed this signal can be a false positive."
            )
        items.append(item)

    out_path = run_dir / "tier3_input.json"
    out_path.write_text(json.dumps(items, indent=2), encoding="utf-8")
    print(f"Wrote tier3_input.json: {len(items)} pairs to judge "
          f"({out_path.stat().st_size} bytes)")

    contradiction_hint_count = sum(1 for it in items if "contradiction_hint" in it)
    if contradiction_hint_count:
        print(f"  ({contradiction_hint_count} have contradiction-hint context for the judge)")

    print(f"\nNext step: Editor in main session spawns a Task subagent with the")
    print(f"prompt at references/tier3_judge_prompt.md (or inlined equivalent),")
    print(f"pointing at this file. Subagent writes verdicts to:")
    print(f"  {run_dir / 'tier3_verdicts.json'}")
    return 0


def cmd_merge(run_dir: Path) -> int:
    """Merge tier3_verdicts.json back into verification_report_v3.json."""
    report_v2_path = run_dir / "verification_report_v2.json"
    verdicts_path = run_dir / "tier3_verdicts.json"
    if not (report_v2_path.exists() and verdicts_path.exists()):
        print(f"ERROR: missing verification_report_v2.json or tier3_verdicts.json",
              file=sys.stderr)
        return 2

    report = json.loads(report_v2_path.read_text(encoding="utf-8"))
    verdicts = json.loads(verdicts_path.read_text(encoding="utf-8"))

    # Map id -> verdict
    by_id = {v["id"]: v for v in verdicts}

    # Walk the details, attach Tier 3 verdicts where escalations had ids
    counters = {"SUPPORTED": 0, "PARTIAL": 0, "CONTRADICTED": 0, "UNRELATED": 0}
    escalation_index = 0
    for d in report["details"]:
        if d.get("tier2_verdict") in ESCALATION_VERDICTS:
            t3 = by_id.get(escalation_index)
            if t3:
                d["tier3_verdict"] = t3.get("verdict")
                d["tier3_rationale"] = t3.get("rationale", "")
                counters[t3.get("verdict", "PARTIAL")] = counters.get(
                    t3.get("verdict", "PARTIAL"), 0) + 1
            escalation_index += 1

    report["tier3_summary"] = counters
    report["tier3_cascade_version"] = "v3"

    out_path = run_dir / "verification_report_v3.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote verification_report_v3.json")
    print(f"\nTier 3 verdicts:")
    for k, v in counters.items():
        print(f"  {k}: {v}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    p_prep = sub.add_parser("prepare", help="Build tier3_input.json from Tier 2 report")
    p_prep.add_argument("--run-dir", required=True, type=Path)
    p_merge = sub.add_parser("merge", help="Merge tier3_verdicts.json into final report")
    p_merge.add_argument("--run-dir", required=True, type=Path)
    args = p.parse_args()

    if args.cmd == "prepare":
        return cmd_prepare(args.run_dir)
    elif args.cmd == "merge":
        return cmd_merge(args.run_dir)
    return 2


if __name__ == "__main__":
    sys.exit(main())
