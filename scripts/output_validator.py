#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6.0"]
# ///
"""Validate a deep-research output markdown file against the non-negotiable
format contract (decision #305).

Action item A6. Must be run BEFORE the engine writes the final file to the
drop target. Blocks writes on any violation — a malformed document would
pollute the ingestion pipeline.

Usage:
    uv run scripts/output_validator.py --file /path/to/final.md

Exit codes:
    0  valid — safe to write
    1  invalid — one or more contract violations (prints them to stderr)
    2  fatal — could not parse the file at all

Checks:
    1. YAML frontmatter present (opens with `---`, closes with `---`)
    2. Frontmatter contains ALL required keys: topic, date, research_tool,
       cost, sources_count
    3. Body contains required H2 sections: `## Context`, `## Findings`,
       `## Gaps & Caveats`. `## Contradictions` is optional.
    4. Body concludes with a `## Sources` H2
    5. Sources section contains a markdown table with at least: ID, URL, Title, Access date
    6. Every citation in the body (`[s<n>_c<n>]`) corresponds to a row in the
       Sources table with the same ID (OR a chunk_id that the run's
       chunks.json maps to a source — but that validation is a warning, not
       a hard block, since this script doesn't take the chunks.json path)
    7. Total word count >= 3000 (minimum document length guard)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml not installed. Run via `uv run` with the PEP-723 header.",
          file=sys.stderr)
    sys.exit(2)


REQUIRED_FRONTMATTER_KEYS = {"topic", "date", "research_tool", "cost", "sources_count"}
# v2 (2026-04-27, supersedes part of decision #305):
# Required H2 sections relaxed to allow topic-specific section names.
# REQUIRED: ## Context first, ## Sources last, plus >=3 other H2 sections in between.
# RECOMMENDED (warning only): ## Gaps & Caveats — emit warning if absent, not a hard error.
REQUIRED_H2_FIRST = "## Context"
REQUIRED_H2_LAST = "## Sources"
RECOMMENDED_H2 = "## Gaps & Caveats"
MIN_OTHER_H2_SECTIONS = 3  # excluding Context and Sources
CITATION_RE = re.compile(r"\[((?:s\d+_c\d+)(?:\s*,\s*s\d+_c\d+)*)\]")
# Sources table row: | s1_c1 | https://... | Title | 2026-... |
SOURCES_ROW_RE = re.compile(
    r"\|\s*(?P<id>s\d+_c\d+|[A-Za-z0-9_-]+)\s*\|\s*(?P<url>https?://\S+)\s*\|",
)


def parse_frontmatter(text: str) -> tuple[dict | None, str]:
    """Return (frontmatter_dict, body) or (None, full_text) if missing/invalid."""
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return None, text
    fm_raw = text[4:end]
    body = text[end + 5:]
    try:
        fm = yaml.safe_load(fm_raw) or {}
        if not isinstance(fm, dict):
            return None, text
        return fm, body
    except yaml.YAMLError:
        return None, text


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--file", required=True, type=Path)
    args = p.parse_args()

    if not args.file.exists():
        print(f"FATAL: file not found: {args.file}", file=sys.stderr)
        return 2

    text = args.file.read_text(encoding="utf-8")
    errors: list[str] = []
    warnings: list[str] = []

    # Check 1 & 2: frontmatter
    fm, body = parse_frontmatter(text)
    if fm is None:
        errors.append("YAML frontmatter missing or malformed. Must open with `---` on line 1, close with `---`, contain valid YAML.")
    else:
        missing = REQUIRED_FRONTMATTER_KEYS - set(fm.keys())
        if missing:
            errors.append(f"Frontmatter missing required keys: {sorted(missing)}")
        # Specific validity of cost/sources_count
        if "sources_count" in fm and not isinstance(fm["sources_count"], int):
            errors.append(f"Frontmatter `sources_count` must be an integer, got {type(fm['sources_count']).__name__}")
        if "cost" in fm and fm["cost"] is not None and not isinstance(fm["cost"], (int, float)):
            errors.append(f"Frontmatter `cost` must be a number or null, got {type(fm['cost']).__name__}")

    # Check 3: structural H2 sections (v2 relaxed contract)
    # Required: ## Context first, ## Sources last
    # Required: >=3 other H2 sections between Context and Sources (any topic-specific names)
    # Recommended (warning only): ## Gaps & Caveats
    body_to_check = body if fm is not None else text

    # Find all H2 section headers (lines starting with "## " at line boundaries)
    h2_pattern = re.compile(r"(?:^|\n)(## [^\n]+)", re.MULTILINE)
    h2_matches = [(m.start(), m.group(1).strip()) for m in h2_pattern.finditer(body_to_check)]

    if not h2_matches:
        errors.append("No H2 sections found in body")
    else:
        # First H2 must be ## Context
        first_h2_pos, first_h2 = h2_matches[0]
        if first_h2 != REQUIRED_H2_FIRST:
            errors.append(f"First H2 must be `{REQUIRED_H2_FIRST}`, got `{first_h2}`")

        # ## Sources must be PRESENT (not necessarily last — trailing appendices like
        # ## Verification are allowed after Sources)
        h2_titles = [h for _, h in h2_matches]
        if REQUIRED_H2_LAST not in h2_titles:
            errors.append(f"Required H2 missing: `{REQUIRED_H2_LAST}` (must be present; trailing H2s after it are allowed)")
        else:
            # Sources must come AFTER Context (not in the first half)
            sources_idx_in_h2 = h2_titles.index(REQUIRED_H2_LAST)
            context_idx_in_h2 = h2_titles.index(REQUIRED_H2_FIRST) if REQUIRED_H2_FIRST in h2_titles else 0
            if sources_idx_in_h2 <= context_idx_in_h2:
                errors.append(f"`{REQUIRED_H2_LAST}` must come after `{REQUIRED_H2_FIRST}`")

            # Count H2 sections strictly between Context and Sources
            intermediate = h2_titles[context_idx_in_h2 + 1: sources_idx_in_h2]
            if len(intermediate) < MIN_OTHER_H2_SECTIONS:
                errors.append(
                    f"Body needs at least {MIN_OTHER_H2_SECTIONS} other H2 sections "
                    f"between `{REQUIRED_H2_FIRST}` and `{REQUIRED_H2_LAST}`; "
                    f"found {len(intermediate)}: {intermediate}"
                )

        # Recommended Gaps & Caveats (warning only)
        if RECOMMENDED_H2 not in h2_titles:
            warnings.append(
                f"Recommended section `{RECOMMENDED_H2}` is absent. "
                "This section is the conventional home for unresolved questions and single-source claims; "
                "consider adding for ingestion clarity."
            )

    # Check 5: Sources table
    sources_idx = body_to_check.find("## Sources")
    if sources_idx >= 0:
        sources_body = body_to_check[sources_idx:]
        if "|" not in sources_body:
            errors.append("`## Sources` section must contain a markdown table (no `|` characters found)")
        else:
            # Look for at least one row matching chunk_id-like pattern
            if not SOURCES_ROW_RE.search(sources_body):
                errors.append("`## Sources` table must contain at least one row with a chunk-id-like ID and an http(s) URL")

    # Check 6: citations in body resolve to Sources table
    if sources_idx >= 0:
        findings_body = body_to_check[:sources_idx]
        sources_body = body_to_check[sources_idx:]
        cited_ids: set[str] = set()
        for m in CITATION_RE.finditer(findings_body):
            for cid in m.group(1).split(","):
                cited_ids.add(cid.strip())
        sourced_ids = {m.group("id") for m in SOURCES_ROW_RE.finditer(sources_body)}
        missing_sources = cited_ids - sourced_ids
        if missing_sources:
            # Hard error — a citation with no source row is exactly the kind of
            # ingestion trap the Sanitizer is supposed to prevent
            errors.append(
                f"Citations in body have no matching row in Sources table: "
                f"{sorted(missing_sources)[:10]}{' ...' if len(missing_sources) > 10 else ''} "
                f"(total: {len(missing_sources)})"
            )
        unused_sources = sourced_ids - cited_ids
        if unused_sources:
            warnings.append(
                f"Sources table has {len(unused_sources)} IDs that are never cited in the body "
                f"(not a contract violation, but suspicious)"
            )

    # Check 7: minimum word count
    words = len(re.findall(r"\b\w+\b", body_to_check))
    if words < 3000:
        errors.append(f"Body word count {words} is below minimum 3000 (deep research outputs must be substantive)")

    # Report
    if warnings:
        print("WARNINGS:", file=sys.stderr)
        for w in warnings:
            print(f"  ⚠ {w}", file=sys.stderr)

    if errors:
        print(f"\nOUTPUT CONTRACT VIOLATIONS ({len(errors)}):", file=sys.stderr)
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        print(f"\nFile is INVALID. Refusing to write to drop target: {args.file}", file=sys.stderr)
        return 1

    print(f"OK: {args.file.name} passes the output contract")
    print(f"  word count: {words}")
    if fm:
        print(f"  topic: {fm.get('topic', '?')}")
        print(f"  sources_count: {fm.get('sources_count', '?')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
