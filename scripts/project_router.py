# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     "fastembed>=0.4.0",
#     "anthropic>=0.40.0",
# ]
# ///
#
# Python pinned to 3.12.x for wheel compatibility. See embeddings.py
# for the detailed reason (py-rust-stemmers / MSVC-link shadow).
"""
project_router.py — Two-band embedding-similarity router for Paperwik.

On every new source or major topic shift:
    1. Embed the content via fastembed (nomic-embed-text-v1.5).
    2. Compare against cached project centroids in the projects table.
    3. If max similarity < 0.55 → create a new project with an auto-generated name.
    4. Else → file into the closest match, no question asked.
    5. When user overrides (moves content between folders), update centroids.

Start condition: if zero projects exist, ALWAYS create the first project for
the first content ingested — no comparison needed.

Ported concept: CoWork's multi-tenant project scoping pattern. Implementation
is greenfield since CoWork uses PostgreSQL and doesn't need auto-routing.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Local imports (same scripts/ directory)
try:
    from embeddings import embed_doc, to_blob, from_blob, cosine, mean_vector, EMBED_DIM
except ImportError:
    # When run via `uv run` the script's directory is on sys.path; this import should work.
    # If it doesn't, the caller needs to set PYTHONPATH.
    raise


# --------------------------------------------------------------------------- #
#  Thresholds (matches retrieval_config.json → project_router)
# --------------------------------------------------------------------------- #

AUTO_SPLIT_BELOW = 0.55
FILE_INTO_CLOSEST_ABOVE = 0.55   # one threshold — no ambiguous middle band


# --------------------------------------------------------------------------- #
#  Project naming via Claude API
# --------------------------------------------------------------------------- #

NAMING_PROMPT = """Propose a short, title-cased folder name (2–4 words) for a knowledge-base project covering the following content. The name should be a noun phrase describing the TOPIC, not a description of the content type. Return ONLY the name — no quotes, no explanation.

Examples of good names:
  - "Cognitive Health"
  - "Municipal Bonds"
  - "Family History"
  - "Omega-3 Research"

Examples of bad names:
  - "research notes" (generic)
  - "articles about cognition" (describes format, not topic)
  - "Project 1" (non-descriptive)

Content:
---
{CONTENT}
---

Folder name:"""


# Stopwords to drop when we fall back to the structural-title heuristic.
# Titles usually end with the topic ("The Unreasonable Effectiveness of
# Recurrent Neural Networks" -> topic = "Recurrent Neural Networks");
# stripping these out + taking trailing content words reliably yields a
# topical folder name without needing the Claude API.
_STOPWORDS = frozenset("""
    a an the
    and or but nor so yet
    of in on at by for with to from as about into through during after before
    is was are were be been being am
    have has had having
    do does did doing
    will would could should may might must can shall
    this that these those
    i you he she we they it
    my your his her its our their
    what which who whom when where why how
    all any some many few more most other another each every both either neither
    not no only just very too also still even
    there here
    if because though although unless until while
""".split())


def _extract_content_title(content: str) -> str | None:
    """Try to extract a topical title from the source by looking for:

      1. HTML <title>...</title>
      2. Markdown H1 (first '# Title' within the first 50 lines)
      3. YAML frontmatter 'title:' field

    Returns the raw title text or None if none of the markers are found.
    """
    # HTML <title>
    m = re.search(r"<title[^>]*>([^<]+)</title>", content, re.IGNORECASE | re.DOTALL)
    if m:
        return " ".join(m.group(1).strip().split())  # collapse internal whitespace
    # Markdown H1
    for line in content.splitlines()[:50]:
        s = line.strip()
        if s.startswith("# ") and not s.startswith("## "):
            return s[2:].strip()
    # YAML frontmatter 'title:'
    m = re.search(r"^title:\s*['\"]?([^\n'\"]+)['\"]?\s*$", content, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return None


def _name_from_title(title: str, max_words: int = 3) -> str | None:
    """Strip stopwords from a title and take the trailing content words.

    English titles typically put the topic last ("The X of Y Z Topic"),
    so after removing articles/prepositions/stopwords, the last ~3 words
    are almost always the project's actual topic.
    """
    # Tokenize while keeping hyphens/apostrophes as part of words
    words = re.findall(r"\b[\w'-]+\b", title)
    content_words = [w for w in words if w.lower() not in _STOPWORDS]
    if not content_words:
        return None
    if len(content_words) > max_words:
        content_words = content_words[-max_words:]
    # Preserve all-caps acronyms as-is; title-case everything else
    formatted = [w if w.isupper() and len(w) >= 2 else w.capitalize() for w in content_words]
    return " ".join(formatted)


def generate_project_name(content: str, api_key: str | None = None) -> str:
    """Propose a folder name for this content.

    Preference order:
      1. Claude Haiku via ANTHROPIC_API_KEY (best — topical noun phrase)
      2. Structural title extraction + stopword filter (good — works
         offline, catches ~90% of web articles/papers cleanly)
      3. Leading capitalized words from the body (weak — previous behavior,
         kept as a last resort before the timestamp default)
    """
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        try:
            from anthropic import Anthropic  # type: ignore

            client = Anthropic(api_key=api_key)
            msg = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=50,
                messages=[
                    {"role": "user", "content": NAMING_PROMPT.replace("{CONTENT}", content[:3000])}
                ],
            )
            raw = msg.content[0].text.strip() if msg.content else ""
            name = _sanitize_folder_name(raw)
            if name:
                return name
        except Exception:
            pass

    # Fallback 1: structural title + stopword filter. Turns
    # "The Unreasonable Effectiveness of Recurrent Neural Networks" ->
    # "Recurrent Neural Networks".
    title = _extract_content_title(content)
    if title:
        from_title = _name_from_title(title)
        if from_title:
            sanitized = _sanitize_folder_name(from_title)
            if sanitized:
                return sanitized

    # Fallback 2: leading capitalized words from the body, minus stopwords.
    # Better than the previous behavior, which would happily include "The"
    # and "A" at the front.
    body_words = re.findall(r"\b[A-Z][a-z]+\b", content[:500])
    body_content = [w for w in body_words if w.lower() not in _STOPWORDS]
    if len(body_content) >= 2:
        sanitized = _sanitize_folder_name(" ".join(body_content[:3]))
        if sanitized:
            return sanitized

    # Last resort: timestamped untitled project. The user is expected to
    # rename it in Obsidian; the router learns from overrides.
    return f"Untitled Project {datetime.now().strftime('%Y%m%d')}"


def _sanitize_folder_name(raw: str) -> str:
    """Strip punctuation that Windows filesystems choke on, collapse whitespace, cap length."""
    # Remove common wrapping quotes/asterisks/backticks
    cleaned = re.sub(r"^['\"`*]+|['\"`*]+$", "", raw.strip())
    # Windows-illegal chars: < > : " / \ | ? *
    cleaned = re.sub(r'[<>:"/\\|?*]', "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:60]  # reasonable cap


# --------------------------------------------------------------------------- #
#  Routing
# --------------------------------------------------------------------------- #

def get_all_projects(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return every non-archived project with its centroid (deserialized to list[float])."""
    rows = conn.execute(
        """SELECT id, name, slug, centroid_embedding, source_count, last_activity_ts
           FROM projects WHERE archived = 0"""
    ).fetchall()
    projects = []
    for r in rows:
        centroid = from_blob(r[3]) if r[3] is not None else None
        projects.append({
            "id": int(r[0]),
            "name": r[1],
            "slug": r[2],
            "centroid": centroid,
            "source_count": int(r[4] or 0),
            "last_activity_ts": r[5],
        })
    return projects


def route_content(
    conn: sqlite3.Connection,
    content: str,
    content_embedding: list[float] | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Decide which project a new piece of content belongs to.

    Returns {"project_name": str, "project_id": int, "is_new": bool, "max_similarity": float}.
    """
    if content_embedding is None:
        content_embedding = embed_doc(content)

    projects = get_all_projects(conn)

    if not projects:
        # First-ever project: create it, no comparison
        name = generate_project_name(content, api_key=api_key)
        pid = _create_project(conn, name, content_embedding)
        return {"project_name": name, "project_id": pid, "is_new": True, "max_similarity": 0.0}

    # Compare against each project's centroid
    scored = []
    for p in projects:
        if p["centroid"] is None:
            continue
        sim = cosine(content_embedding, p["centroid"])
        scored.append((sim, p))

    if not scored:
        # Defensive: all existing projects lack centroids (shouldn't happen in practice)
        name = generate_project_name(content, api_key=api_key)
        pid = _create_project(conn, name, content_embedding)
        return {"project_name": name, "project_id": pid, "is_new": True, "max_similarity": 0.0}

    scored.sort(key=lambda x: x[0], reverse=True)
    top_sim, top_proj = scored[0]

    if top_sim < AUTO_SPLIT_BELOW:
        # Create a new project
        name = generate_project_name(content, api_key=api_key)
        pid = _create_project(conn, name, content_embedding)
        return {"project_name": name, "project_id": pid, "is_new": True, "max_similarity": top_sim}

    # File into closest match. Blend the content embedding into the centroid so it learns.
    _update_centroid_blend(conn, top_proj["id"], top_proj["centroid"], content_embedding)
    _touch_activity(conn, top_proj["id"])
    return {
        "project_name": top_proj["name"],
        "project_id": top_proj["id"],
        "is_new": False,
        "max_similarity": top_sim,
    }


# --------------------------------------------------------------------------- #
#  Project CRUD
# --------------------------------------------------------------------------- #

def _slugify(name: str) -> str:
    """Convert a display name to a filesystem-safe slug."""
    slug = re.sub(r"\s+", "-", name.lower().strip())
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    return slug[:50] or "project"


def _create_project(conn: sqlite3.Connection, name: str, centroid: list[float]) -> int:
    """Insert a new project with a unique slug. Returns project id."""
    base_slug = _slugify(name)
    slug = base_slug
    suffix = 1
    while conn.execute("SELECT 1 FROM projects WHERE slug = ?", (slug,)).fetchone():
        suffix += 1
        slug = f"{base_slug}-{suffix}"

    ts = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO projects (name, slug, centroid_embedding, source_count, last_activity_ts, archived, created_ts)
           VALUES (?, ?, ?, 0, ?, 0, ?)""",
        (name, slug, to_blob(centroid), ts, ts),
    )
    conn.commit()

    # Physically create the folder inside the vault
    user_profile = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    folder = user_profile / "Paperwik" / "Vault" / "Projects" / name
    folder.mkdir(parents=True, exist_ok=True)

    return int(cur.lastrowid)


def _update_centroid_blend(
    conn: sqlite3.Connection,
    project_id: int,
    old_centroid: list[float],
    new_content_emb: list[float],
    alpha: float = 0.1,
) -> None:
    """Update a project centroid via exponential moving average.

    centroid_new = (1 - alpha) * centroid_old + alpha * new_content
    alpha=0.1 means each new source shifts the centroid by 10% — resistant to
    topic drift but not frozen.
    """
    blended = [(1 - alpha) * old_centroid[i] + alpha * new_content_emb[i] for i in range(EMBED_DIM)]
    conn.execute(
        "UPDATE projects SET centroid_embedding = ? WHERE id = ?",
        (to_blob(blended), project_id),
    )


def _touch_activity(conn: sqlite3.Connection, project_id: int) -> None:
    """Update last_activity_ts and bump source_count."""
    ts = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE projects SET last_activity_ts = ?, source_count = source_count + 1 WHERE id = ?",
        (ts, project_id),
    )
    conn.commit()


# --------------------------------------------------------------------------- #
#  User-override learning
# --------------------------------------------------------------------------- #

def record_override(
    conn: sqlite3.Connection,
    source_id: int,
    original_project: str,
    corrected_project: str,
    corrected_content_emb: list[float],
) -> None:
    """Called when the user moves content from one project to another.

    Logs the override + updates the corrected project's centroid to incorporate
    the moved content, so future similar items route to the right place.
    """
    ts = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO routing_overrides (source_id, original_project, corrected_project, override_ts)
           VALUES (?, ?, ?, ?)""",
        (source_id, original_project, corrected_project, ts),
    )

    row = conn.execute(
        "SELECT id, centroid_embedding FROM projects WHERE name = ?",
        (corrected_project,),
    ).fetchone()
    if row:
        pid = int(row[0])
        existing_centroid = from_blob(row[1]) if row[1] else corrected_content_emb
        _update_centroid_blend(conn, pid, existing_centroid, corrected_content_emb, alpha=0.2)
    conn.commit()


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #

# nomic-embed-text-v1.5 has an ~8k token / ~32k char context window, but the
# onnxruntime kernels for its MLP layers allocate intermediate buffers that
# scale with input size and OOM on low-RAM machines (observed on 4 GB Windows
# Sandbox during Paperwik v0.1.7 testing with a 48 KB HTML source). Truncating
# router input is safe: topic routing only needs a coarse embedding, not the
# full document — the indexer embeds every chunk separately.
ROUTING_SNIPPET_CHARS = 8000


def _cmd_route(content_path: str) -> int:
    user_profile = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    db_path = user_profile / "Paperwik" / "knowledge.db"
    if not db_path.exists():
        print(f"knowledge.db not found at {db_path}", file=sys.stderr)
        return 1
    content = Path(content_path).read_text(encoding="utf-8")[:ROUTING_SNIPPET_CHARS]
    conn = sqlite3.connect(str(db_path))
    try:
        result = route_content(conn, content)
        print(json.dumps(result, indent=2))
    finally:
        conn.close()
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: uv run project_router.py <content-file>", file=sys.stderr)
        return 2
    return _cmd_route(argv[1])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
