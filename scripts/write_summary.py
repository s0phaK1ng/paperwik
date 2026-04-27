# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = []
# ///
"""
write_summary.py -- v0.6.4 architectural enforcement of summary-page YAML.

This script is the ONLY blessed way to create a paperwik summary page.
The agent assembles structured data (title, abstract, key_points,
source_type, ...) into a JSON spec, calls this script, and the script
generates the markdown file with a properly-populated YAML frontmatter
that includes `source_type:`.

Why this exists: through v0.6.0/v0.6.1/v0.6.2 sandbox testing, the agent
*reliably* skipped writing `source_type:` into summary YAML even when:
  - SKILL.md said so prominently (v0.6.0)
  - SKILL.md said so with MANDATORY framing + pre-flight checklist +
    self-check gate (v0.6.1)
  - the value was returned in the router's JSON output the agent already
    captured (v0.6.2)

D12's lesson confirmed: anything that's "agent reads tool output and
writes a file" is skippable. Anything done by a tool is not. So in
v0.6.4 we move summary-page generation INTO a tool. The agent still
gathers the facts; the tool generates the file.

Usage:
    uv run write_summary.py --json /tmp/summary_spec.json

JSON spec schema (REQUIRED fields marked):

    {
      "project": "PostgreSQL",                    # REQUIRED
      "source_type": "article",                   # REQUIRED, one of the 6
      "title": "PostgreSQL Overview",             # REQUIRED
      "body": "## Section 1\\n\\n...",            # REQUIRED, markdown body
      "source": "https://...",                    # optional
      "source_title": "PostgreSQL — Grokipedia",  # optional
      "tags": ["postgresql", "database"],         # optional
      "slug": "Grokipedia Overview",              # optional, default = title
      "created": "2026-04-27"                     # optional, default = today
    }

Output: writes the file to
    %USERPROFILE%/Paperwik/Vault/Projects/<project>/<slug>.md
and prints a JSON status line: {"path": "...", "source_type": "..."}.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

# Source types must match source_classifier.py's taxonomy. Validated at
# write time so we never ship a summary with a malformed source_type.
ALLOWED_SOURCE_TYPES = {
    "academic",
    "article",
    "newsletter",
    "social",
    "journal",
    "reference",
}

# YAML field order is fixed for diff-friendliness (so the agent can't
# accidentally permute fields between runs and create churn in git).
FRONTMATTER_FIELDS_ORDER = [
    "created",
    "source",
    "source_title",
    "source_type",
    "tags",
]


def _slugify_for_filename(name: str) -> str:
    """Filesystem-safe slug. Allows spaces (Obsidian-friendly) but strips
    Windows-illegal characters and trims length."""
    cleaned = name.strip()
    # Windows-illegal: < > : " / \ | ? *
    for ch in '<>:"/\\|?*':
        cleaned = cleaned.replace(ch, "")
    cleaned = " ".join(cleaned.split())  # collapse whitespace runs
    return cleaned[:80] or "Summary"


def _format_yaml_value(key: str, value) -> str:
    """Emit one YAML scalar/list line. Conservative quoting."""
    if value is None:
        return f"{key}:"
    if isinstance(value, list):
        # YAML inline list, comma-separated, no quotes (tags are plain words)
        rendered = ", ".join(str(v) for v in value)
        return f"{key}: [{rendered}]"
    s = str(value)
    # Quote if the value contains characters that confuse YAML parsers
    needs_quote = any(c in s for c in (":", "#", "{", "}", "[", "]", ",", "&", "*", "!", "|", ">", "'", '"', "`", "@"))
    if needs_quote:
        # Escape any embedded double quotes and wrap
        escaped = s.replace('"', '\\"')
        return f'{key}: "{escaped}"'
    return f"{key}: {s}"


def _build_frontmatter(spec: dict) -> str:
    """Generate the YAML frontmatter block. Always includes source_type."""
    fields = {
        "created": spec.get("created") or date.today().isoformat(),
        "source": spec.get("source") or "",
        "source_title": spec.get("source_title") or spec["title"],
        "source_type": spec["source_type"],
        "tags": spec.get("tags") or [],
    }
    lines = ["---"]
    for key in FRONTMATTER_FIELDS_ORDER:
        if key == "source" and not fields[key]:
            continue  # skip empty source field rather than emit blank
        lines.append(_format_yaml_value(key, fields[key]))
    lines.append("---")
    return "\n".join(lines)


def _validate_spec(spec: dict) -> None:
    """Hard-fail on missing required fields or invalid source_type."""
    required = ["project", "source_type", "title", "body"]
    for k in required:
        if k not in spec or spec[k] in (None, "", []):
            print(
                f"[write_summary] ERROR: missing or empty required field '{k}' in JSON spec",
                file=sys.stderr,
            )
            sys.exit(2)
    if spec["source_type"] not in ALLOWED_SOURCE_TYPES:
        print(
            f"[write_summary] ERROR: source_type must be one of "
            f"{sorted(ALLOWED_SOURCE_TYPES)}; got '{spec['source_type']}'",
            file=sys.stderr,
        )
        sys.exit(2)


def write_summary(spec: dict) -> Path:
    """Generate the summary-page markdown and write it to disk.

    Returns the absolute Path of the file written.
    """
    _validate_spec(spec)

    project = spec["project"]
    title = spec["title"]
    body = spec["body"]
    slug = spec.get("slug") or title

    user_profile = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    project_dir = user_profile / "Paperwik" / "Vault" / "Projects" / project
    project_dir.mkdir(parents=True, exist_ok=True)

    target = project_dir / f"{_slugify_for_filename(slug)}.md"

    frontmatter = _build_frontmatter(spec)
    # Body may already include a top-level # heading; if not, prepend the title.
    body_stripped = body.lstrip()
    if not body_stripped.startswith("# "):
        body_block = f"\n\n# {title}\n\n{body_stripped}"
    else:
        body_block = f"\n\n{body_stripped}"

    content = frontmatter + body_block
    target.write_text(content, encoding="utf-8")
    return target


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a paperwik summary page from a JSON spec. The "
            "generated file always has source_type in YAML frontmatter."
        ),
    )
    parser.add_argument(
        "--json",
        required=True,
        help="Path to JSON spec file (see header for schema).",
    )
    args = parser.parse_args(argv[1:])

    spec_path = Path(args.json)
    if not spec_path.exists():
        print(f"[write_summary] ERROR: spec file not found: {spec_path}", file=sys.stderr)
        return 2

    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[write_summary] ERROR: spec file is not valid JSON: {exc}", file=sys.stderr)
        return 2

    target = write_summary(spec)
    print(json.dumps(
        {
            "path": str(target),
            "source_type": spec["source_type"],
            "project": spec["project"],
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
