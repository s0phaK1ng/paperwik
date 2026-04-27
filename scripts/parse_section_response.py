#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Parse a section-writer subagent's inline response into draft files.

Action item D2R-5 (D2 retrospective, 2026-04-27). The section-writer prompt
v2 directs subagents to return their deliverable as an inline four-marker
block:

    ---BEGIN_SECTION---
    <section body markdown>
    ---END_SECTION---

    ---BEGIN_SUMMARY---
    <2-sentence summary>
    ---END_SUMMARY---

    ---METADATA---
    word_count: <int>
    distinct_chunks_cited: <int>
    chunk_ids_cited: <comma-separated list>
    ---END_METADATA---

This script extracts those blocks and writes:
    {run-dir}/drafts/<section_id>.md
    {run-dir}/drafts/_summaries/<section_id>.txt
    {run-dir}/drafts/_metadata/<section_id>.json

Usage:
    # Read the agent response from a file
    uv run scripts/parse_section_response.py \\
        --run-dir /path/to/runs/<run_id> \\
        --section-id s4 \\
        --response-file /path/to/agent_response.txt

    # Or pipe the response in via stdin
    cat agent_response.txt | uv run scripts/parse_section_response.py \\
        --run-dir /path/to/runs/<run_id> \\
        --section-id s4 \\
        --response-stdin

Exit codes:
    0  all 3 blocks parsed cleanly; 3 files written
    1  one or more blocks missing or malformed (orchestrator should re-spawn)
    2  fatal error (run-dir missing, response file unreadable, etc.)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SECTION_RE = re.compile(
    r"---BEGIN_SECTION---\s*\n(.*?)\n---END_SECTION---",
    re.DOTALL,
)
SUMMARY_RE = re.compile(
    r"---BEGIN_SUMMARY---\s*\n(.*?)\n---END_SUMMARY---",
    re.DOTALL,
)
METADATA_RE = re.compile(
    r"---METADATA---\s*\n(.*?)\n---END_METADATA---",
    re.DOTALL,
)
# Per-line metadata keys
META_LINE_RE = re.compile(r"^\s*([a-z_][a-z0-9_]*)\s*:\s*(.+?)\s*$", re.IGNORECASE)


def parse_metadata(block: str) -> dict:
    """Convert the metadata block's `key: value` lines into a dict.

    Recognized keys: word_count (int), distinct_chunks_cited (int),
    chunk_ids_cited (list of trimmed strings split on commas).
    Unknown keys are preserved as raw strings.
    """
    out: dict = {}
    for line in block.strip().splitlines():
        m = META_LINE_RE.match(line)
        if not m:
            continue
        key = m.group(1).strip().lower()
        value = m.group(2).strip()
        if key == "word_count" or key == "distinct_chunks_cited":
            try:
                out[key] = int(value)
            except ValueError:
                out[key] = value  # keep raw if unparseable
        elif key == "chunk_ids_cited":
            out[key] = [s.strip() for s in value.split(",") if s.strip()]
        else:
            out[key] = value
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-dir", required=True, type=Path,
                   help="The deep-research run directory")
    p.add_argument("--section-id", required=True,
                   help="The section ID to write under (e.g. s4)")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--response-file", type=Path,
                     help="Path to a file containing the raw subagent response")
    src.add_argument("--response-stdin", action="store_true",
                     help="Read the raw response from stdin")
    args = p.parse_args()

    if not args.run_dir.exists():
        print(f"FATAL: run-dir not found: {args.run_dir}", file=sys.stderr)
        return 2

    if args.response_stdin:
        text = sys.stdin.read()
    else:
        if not args.response_file.exists():
            print(f"FATAL: response file not found: {args.response_file}",
                  file=sys.stderr)
            return 2
        text = args.response_file.read_text(encoding="utf-8")

    if not text.strip():
        print("FATAL: response is empty", file=sys.stderr)
        return 2

    sid = args.section_id.strip()
    if not re.fullmatch(r"s\d+", sid):
        print(f"FATAL: section-id must match s<integer>, got: {sid}",
              file=sys.stderr)
        return 2

    section_match = SECTION_RE.search(text)
    summary_match = SUMMARY_RE.search(text)
    metadata_match = METADATA_RE.search(text)

    missing: list[str] = []
    if not section_match:
        missing.append("---BEGIN_SECTION---/---END_SECTION---")
    if not summary_match:
        missing.append("---BEGIN_SUMMARY---/---END_SUMMARY---")
    if not metadata_match:
        missing.append("---METADATA---/---END_METADATA---")
    if missing:
        print(f"PARSE FAIL: missing block(s): {missing}", file=sys.stderr)
        print(f"  response length: {len(text)} chars", file=sys.stderr)
        print(f"  hint: subagent may have ignored the inline-return contract; "
              f"re-spawn with override prompt", file=sys.stderr)
        return 1

    section_body = section_match.group(1).strip()
    summary_body = summary_match.group(1).strip()
    metadata = parse_metadata(metadata_match.group(1))

    # Sanity checks
    if not section_body:
        print(f"PARSE FAIL: SECTION block is empty for {sid}", file=sys.stderr)
        return 1
    if not summary_body:
        print(f"PARSE FAIL: SUMMARY block is empty for {sid}", file=sys.stderr)
        return 1

    # Ensure directories
    drafts_dir = args.run_dir / "drafts"
    summaries_dir = drafts_dir / "_summaries"
    metadata_dir = drafts_dir / "_metadata"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    summaries_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)

    section_path = drafts_dir / f"{sid}.md"
    summary_path = summaries_dir / f"{sid}.txt"
    metadata_path = metadata_dir / f"{sid}.json"

    section_path.write_text(section_body + "\n", encoding="utf-8")
    summary_path.write_text(summary_body + "\n", encoding="utf-8")
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    # Report
    word_count = metadata.get("word_count", "?")
    chunks_cited = metadata.get("distinct_chunks_cited", "?")
    print(f"OK: parsed section {sid}")
    print(f"  body:     {section_path}  ({section_path.stat().st_size:,} bytes, "
          f"reported {word_count} words)")
    print(f"  summary:  {summary_path}  ({summary_path.stat().st_size:,} bytes)")
    print(f"  metadata: {metadata_path}  ({chunks_cited} distinct chunks cited)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
