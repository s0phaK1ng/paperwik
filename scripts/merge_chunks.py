#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Phase 2.5 — merge searcher_*.json files into unified chunks.json.

Action item D2R-2 (D2 retrospective, 2026-04-27). Promotes the ad-hoc
normalizer used during D2 into a permanent skill artifact. D2 surfaced that
the 4 search subagents each produced slightly different JSON shapes for the
same logical "chunk" object. This script is the single point that enforces
the canonical schema downstream.

Canonical chunk schema (STRICT — see references/search_contract.md):

    {
      "chunk_id": "s3_c1",
      "section_id": "s3",
      "source_url": "https://...",
      "source_title": "...",
      "fetched_at": "2026-04-22T15:30:00Z",
      "sub_question_origin": "<the sub-question that surfaced this source>",
      "text": "<~500-token passage of clean text>"
    }

CoWork's D2 surfaced four empirical input shapes from four parallel searcher
subagents. The normalizer's actual mechanism is field-by-field optional
key-rename detection, not four discrete schema branches — so the same logic
absorbs any subagent that uses one of the recognized rename keys for any of
the canonical 7. The "four variants" terminology below is descriptive of
D2's instance, not exhaustive of what the merger can handle.

The known input shapes (from D2):
    1. Native canonical (list of objects with all 7 keys)             - searcher_1
    2. Key renames (`id`->`chunk_id`, `section`->`section_id`,        - searcher_2
       missing fetched_at + sub_question_origin filled with defaults)
    3. Nested envelope (top-level dict with "chunks" key holding the  - searcher_3
       list, with `id`/`section`/`url`/`title`/`extract`/`subquestion`
       per chunk)
    4. Nested envelope with extra metadata (`searcher`, `run_dir`,    - searcher_4
       `summary` siblings; per-chunk uses `topic`/`date`/`extract`)

The recognized field-rename pairs (any new variant using only these
renames is normalized automatically):
    chunk_id  <- id
    section_id  <- section
    source_url  <- url
    source_title  <- title
    fetched_at  <- date
    sub_question_origin  <- subquestion | topic
    text  <- extract

paperwik typical case: paperwik runs ONE searcher subagent (vs CoWork's
N parallel searchers). The merger still runs for schema-enforcement
consistency; it normalizes the single searcher_1.json to chunks.json
the same way a single CoWork searcher would.

If a chunk doesn't match any known variant (uses unknown key names for
the canonical fields), the script fails loudly so the orchestrator can
re-spawn that searcher rather than silently dropping data.

Usage:
    uv run scripts/merge_chunks.py --run-dir /path/to/runs/<run_id>

Reads:
    {run-dir}/chunks/searcher_*.json    (one or more searcher outputs)
    {run-dir}/plan.json                 (for the canonical section list)

Writes:
    {run-dir}/chunks.json               (unified, normalized, sorted)
    {run-dir}/pending_sections.json     (which sections have chunks)

Exit codes:
    0  success
    1  no searcher files found
    2  fatal error (missing run-dir, plan.json, or unmappable chunk shape)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Canonical schema fields (in canonical order)
CANONICAL_FIELDS = (
    "chunk_id",
    "section_id",
    "source_url",
    "source_title",
    "fetched_at",
    "sub_question_origin",
    "text",
)
DEFAULT_FETCHED_AT = "2026-01-01T00:00:00Z"  # only used as a last-resort fallback
DEFAULT_SUB_QUESTION = "(not recorded)"
# Sections that are framing/synthesis — they don't get direct chunks routed
# from search; the section-writer subagent is given the full corpus instead.
# This list is informational; the actual routing decision is the orchestrator's.
DEFAULT_FRAMING_SECTIONS = ("s1",)


def normalize_chunk(c: dict, source_searcher: str) -> dict:
    """Map any of the 4 known schema variants to the canonical schema.

    Returns the normalized dict. Raises ValueError if the chunk doesn't match
    any known variant.
    """
    if not isinstance(c, dict):
        raise ValueError(f"chunk is not a dict (got {type(c).__name__}) in {source_searcher}")

    chunk_id = c.get("chunk_id") or c.get("id")
    section_id = c.get("section_id") or c.get("section")
    source_url = c.get("source_url") or c.get("url")
    source_title = c.get("source_title") or c.get("title")
    fetched_at = c.get("fetched_at") or c.get("date") or DEFAULT_FETCHED_AT
    sub_q = (
        c.get("sub_question_origin")
        or c.get("subquestion")
        or c.get("topic")
        or DEFAULT_SUB_QUESTION
    )
    text = c.get("text") or c.get("extract")

    # All 7 canonical fields must end up populated
    required = {
        "chunk_id": chunk_id,
        "section_id": section_id,
        "source_url": source_url,
        "source_title": source_title,
        "text": text,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise ValueError(
            f"chunk in {source_searcher} missing required fields {missing}; "
            f"raw keys={sorted(c.keys())}"
        )

    # v0.7.1: hard minimum 200 characters on text. Anything shorter is a
    # content-extraction failure, not a real chunk. v0.7.0's D1 surfaced
    # this when the Haiku searcher emitted ~90-char one-liner summaries
    # instead of ~500-token passages, and section writers couldn't
    # synthesize from them. The contract directive in
    # references/search_contract.md tells the searcher to invoke
    # chunk_text.py rather than hand-writing summaries; this validation
    # is the merge-layer enforcement of the same rule.
    if len(text) < 200:
        raise ValueError(
            f"chunk {chunk_id} in {source_searcher} has text only "
            f"{len(text)} chars; minimum is 200 (chunks under that are "
            f"content-extraction failures, not real chunks). The searcher "
            f"should invoke scripts/chunk_text.py on the fetched markdown "
            f"rather than hand-writing summary one-liners."
        )

    return {
        "chunk_id": chunk_id,
        "section_id": section_id,
        "source_url": source_url,
        "source_title": source_title,
        "fetched_at": fetched_at,
        "sub_question_origin": sub_q,
        "text": text,
    }


def extract_chunks(data, source_searcher: str) -> list[dict]:
    """Pull the chunks list out of a searcher_N.json regardless of envelope."""
    if isinstance(data, list):
        return [normalize_chunk(c, source_searcher) for c in data]
    if isinstance(data, dict):
        if "chunks" in data and isinstance(data["chunks"], list):
            return [normalize_chunk(c, source_searcher) for c in data["chunks"]]
        # Some envelopes might nest under "results" or similar — list known
        # variants here as we discover them.
        raise ValueError(
            f"unrecognized envelope in {source_searcher}: dict with keys "
            f"{sorted(data.keys())} (expected list or dict with 'chunks')"
        )
    raise ValueError(
        f"unrecognized top-level type in {source_searcher}: {type(data).__name__}"
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-dir", required=True, type=Path)
    args = p.parse_args()

    run_dir = args.run_dir
    if not run_dir.exists():
        print(f"FATAL: run-dir not found: {run_dir}", file=sys.stderr)
        return 2

    chunks_dir = run_dir / "chunks"
    if not chunks_dir.exists():
        print(f"FATAL: chunks dir not found: {chunks_dir}", file=sys.stderr)
        return 2

    plan_path = run_dir / "plan.json"
    if not plan_path.exists():
        print(f"FATAL: plan.json not found: {plan_path}", file=sys.stderr)
        return 2

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_sections = [s["section_id"] for s in plan["section_outline"]]

    # Walk searcher files
    searcher_files = sorted(chunks_dir.glob("searcher_*.json"))
    if not searcher_files:
        print(f"No searcher_*.json files in {chunks_dir} — nothing to merge",
              file=sys.stderr)
        return 1

    all_chunks: list[dict] = []
    per_searcher: dict[str, int] = {}
    for searcher_file in searcher_files:
        try:
            data = json.loads(searcher_file.read_text(encoding="utf-8"))
            chunks = extract_chunks(data, searcher_file.stem)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"FATAL: cannot parse {searcher_file.name}: {e}", file=sys.stderr)
            return 2
        per_searcher[searcher_file.name] = len(chunks)
        all_chunks.extend(chunks)

    # De-dup chunk_ids globally — if a searcher reused an id, re-number within
    # the section so every id is unique system-wide.
    ids_seen = Counter(c["chunk_id"] for c in all_chunks)
    dups = {k: v for k, v in ids_seen.items() if v > 1}
    if dups:
        print(f"WARN: duplicate chunk_ids: {dups} — re-numbering per section",
              file=sys.stderr)
        counters: dict[str, int] = defaultdict(int)
        for c in all_chunks:
            sec = c["section_id"]
            counters[sec] += 1
            c["chunk_id"] = f"{sec}_c{counters[sec]}"

    # Sort by section, then by ordinal within section
    def sort_key(c: dict):
        sid = c["section_id"]
        sec_num = int(sid.lstrip("s")) if sid.lstrip("s").isdigit() else 99
        cid = c["chunk_id"]
        cn = cid.split("_c")[-1]
        cn_int = int(cn) if cn.isdigit() else 999
        return (sec_num, cn_int)

    all_chunks.sort(key=sort_key)

    # Section coverage
    section_chunks: dict[str, list[str]] = defaultdict(list)
    for c in all_chunks:
        section_chunks[c["section_id"]].append(c["chunk_id"])

    # Write unified chunks.json
    out_chunks = run_dir / "chunks.json"
    out_chunks.write_text(json.dumps(all_chunks, indent=2, ensure_ascii=False),
                          encoding="utf-8")

    # Write pending_sections.json
    direct_chunk_sections = sorted(section_chunks.keys())
    framing_sections = [s for s in plan_sections if s not in direct_chunk_sections]
    pending = {
        "all_sections": plan_sections,
        "sections_with_chunks": direct_chunk_sections,
        "framing_sections_full_corpus": framing_sections,
        "sections_chunk_count": {sid: len(section_chunks[sid])
                                 for sid in direct_chunk_sections},
        "total_chunks": len(all_chunks),
    }
    out_pending = run_dir / "pending_sections.json"
    out_pending.write_text(json.dumps(pending, indent=2), encoding="utf-8")

    # Report
    print(f"=== merge_chunks complete ===")
    print(f"Per-searcher input: {per_searcher}")
    print(f"Total chunks merged: {len(all_chunks)}")
    print(f"Distinct source URLs: {len({c['source_url'] for c in all_chunks})}")
    print(f"\nSection coverage:")
    for sid in plan_sections:
        title = next((s["title"] for s in plan["section_outline"]
                      if s["section_id"] == sid), "?")
        count = len(section_chunks.get(sid, []))
        flag = "" if count > 0 else "  (framing — full-corpus synthesis)"
        print(f"  {sid:<5} {title:<55} {count:>3} chunks{flag}")

    print(f"\nFiles written:")
    print(f"  {out_chunks}  ({out_chunks.stat().st_size:,} bytes)")
    print(f"  {out_pending}  ({out_pending.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
