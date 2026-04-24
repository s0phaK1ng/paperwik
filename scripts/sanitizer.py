#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["rapidfuzz>=3.0"]
# ///
"""Citation verifier for the research engine's Phase 4 Editor.

Action item A5 (paperwik action item #408). Reads concatenated drafts,
parses citations in the form `[s3_c7]` or `[s3_c7, s4_c2]`, compares each
claim sentence against its cited chunk(s) via rapidfuzz.partial_ratio, and
writes a verification report.

This script implements ONLY the deterministic fuzzy pass. It emits the
AMBIGUOUS and FAIL cases as JSON that the Editor then feeds into
LLM-as-judge Task subagents (Haiku 4.5, per paperwik's hybrid model
routing). This separation is deliberate: determinism stays in Python;
LLM judgment stays in Claude Code.

Usage:
    uv run scripts/sanitizer.py \\
        --draft /path/to/concatenated_draft.md \\
        --chunks /path/to/chunks.json \\
        --output-report /path/to/verification_report.json \\
        [--fuzzy-threshold 70]

Exit codes:
    0  all citations PASS
    1  some AMBIGUOUS or FAIL exist (Editor must escalate)
    2  fatal error (missing chunks, broken input)

Ported verbatim from CoWork deep-research skill at 2026-04-24 (paperwik
action item #408). No paperwik-specific code changes.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    from rapidfuzz import fuzz
except ImportError:
    print("ERROR: rapidfuzz not installed. Run via `uv run` with the PEP-723 header.",
          file=sys.stderr)
    sys.exit(2)


CITATION_RE = re.compile(r"\[((?:s\d+_c\d+)(?:\s*,\s*s\d+_c\d+)*)\]")


def load_chunks(chunks_path: Path) -> dict[str, dict]:
    """Return {chunk_id: chunk_record}."""
    data = json.loads(chunks_path.read_text(encoding="utf-8"))
    return {entry["chunk_id"]: entry for entry in data}


def extract_citations(draft_text: str) -> list[dict]:
    """Find every citation instance and return (chunk_ids, claim_sentence, position)."""
    results = []
    # Split into sentences -- naive, but good enough for our prose
    # Keep the citation attached to its preceding sentence
    for m in CITATION_RE.finditer(draft_text):
        citation_str = m.group(1)
        chunk_ids = [s.strip() for s in citation_str.split(",")]
        # Find the sentence containing this citation:
        # walk backwards from the citation to the nearest sentence-ending punctuation
        start = m.start()
        # find previous period/!/? that's not inside an abbreviation or a citation itself
        sentence_start = 0
        for i in range(start - 1, -1, -1):
            ch = draft_text[i]
            if ch in ".!?\n" and (i == 0 or draft_text[i - 1] != "."):
                # Check for common abbreviations that might precede a period (Mr., Dr., etc.)
                # Keep it simple: accept any period followed by whitespace as a sentence boundary
                if i + 1 < len(draft_text) and draft_text[i + 1] in " \t\n":
                    sentence_start = i + 1
                    break
        claim = draft_text[sentence_start:m.end()].strip()
        # strip leading whitespace/markdown noise
        claim = re.sub(r"^[\s#>*\-]+", "", claim)
        results.append({
            "chunk_ids": chunk_ids,
            "claim": claim,
            "position": m.start(),
        })
    return results


def classify(claim: str, chunk_text: str, threshold: int) -> tuple[str, int]:
    """Return (verdict, fuzzy_score) where verdict is PASS/AMBIGUOUS/FAIL."""
    score = int(fuzz.partial_ratio(claim.lower(), chunk_text.lower()))
    if score >= threshold:
        return ("PASS", score)
    if score >= int(threshold * 0.55):  # >= 40 when threshold is 70
        return ("AMBIGUOUS", score)
    return ("FAIL", score)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--draft", required=True, type=Path)
    p.add_argument("--chunks", required=True, type=Path)
    p.add_argument("--output-report", required=True, type=Path)
    p.add_argument("--fuzzy-threshold", type=int, default=70)
    args = p.parse_args()

    if not args.draft.exists():
        print(f"ERROR: draft file not found: {args.draft}", file=sys.stderr)
        return 2
    if not args.chunks.exists():
        print(f"ERROR: chunks file not found: {args.chunks}", file=sys.stderr)
        return 2

    draft_text = args.draft.read_text(encoding="utf-8")
    chunks_by_id = load_chunks(args.chunks)

    citations = extract_citations(draft_text)

    report_details: list[dict] = []
    counts = {"PASS": 0, "AMBIGUOUS": 0, "FAIL": 0, "MISSING_CHUNK": 0}

    for cit in citations:
        for chunk_id in cit["chunk_ids"]:
            if chunk_id not in chunks_by_id:
                counts["MISSING_CHUNK"] += 1
                report_details.append({
                    "claim": cit["claim"],
                    "chunk_id": chunk_id,
                    "verdict": "MISSING_CHUNK",
                    "fuzzy_score": None,
                    "position": cit["position"],
                })
                continue
            chunk_text = chunks_by_id[chunk_id]["text"]
            verdict, score = classify(cit["claim"], chunk_text, args.fuzzy_threshold)
            counts[verdict] += 1
            report_details.append({
                "claim": cit["claim"],
                "chunk_id": chunk_id,
                "verdict": verdict,
                "fuzzy_score": score,
                "position": cit["position"],
            })

    total = sum(counts.values())
    report = {
        "total_citation_instances": total,
        "pass": counts["PASS"],
        "ambiguous": counts["AMBIGUOUS"],
        "fail": counts["FAIL"],
        "missing_chunk": counts["MISSING_CHUNK"],
        "fuzzy_threshold": args.fuzzy_threshold,
        "needs_llm_judge": counts["AMBIGUOUS"] + counts["FAIL"],
        "needs_substitution_or_weakening": counts["FAIL"] + counts["MISSING_CHUNK"],
        "details": report_details,
    }

    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Verification report: {args.output_report}")
    print(f"  total: {total} | PASS: {counts['PASS']} "
          f"| AMBIGUOUS: {counts['AMBIGUOUS']} "
          f"| FAIL: {counts['FAIL']} "
          f"| MISSING_CHUNK: {counts['MISSING_CHUNK']}")

    # Exit 1 if anything needs escalation; Editor catches this and spawns judges
    if counts["AMBIGUOUS"] + counts["FAIL"] + counts["MISSING_CHUNK"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
