# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     "onnxruntime>=1.16.3",
#     "onnx>=1.15.0",
#     "sympy>=1.12.0",
#     "tokenizers>=0.15.0",
#     "numpy>=1.26.0",
#     "huggingface-hub>=0.20.0",
# ]
# ///
#
# v0.6.3: `onnx` added (see classify.py header for the rationale).
# v0.6.5: `sympy` added (see classify.py header).
"""
source_classifier.py -- Classify ingested sources by document TYPE.

Single function:

    classify_source_type(content, metadata=None) -> (type, confidence)

The 6-type taxonomy is fixed at v0.6.0 ship:

    academic    -- peer-reviewed paper, preprint, thesis, technical report
    article     -- web article, blog post, magazine piece, journalism
    newsletter  -- email-style digest with subscribe/unsubscribe boilerplate
    social      -- social-media post, forum thread, X/Reddit/HN excerpt
    journal     -- personal journaling, diary, daily-note style
    reference   -- documentation, manual, glossary, lookup-style content

If the measure-classification telemetry shows a label never fires (e.g.,
"journal" is rare in the dad corpus), a future v0.6.x can drop it cheaply.

Used by paperwik-ingest at NEW Step 1.5 (BEFORE subagent dispatch) so the
subagent's extraction prompt can be parameterized by source type:

    academic   -> extract methodology / findings / limitations
    article    -> thesis + key arguments
    newsletter -> summary minus subscribe/footer chrome
    social     -> preserve verbatim as quoted block
    journal    -> file as personal journaling
    reference  -> minimal-edit searchable index

Implementation notes:
    * Single-label argmax (softmax across types). Source type IS exclusive.
    * Pulls only the first 500 chars + optional URL/filename metadata as
      input — the type signal is dense at the head of the document and
      we don't need to embed gigabytes of body text just to tell article
      from newsletter.
    * Confidence is the softmax probability of the chosen type. Useful
      for the future paperwik-measure-classification skill to flag
      borderline cases for manual review.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

# classify.py is in the same scripts/ directory. uv-run sets sys.path[0]
# to the script's directory, so a flat import works.
from classify import classify, DEFAULT_TEMPLATE  # noqa: E402


# Hypothesis template tuned for source-type classification. Notice it asks
# about FORMAT, not topic — distinguishes from project_router's TOPIC-focused
# template.
SOURCE_TYPE_TEMPLATE = "This document is best categorized as a {} by its format and structure."

# Descriptive label expansions. We give the NLI model richer phrases than the
# bare type names so the entailment signal is stronger. These descriptive
# labels are what the model sees; the returned `type` is the short form.
SOURCE_TYPES: dict[str, str] = {
    "academic":   "peer-reviewed academic paper, preprint, or technical research report",
    "article":    "web article, blog post, or piece of journalism",
    "newsletter": "email newsletter with subscribe and unsubscribe boilerplate",
    "social":     "social media post, forum thread, or short online discussion",
    "journal":    "personal journal entry, diary, or daily note",
    "reference":  "reference documentation, manual, glossary, or lookup material",
}

# Truncate to the first N chars for type classification. The signal is
# concentrated at the head of the document (title, first paragraph, headers).
HEAD_CHARS = 500


def classify_source_type(
    content: str,
    metadata: dict[str, Any] | None = None,
) -> tuple[str, float]:
    """Classify a source by format / structural type.

    Args:
        content: the source text. We use the first HEAD_CHARS characters.
        metadata: optional dict; if it contains 'url' or 'filename',
                  those hints are prepended to the input as a one-line
                  context cue (helps disambiguate e.g. PDF-with-doi from
                  blog post when the prose-only body looks similar).

    Returns:
        (type, confidence) where type is one of the SOURCE_TYPES keys and
        confidence is the softmax probability of that type in [0, 1].
    """
    head = (content or "")[:HEAD_CHARS]

    cues: list[str] = []
    if metadata:
        url = metadata.get("url") or metadata.get("source_url")
        if url:
            cues.append(f"Source URL: {url}")
        fname = metadata.get("filename") or metadata.get("source_filename")
        if fname:
            cues.append(f"Source file: {fname}")
    if cues:
        head = "\n".join(cues) + "\n\n" + head

    # Use the descriptive expansions as labels for stronger NLI signal.
    label_keys = list(SOURCE_TYPES.keys())
    label_phrases = [SOURCE_TYPES[k] for k in label_keys]

    results = classify(
        text=head,
        labels=label_phrases,
        multi_label=False,           # source type IS exclusive
        template=SOURCE_TYPE_TEMPLATE,
    )

    if not results:
        return ("article", 0.0)  # safe default — most non-academic content is article-like

    top_phrase, top_prob = results[0]
    # Map the descriptive phrase back to the short type key.
    for k, v in SOURCE_TYPES.items():
        if v == top_phrase:
            return (k, float(top_prob))
    # Defensive fallback if phrase mapping somehow breaks.
    return ("article", float(top_prob))


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #

def _read_content(path: str | None, stdin_flag: bool, text_arg: str | None) -> str:
    if text_arg:
        return text_arg
    if stdin_flag:
        return sys.stdin.read()
    if path:
        from pathlib import Path
        return Path(path).read_text(encoding="utf-8", errors="replace")
    raise SystemExit("Provide --text, --file, or --stdin.")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Classify a source document by structural type (academic/article/newsletter/social/journal/reference).",
    )
    parser.add_argument("--text", help="Inline source text.")
    parser.add_argument("--file", help="Path to source file.")
    parser.add_argument("--stdin", action="store_true", help="Read source from stdin.")
    parser.add_argument("--url", help="Optional source URL hint.")
    parser.add_argument("--filename", help="Optional source filename hint.")
    args = parser.parse_args(argv[1:])

    content = _read_content(args.file, args.stdin, args.text)

    metadata: dict[str, Any] = {}
    if args.url:
        metadata["url"] = args.url
    if args.filename:
        metadata["filename"] = args.filename

    type_, confidence = classify_source_type(content, metadata=metadata or None)
    print(json.dumps({"type": type_, "confidence": confidence}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
