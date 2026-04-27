# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = []
# ///
"""
populate_label.py -- v0.6.4 architectural enforcement of .paperwik/label.txt.

The blessed way to write a project's descriptive label. Refuses if:
  - --label is empty or whitespace-only
  - --label still starts with the v0.6.2 TODO marker prefix
  - --label is shorter than 20 chars (probably not descriptive enough)
  - --label is longer than 300 chars (probably accidentally pasted a paragraph)

Why this exists: in v0.6.0/v0.6.1/v0.6.2 sandbox testing the agent
*reliably* skipped writing a real descriptive label, leaving the TODO
marker in place and silently disabling ZSC routing for the project.
SKILL.md prose tightening (D11) didn't change this. v0.6.4 takes the
D12 approach: move the operation into a tool with input validation,
making the failure mode (writing TODO marker) impossible by construction.

Usage:
    uv run populate_label.py --project "PostgreSQL" \\
        --label "Open-source ORDBMS internals, MVCC, replication, and ecosystem extensions."

Exits non-zero on validation failure with an explicit error message
instructing the agent how to fix.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

MIN_LABEL_CHARS = 20
MAX_LABEL_CHARS = 300
TODO_LABEL_PREFIX = "TODO:"


def _label_path(project: str) -> Path:
    user_profile = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    return (
        user_profile / "Paperwik" / "Vault" / "Projects"
        / project / ".paperwik" / "label.txt"
    )


def _validate_label(label: str) -> None:
    """Hard-fail with explicit error if the label is malformed."""
    s = label.strip()
    if not s:
        print(
            "[populate_label] ERROR: --label is empty after stripping. "
            "Provide a real one-sentence descriptive label of the project's "
            "topical focus (60-180 chars recommended).",
            file=sys.stderr,
        )
        sys.exit(2)
    if s.startswith(TODO_LABEL_PREFIX):
        print(
            f"[populate_label] ERROR: --label still has the TODO marker "
            f"prefix. The whole point of this tool is to REPLACE the TODO "
            f"marker with a real descriptive sentence. You provided:\n"
            f"  {s[:100]}{'...' if len(s) > 100 else ''}\n"
            f"Re-run with a real descriptive label.",
            file=sys.stderr,
        )
        sys.exit(2)
    if len(s) < MIN_LABEL_CHARS:
        print(
            f"[populate_label] ERROR: --label is {len(s)} chars, minimum "
            f"is {MIN_LABEL_CHARS}. Vague labels like 'Notes' or 'Articles' "
            f"don't give the ZSC router enough signal to compare against. "
            f"Aim for one sentence describing the project's topical focus.",
            file=sys.stderr,
        )
        sys.exit(2)
    if len(s) > MAX_LABEL_CHARS:
        print(
            f"[populate_label] ERROR: --label is {len(s)} chars, max is "
            f"{MAX_LABEL_CHARS}. Long labels are noise -- the ZSC router "
            f"reads them as the hypothesis side of a single NLI pair. "
            f"One sentence is the target.",
            file=sys.stderr,
        )
        sys.exit(2)


def populate_label(project: str, label: str) -> Path:
    """Write the validated label to <Project>/.paperwik/label.txt.

    Returns the absolute Path written. Raises (via sys.exit) on validation
    failure or if the project directory doesn't exist.
    """
    _validate_label(label)

    target = _label_path(project)
    if not target.parent.parent.exists():
        # The project folder itself is missing -- the router should have
        # created it. This is a hard error; populate_label is not a project
        # creator.
        print(
            f"[populate_label] ERROR: project directory does not exist: "
            f"{target.parent.parent}\n"
            f"The router (project_router.py) is responsible for creating "
            f"the project folder. Run that first, then call this tool.",
            file=sys.stderr,
        )
        sys.exit(1)

    target.parent.mkdir(parents=True, exist_ok=True)
    # Strip + normalize: collapse internal whitespace runs to single space,
    # remove a trailing newline if any. Keeps the file deterministic.
    normalized = " ".join(label.strip().split())
    target.write_text(normalized, encoding="utf-8")
    return target


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Write a real descriptive label to <Project>/.paperwik/label.txt, "
            "replacing any TODO marker placeholder. Refuses empty / TODO / "
            "too-short / too-long labels."
        ),
    )
    parser.add_argument(
        "--project",
        required=True,
        help="Project name (folder name under Vault/Projects/).",
    )
    parser.add_argument(
        "--label",
        required=True,
        help=(
            "One-sentence descriptive label of the project's topical focus. "
            f"Required, {MIN_LABEL_CHARS}-{MAX_LABEL_CHARS} chars, must "
            f"NOT start with '{TODO_LABEL_PREFIX}'."
        ),
    )
    args = parser.parse_args(argv[1:])

    target = populate_label(args.project, args.label)
    print(json.dumps(
        {
            "project": args.project,
            "label_path": str(target),
            "label_length": target.stat().st_size,
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
