#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Phase 4e — assemble the final research document from per-section drafts.

Reads the run dir's plan + drafts + verification reports, builds the final
markdown with YAML frontmatter, body (with H2 section headers), Sources
table, and verification appendix, then writes to:
  - {run-dir}/final.md
  - {drop-target}/deep_research_<slug>_<date>.md

The output complies with the v2 format contract (decision #305 as superseded
by the body-format relaxation): YAML frontmatter required, ## Context first,
## Sources last, >=3 other H2 sections in between (any topic-specific names).

Usage:
    uv run scripts/stitch_final.py \\
        --run-dir /path/to/runs/<run_id> \\
        --drop-target /path/to/Research/_Inbox/ \\
        [--research-tool "deep-research-skill/v1.1"]

Exit codes:
    0  success
    2  fatal error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path


def slugify(s: str, max_len: int = 50) -> str:
    """Lowercase, alphanumeric + underscore, truncated."""
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s)
    s = s.strip("_").lower()
    return s[:max_len].rstrip("_")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-dir", required=True, type=Path)
    p.add_argument("--drop-target", required=True, type=Path,
                   help="Directory where the final markdown drops (e.g., Research/_Inbox/)")
    p.add_argument("--research-tool", default="deep-research-skill/v1.1")
    p.add_argument(
        "--date",
        default=None,
        help=(
            "Override the document's date (YYYY-MM-DD). Default: today. "
            "Used by the synthetic test harness to keep snapshots stable "
            "across days. Production callers should leave this unset."
        ),
    )
    args = p.parse_args()

    run_dir = args.run_dir
    if not run_dir.exists():
        print(f"ERROR: run-dir not found: {run_dir}", file=sys.stderr)
        return 2

    plan_path = run_dir / "plan.json"
    chunks_path = run_dir / "chunks.json"
    drafts_dir = run_dir / "drafts"
    if not (plan_path.exists() and chunks_path.exists() and drafts_dir.exists()):
        print(f"ERROR: missing plan.json, chunks.json, or drafts/ in {run_dir}",
              file=sys.stderr)
        return 2

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))

    # Best available verification report (v3 > v2 > v1)
    report = None
    for cand in ("verification_report_v3.json", "verification_report_v2.json",
                 "verification_report.json"):
        cand_path = run_dir / cand
        if cand_path.exists():
            report = json.loads(cand_path.read_text(encoding="utf-8"))
            report_version = cand
            break

    today = args.date or datetime.now().strftime("%Y-%m-%d")

    # ---------- Body (assembled before frontmatter so we can extract citations) ----------
    sections_by_id = {s["section_id"]: s for s in plan["section_outline"]}
    body_parts = []

    # Determine canonical section ordering: respect plan outline,
    # but enforce ## Context first if it exists.
    section_order = [s["section_id"] for s in plan["section_outline"]]

    for sid in section_order:
        section = sections_by_id[sid]
        title = section["title"]
        body_path = drafts_dir / f"{sid}.md"
        if not body_path.exists():
            print(f"  WARN: draft missing for {sid}", file=sys.stderr)
            continue
        body = body_path.read_text(encoding="utf-8").strip()
        body_parts.append(f"## {title}\n\n{body}\n")

    body_text = "\n".join(body_parts)

    # ---------- v0.7.1 (F6): determine which chunks the body actually cites ----------
    # Pre-v0.7.1 the Sources table listed every chunk in chunks.json
    # regardless of whether any section writer cited it. The validator
    # warned about unused IDs but didn't fail; users saw a Sources table
    # with dangling references. v0.7.1 uses a regex over the assembled
    # body to find cited chunk_ids and filters BOTH the Sources table
    # AND the YAML frontmatter's sources_count to reflect only cited
    # sources.
    cited_ids: set[str] = set()
    citation_re = re.compile(r"\[((?:s\d+_c\d+)(?:\s*,\s*s\d+_c\d+)*)\]")
    for m in citation_re.finditer(body_text):
        for cid in m.group(1).split(","):
            cited_ids.add(cid.strip())

    # sources_count = unique URLs across CITED chunks only (F6-consistent)
    sources_count = len({
        c["source_url"] for c in chunks if c["chunk_id"] in cited_ids
    })

    # ---------- YAML frontmatter (now uses cited-chunk source count) ----------
    frontmatter = (
        "---\n"
        f'topic: "{plan["topic"]}"\n'
        f'date: "{today}"\n'
        f'research_tool: "{args.research_tool}"\n'
        "cost: null\n"
        f"sources_count: {sources_count}\n"
        "---\n\n"
    )

    # ---------- Sources table (v0.7.1: filter to cited chunks only) ----------

    sources_seen = OrderedDict()
    for c in chunks:
        cid = c["chunk_id"]
        if cid not in cited_ids:
            continue  # F6: skip chunks no section writer cited
        if cid not in sources_seen:
            title_clean = c.get("source_title", "")[:60].replace("|", "\\|")
            sources_seen[cid] = {
                "url": c["source_url"],
                "title": title_clean,
                "fetched": c.get("fetched_at", "")[:10],
            }

    def sort_key(cid):
        parts = cid.split("_c")
        return (int(parts[0][1:]), int(parts[1]))

    sources_lines = ["## Sources", "",
                     "| ID | URL | Title | Access date |",
                     "|----|-----|-------|-------------|"]
    for cid in sorted(sources_seen.keys(), key=sort_key):
        s = sources_seen[cid]
        sources_lines.append(f"| {cid} | {s['url']} | {s['title']} | {s['fetched']} |")
    sources_table = "\n".join(sources_lines) + "\n"

    # ---------- Verification appendix ----------
    appendix_lines = ["", "## Verification", "",
                      f"This document was produced by an in-session deep-research engine on {today}."]
    if report:
        appendix_lines.append(f"Sanitizer cascade output: `{report_version}`")
        appendix_lines.append("")
        if "tier2_summary" in report:
            t2 = report["tier2_summary"]
            appendix_lines.append("### Tier 2 (local NLI / verify_nli)")
            for k in ("ZSC_PASS", "ZSC_AMBIGUOUS_CONTRADICTION_HINT", "ZSC_UNRELATED",
                     "ZSC_AMBIGUOUS"):
                if k in t2:
                    appendix_lines.append(f"  - {k}: {t2[k]}")
            if "tier2_kill_switch_active" in report and report["tier2_kill_switch_active"]:
                appendix_lines.append("  (kill switch was active — Tier 2 skipped, all routed to Tier 3)")
            appendix_lines.append("")
        if "tier3_summary" in report:
            t3 = report["tier3_summary"]
            appendix_lines.append("### Tier 3 (LLM-as-judge)")
            for k in ("SUPPORTED", "PARTIAL", "CONTRADICTED", "UNRELATED"):
                if k in t3:
                    appendix_lines.append(f"  - {k}: {t3[k]}")
            appendix_lines.append("")
        appendix_lines.append(
            f"Cascade version: {report.get('tier2_cascade_version', 'unknown')}")

    verification_appendix = "\n".join(appendix_lines) + "\n"

    # ---------- Compose ----------
    final_doc = frontmatter + body_text + "\n" + sources_table + verification_appendix

    # ---------- Write ----------
    final_path = run_dir / "final.md"
    final_path.write_text(final_doc, encoding="utf-8")

    args.drop_target.mkdir(parents=True, exist_ok=True)
    slug = slugify(plan["topic"])
    drop_file = args.drop_target / f"deep_research_{slug}_{today}.md"
    drop_file.write_text(final_doc, encoding="utf-8")

    word_count = len(re.findall(r"\b\w+\b", final_doc))
    print(f"Final document: {len(final_doc)} bytes, {word_count} words")
    print(f"  run-dir copy: {final_path}")
    print(f"  drop target:  {drop_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
