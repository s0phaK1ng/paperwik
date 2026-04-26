# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     "fastembed>=0.4.0",
#     "anthropic>=0.40.0",
#     "onnxruntime>=1.16.3",
#     "tokenizers>=0.15.0",
#     "numpy>=1.26.0",
#     "huggingface-hub>=0.20.0",
# ]
# ///
#
# Python pinned to 3.12.x for wheel compatibility. See embeddings.py
# for the detailed reason (py-rust-stemmers / MSVC-link shadow).
#
# v0.6.0 added the bottom four deps for the ZSC routing branch (classify.py).
# The router itself doesn't import classify directly — it imports lazily
# inside _zsc_classify() — but `uv run` resolves the entry-script PEP-723
# header only, never transitive imports. So when ingest invokes
# `uv run project_router.py ...`, every classify dep MUST live here.
# anthropic stays for the optional naming fallback (still pre-v0.6 behavior).
"""
project_router.py — Hybrid ZSC-first / cosine-fallback router for Paperwik.

On every new source or major topic shift:
    1. Embed the content via fastembed (nomic-embed-text-v1.5).
    2. v0.6+: if zsc_enabled AND >=2 projects exist with descriptive labels,
       run zero-shot classification (multi-label) against per-project labels
       at Vault/Projects/<Project>/.paperwik/label.txt. If top probability
       >= zsc_routing_threshold AND margin over second >= zsc_routing_margin,
       FILE into top-match project. Else fall through.
    3. Compare embedding against cached project centroids.
    4. If max similarity < 0.55 → create a new project with an auto-generated
       name.
    5. Else → file into the closest match, no question asked.
    6. When user overrides (moves content between folders), update centroids.

Start condition: if zero projects exist, ALWAYS create the first project for
the first content ingested — no comparison needed.

Ported concept: CoWork's multi-tenant project scoping pattern. Implementation
is greenfield since CoWork uses PostgreSQL and doesn't need auto-routing.

v0.6.0 design notes:
    * route_content() signature is unchanged. The ZSC branch is purely
      additive — disabled callers see identical pre-v0.6 behavior.
    * The optional Anthropic-SDK name-generation fallback at
      generate_project_name() STAYS — paperwik is dad-on-Claude-Pro, but
      ANTHROPIC_API_KEY is allowed (and recommended) for higher-quality
      project names.
    * ZSC is an OPTIONAL routing accelerant; cosine remains the safety net.
      If classify.py crashes (corrupted INT8 cache, bad ONNX session, etc.)
      we silently fall through to cosine — never block ingest on ZSC errors.
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

# v0.5.x cosine-band defaults. Used as fallback when retrieval_config.json
# is missing or unparseable.
AUTO_SPLIT_BELOW = 0.55
FILE_INTO_CLOSEST_ABOVE = 0.55   # one threshold — no ambiguous middle band

# v0.6.0 ZSC routing defaults. Loaded from retrieval_config.json's nested
# project_router block at runtime via _load_zsc_config(); these constants
# are the fallback when the config file is absent or corrupted.
ZSC_ENABLED_DEFAULT = True
ZSC_ROUTING_THRESHOLD_DEFAULT = 0.70  # top match must clear this to win
ZSC_ROUTING_MARGIN_DEFAULT = 0.15     # top must beat 2nd by >= this margin


# --------------------------------------------------------------------------- #
#  retrieval_config.json loading (v0.6.0)
# --------------------------------------------------------------------------- #

def _retrieval_config_path() -> Path:
    """Resolve the per-vault retrieval_config.json path.

    Paperwik installs ship the canonical config at
    ~/Paperwik/.claude/retrieval_config.json. Older installs may have it at
    ~/Paperwik/Vault/.claude/retrieval_config.json (legacy template
    location); we check both. The first hit wins.
    """
    user_profile = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    paperwik_root = user_profile / "Paperwik"
    candidates = [
        paperwik_root / ".claude" / "retrieval_config.json",
        paperwik_root / "Vault" / ".claude" / "retrieval_config.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    # Return the canonical path even if it doesn't exist; caller will fall back.
    return candidates[0]


def _load_zsc_config() -> dict[str, Any]:
    """Read retrieval_config.json and return ZSC routing config.

    Returns a dict with keys:
        zsc_enabled            (bool)
        zsc_routing_threshold  (float)
        zsc_routing_margin     (float)

    On any parse error or missing file, returns the hardcoded defaults so
    the router never crashes on bad config.
    """
    path = _retrieval_config_path()
    if not path.exists():
        return {
            "zsc_enabled": ZSC_ENABLED_DEFAULT,
            "zsc_routing_threshold": ZSC_ROUTING_THRESHOLD_DEFAULT,
            "zsc_routing_margin": ZSC_ROUTING_MARGIN_DEFAULT,
        }
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        router_block = (cfg.get("project_router") or {}) if isinstance(cfg, dict) else {}
        return {
            "zsc_enabled": bool(router_block.get("zsc_enabled", ZSC_ENABLED_DEFAULT)),
            "zsc_routing_threshold": float(
                router_block.get("zsc_routing_threshold", ZSC_ROUTING_THRESHOLD_DEFAULT)
            ),
            "zsc_routing_margin": float(
                router_block.get("zsc_routing_margin", ZSC_ROUTING_MARGIN_DEFAULT)
            ),
        }
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        # Corrupt config -> silently fall back to defaults. Router must NEVER
        # crash on user-edited retrieval_config.json.
        return {
            "zsc_enabled": ZSC_ENABLED_DEFAULT,
            "zsc_routing_threshold": ZSC_ROUTING_THRESHOLD_DEFAULT,
            "zsc_routing_margin": ZSC_ROUTING_MARGIN_DEFAULT,
        }


# --------------------------------------------------------------------------- #
#  ZSC routing helpers (v0.6.0)
# --------------------------------------------------------------------------- #

def _project_label_path(project_name: str) -> Path:
    """Resolve the per-project descriptive-label path."""
    user_profile = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    return (
        user_profile / "Paperwik" / "Vault" / "Projects"
        / project_name / ".paperwik" / "label.txt"
    )


def _read_project_label(project_name: str) -> str | None:
    """Return the descriptive label for a project, or None if missing/empty.

    A non-empty label is REQUIRED for the project to participate in ZSC
    routing. Projects without label.txt fall through to cosine.
    """
    p = _project_label_path(project_name)
    if not p.exists():
        return None
    try:
        text = p.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def _zsc_classify(
    content: str,
    projects_with_labels: list[tuple[dict[str, Any], str]],
    threshold: float,
    margin: float,
) -> dict[str, Any] | None:
    """Run ZSC against per-project labels; return top match if gate passes.

    Args:
        content: source text (already truncated by caller).
        projects_with_labels: list of (project_dict, label_string) pairs.
        threshold: minimum top-match probability to win.
        margin: minimum gap between top and 2nd-best probability.

    Returns:
        The winning project dict if both gates pass, else None.

    Failure modes:
        * Any exception from classify.py -> return None (caller falls back
          to cosine). Router must never block ingest on ZSC errors.
        * Fewer than 2 labeled projects -> return None (margin gate is
          ill-defined with one candidate).
    """
    if len(projects_with_labels) < 2:
        return None

    try:
        # Lazy import: classify.py is heavy (onnxruntime, ~150 MB INT8 model
        # download on first call). Don't pay that cost when ZSC is disabled.
        from classify import classify as zsc_classify_fn  # type: ignore
    except ImportError:
        return None

    labels = [label for (_, label) in projects_with_labels]
    try:
        ranked = zsc_classify_fn(
            text=content,
            labels=labels,
            multi_label=True,  # independent per-label entailment scores
        )
    except Exception:
        # Corrupted ONNX, network error during first download, etc.
        # Cosine fallback is always available.
        return None

    if not ranked or len(ranked) < 2:
        return None

    top_label, top_prob = ranked[0]
    _, second_prob = ranked[1]

    if top_prob < threshold:
        return None
    if (top_prob - second_prob) < margin:
        return None

    # Map winning label back to its project.
    for proj, label in projects_with_labels:
        if label == top_label:
            return proj
    return None


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

    v0.6.0 hybrid routing:
      1. ZSC-first (if zsc_enabled AND >=2 projects have descriptive labels):
         multi-label entailment vs. per-project labels. If top >= threshold
         AND (top - 2nd) >= margin, return the top match (no centroid update —
         ZSC matches don't tell us anything about embedding-space drift).
      2. Cosine fallback (always): existing v0.5.x behavior. New project if
         max similarity < AUTO_SPLIT_BELOW; else file into closest + blend.

    Returns {"project_name": str, "project_id": int, "is_new": bool,
             "max_similarity": float, "routed_via": str}.

    The "routed_via" key is new in v0.6.0:
        "zsc"    -- the ZSC branch fired and won
        "cosine" -- fell through to cosine (either ZSC disabled, no labels,
                    gate failed, or ZSC errored out)
        "first"  -- first-ever project, no routing happened
    """
    if content_embedding is None:
        content_embedding = embed_doc(content)

    projects = get_all_projects(conn)

    if not projects:
        # First-ever project: create it, no comparison
        name = generate_project_name(content, api_key=api_key)
        pid = _create_project(conn, name, content_embedding)
        return {
            "project_name": name,
            "project_id": pid,
            "is_new": True,
            "max_similarity": 0.0,
            "routed_via": "first",
        }

    # ----- ZSC branch (v0.6.0) ----------------------------------------------
    zsc_cfg = _load_zsc_config()
    if zsc_cfg["zsc_enabled"]:
        labeled = []
        for p in projects:
            label = _read_project_label(p["name"])
            if label:
                labeled.append((p, label))
        if len(labeled) >= 2:
            zsc_match = _zsc_classify(
                content=content,
                projects_with_labels=labeled,
                threshold=zsc_cfg["zsc_routing_threshold"],
                margin=zsc_cfg["zsc_routing_margin"],
            )
            if zsc_match is not None:
                # ZSC won. Update activity but NOT centroid — embedding-space
                # learning still requires an embedding-space match signal.
                _touch_activity(conn, zsc_match["id"])
                # Compute the cosine for transparency in the return value.
                if zsc_match.get("centroid"):
                    sim = cosine(content_embedding, zsc_match["centroid"])
                else:
                    sim = 0.0
                return {
                    "project_name": zsc_match["name"],
                    "project_id": zsc_match["id"],
                    "is_new": False,
                    "max_similarity": float(sim),
                    "routed_via": "zsc",
                }
        # else: <2 labeled projects, fall through silently to cosine.

    # ----- Cosine fallback (pre-v0.6 behavior, unchanged) -------------------
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
        return {
            "project_name": name,
            "project_id": pid,
            "is_new": True,
            "max_similarity": 0.0,
            "routed_via": "cosine",
        }

    scored.sort(key=lambda x: x[0], reverse=True)
    top_sim, top_proj = scored[0]

    if top_sim < AUTO_SPLIT_BELOW:
        # Create a new project
        name = generate_project_name(content, api_key=api_key)
        pid = _create_project(conn, name, content_embedding)
        return {
            "project_name": name,
            "project_id": pid,
            "is_new": True,
            "max_similarity": top_sim,
            "routed_via": "cosine",
        }

    # File into closest match. Blend the content embedding into the centroid so it learns.
    _update_centroid_blend(conn, top_proj["id"], top_proj["centroid"], content_embedding)
    _touch_activity(conn, top_proj["id"])
    return {
        "project_name": top_proj["name"],
        "project_id": top_proj["id"],
        "is_new": False,
        "max_similarity": top_sim,
        "routed_via": "cosine",
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

    # v0.6.0: create the per-project ZSC metadata folder + empty label.txt
    # placeholder. The paperwik agent fills this in on first ingest with a
    # one-sentence descriptive expansion (which the ZSC router reads on
    # subsequent ingests). We CREATE the file here even if empty so the
    # agent has a stable file path to write to without worrying about
    # parent-folder creation later.
    paperwik_meta = folder / ".paperwik"
    paperwik_meta.mkdir(parents=True, exist_ok=True)
    label_file = paperwik_meta / "label.txt"
    if not label_file.exists():
        # Empty file — agent's responsibility to populate at first-ingest
        # time. ZSC routing skips projects whose label.txt is empty (see
        # _read_project_label), so an unfilled placeholder simply means
        # this project doesn't participate in ZSC until the agent labels it.
        label_file.write_text("", encoding="utf-8")

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
