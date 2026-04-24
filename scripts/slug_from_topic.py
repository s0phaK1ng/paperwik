#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Generate a dad-readable filename slug from a research topic.

Action item #413. Paperwik drops research outputs into ~/Paperwik/Vault/Inbox/
where they appear in the user's Obsidian file list. Filenames must be
readable at a glance, not computer-ish.

CoWork's slug pattern:  deep_research_cognitivehe_2026-04-22.md   (ugly)
Paperwik's slug pattern: Cognitive Health Strategies - 2026-04-22.md  (dad)

Rules:
1. Title Case the topic (first letter of each significant word uppercased).
2. Strip filesystem-unsafe characters: < > : " / \\ | ? *
3. Collapse runs of whitespace to single spaces.
4. Strip leading/trailing whitespace and punctuation.
5. Truncate topic portion to 60 chars (reserve room for " - YYYY-MM-DD.md").
6. Append " - YYYY-MM-DD.md".

Stopwords kept lowercase (so "Strategies for Aging Adults" not "Strategies
For Aging Adults"):
    a an the and or but of in on at to for from with

No spaCy dependency -- a small stopword set and str.title() + regex handle
the 99% case for English topics, which is all paperwik ships for.

Usage (CLI):
    python scripts/slug_from_topic.py "cognitive health strategies for aging adults"
    -> Cognitive Health Strategies for Aging Adults - 2026-04-24.md

Usage (library):
    from slug_from_topic import slug_filename
    name = slug_filename("cognitive health for aging")  # uses today's date
    name = slug_filename("...", date="2026-04-24")       # explicit date
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys


STOPWORDS_LOWER = {
    "a", "an", "the", "and", "or", "but",
    "of", "in", "on", "at", "to", "for", "from", "with",
    "by", "as", "is", "vs",
}

# Characters Windows / POSIX filesystems both forbid or treat specially.
UNSAFE_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Collapse whitespace + trim trailing punctuation/whitespace.
WHITESPACE_RE = re.compile(r"\s+")
TRAILING_PUNCT_RE = re.compile(r"[\s\-_.,;:!?]+$")
LEADING_PUNCT_RE = re.compile(r"^[\s\-_.,;:!?]+")


def _title_case_with_stopwords(text: str) -> str:
    words = text.split()
    out: list[str] = []
    for i, w in enumerate(words):
        lw = w.lower()
        if i > 0 and lw in STOPWORDS_LOWER:
            out.append(lw)
        else:
            out.append(lw[:1].upper() + lw[1:])
    return " ".join(out)


def _topic_to_title(topic: str, max_chars: int = 60) -> str:
    """Clean + title-case the topic; truncate to max_chars on word boundary."""
    # Strip unsafe FS chars first (replace with space to preserve word boundary)
    cleaned = UNSAFE_CHARS_RE.sub(" ", topic)
    # Collapse whitespace
    cleaned = WHITESPACE_RE.sub(" ", cleaned).strip()
    # Trim junk from edges
    cleaned = TRAILING_PUNCT_RE.sub("", LEADING_PUNCT_RE.sub("", cleaned))
    # Truncate on word boundary
    if len(cleaned) > max_chars:
        cut = cleaned[:max_chars]
        last_space = cut.rfind(" ")
        if last_space > 0:
            cut = cut[:last_space]
        cleaned = cut
    # Title-case
    return _title_case_with_stopwords(cleaned)


def slug_filename(topic: str, date: str | None = None, max_chars: int = 60) -> str:
    """Return 'Title Case Topic - YYYY-MM-DD.md' (dad-readable)."""
    title = _topic_to_title(topic, max_chars=max_chars)
    if not title:
        title = "Research"
    if date is None:
        date = dt.date.today().isoformat()
    return f"{title} - {date}.md"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("topic", help="The research topic string")
    p.add_argument("--date", default=None, help="YYYY-MM-DD (defaults to today)")
    p.add_argument("--max-chars", type=int, default=60)
    args = p.parse_args()

    name = slug_filename(args.topic, date=args.date, max_chars=args.max_chars)
    print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
