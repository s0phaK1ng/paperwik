#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Chunk a fetched markdown document into passages with unique IDs.

Part of research skill A3 (search orchestration). Invoked by Claude Code
per-source after WebFetch normalizes the page into markdown.

Usage:
    uv run scripts/chunk_text.py \\
        --section-id s3 \\
        --source-url https://example.com/doc \\
        --source-title "Article Title" \\
        --sub-question-origin "What is X?" \\
        --text-file /path/to/fetched.md \\
        --chunk-size-tokens 500 \\
        --output-append /path/to/chunks.json

Appends JSON-array entries to the output file. If the output file doesn't
exist, creates it with `[]`. Safe to run concurrently on the same file
(uses a simple read-modify-write with timestamp-based sequencing -- not
transactional, but OK for single-user sequential invocation).

Chunk IDs are `s<section_id>_c<n>` where n is the next available integer
for that section (inspects the existing chunks.json to continue numbering).

Ported verbatim from CoWork deep-research skill at 2026-04-24 (paperwik
action item #408). No paperwik-specific changes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path


def count_tokens_approx(text: str) -> int:
    """Rough token count: ~4 chars per token for English text."""
    return max(1, len(text) // 4)


def split_into_paragraphs(text: str) -> list[str]:
    """Split markdown into paragraph-sized units preserving code blocks and tables."""
    # Protect code blocks -- replace triple-backtick blocks with placeholders
    code_blocks: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        code_blocks.append(match.group(0))
        return f"\x00CODEBLOCK{len(code_blocks) - 1}\x00"

    text = re.sub(r"```.*?```", _stash, text, flags=re.DOTALL)
    # Split on blank lines
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    # Restore code blocks
    restored: list[str] = []
    for p in paragraphs:
        for i, cb in enumerate(code_blocks):
            p = p.replace(f"\x00CODEBLOCK{i}\x00", cb)
        restored.append(p)
    return restored


def chunk_paragraphs(paragraphs: list[str], target_tokens: int) -> list[str]:
    """Greedy-pack paragraphs into chunks that approach target_tokens."""
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for p in paragraphs:
        p_tokens = count_tokens_approx(p)
        # If a single paragraph exceeds target, emit it as its own chunk
        if p_tokens >= target_tokens:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_tokens = 0
            chunks.append(p)
            continue
        if current_tokens + p_tokens > target_tokens and current:
            chunks.append("\n\n".join(current))
            current = [p]
            current_tokens = p_tokens
        else:
            current.append(p)
            current_tokens += p_tokens
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def load_existing(output_path: Path) -> list[dict]:
    if not output_path.exists():
        return []
    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except Exception as exc:
        print(f"WARNING: could not parse {output_path} ({exc}); starting fresh",
              file=sys.stderr)
        return []


def next_chunk_number(existing: list[dict], section_id: str) -> int:
    """Find highest c<n> for this section_id and return n+1."""
    max_n = 0
    prefix = f"{section_id}_c"
    for entry in existing:
        cid = entry.get("chunk_id", "")
        if cid.startswith(prefix):
            try:
                n = int(cid[len(prefix):])
                max_n = max(max_n, n)
            except ValueError:
                continue
    return max_n + 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--section-id", required=True, help="e.g. s3")
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--source-title", required=True)
    parser.add_argument("--sub-question-origin", required=True)
    parser.add_argument("--text-file", required=True, type=Path)
    parser.add_argument("--chunk-size-tokens", type=int, default=500)
    parser.add_argument("--output-append", required=True, type=Path)
    args = parser.parse_args()

    if not args.text_file.exists():
        print(f"ERROR: text file not found: {args.text_file}", file=sys.stderr)
        return 1

    text = args.text_file.read_text(encoding="utf-8", errors="replace")
    paragraphs = split_into_paragraphs(text)
    chunks_text = chunk_paragraphs(paragraphs, args.chunk_size_tokens)

    args.output_append.parent.mkdir(parents=True, exist_ok=True)
    existing = load_existing(args.output_append)
    start_n = next_chunk_number(existing, args.section_id)

    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    new_entries = []
    for i, chunk_text in enumerate(chunks_text):
        entry = {
            "chunk_id": f"{args.section_id}_c{start_n + i}",
            "section_id": args.section_id,
            "source_url": args.source_url,
            "source_title": args.source_title,
            "fetched_at": now,
            "sub_question_origin": args.sub_question_origin,
            "text": chunk_text,
            "token_count_approx": count_tokens_approx(chunk_text),
        }
        new_entries.append(entry)

    combined = existing + new_entries
    args.output_append.write_text(json.dumps(combined, indent=2), encoding="utf-8")

    print(f"Chunked {len(chunks_text)} passages from {args.source_url}")
    print(f"  IDs: {args.section_id}_c{start_n} .. {args.section_id}_c{start_n + len(chunks_text) - 1}")
    print(f"  Total chunks in {args.output_append.name}: {len(combined)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
