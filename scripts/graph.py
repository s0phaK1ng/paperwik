# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     "anthropic>=0.40.0",
#     "spacy>=3.7.0",
# ]
# ///
#
# Python pinned to 3.12.x for wheel compatibility. See embeddings.py
# for the detailed reason (py-rust-stemmers / MSVC-link shadow).
"""
graph.py — Entity extraction + storage for Paperwik's knowledge graph.

Called at ingest time by ingest-source. Takes a chunk of text, extracts
entities (PERSON / CONCEPT / PAPER / ORGANIZATION), and stores them in
knowledge.db's graph_entities, entity_relationships, and chunk_entities
tables.

Extraction backend is dual-path:

1. If ANTHROPIC_API_KEY is set → call Claude Haiku for high-quality
   extraction including typed relationships between entities.
2. Otherwise → use spaCy NER (local, no network, no API key) for PERSON,
   ORG, and WORK_OF_ART labels. No relationships in this path — spaCy's
   NER doesn't emit them — but chunk↔entity links still populate, so
   entity-graph search still works.

Target users are on Claude Pro/Max OAuth, which does NOT expose an API
key. The spaCy fallback is the default path for the target deployment;
the Claude path is the enhancement for users who happen to have an
ANTHROPIC_API_KEY set.

Usage:
    from graph import extract_and_store

    entity_ids = extract_and_store(conn, chunk_id, chunk_text, project)
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from typing import Any


# --------------------------------------------------------------------------- #
#  Shared types
# --------------------------------------------------------------------------- #

_VALID_ENTITY_TYPES = {"PERSON", "CONCEPT", "PAPER", "ORGANIZATION"}


# --------------------------------------------------------------------------- #
#  Path 1: Claude API (high-quality, requires ANTHROPIC_API_KEY)
# --------------------------------------------------------------------------- #

EXTRACTION_PROMPT = """You are an entity extraction system for a personal knowledge base.

Read the following text and extract entities that would be worth tracking across multiple sources. Specifically:

- PERSON: named researchers, authors, experts, or individuals discussed substantively (not passing mentions)
- CONCEPT: specific named ideas, frameworks, theories, methodologies, mechanisms, or technical terms (not generic common nouns)
- PAPER: specific named papers, studies, articles, books, or reports cited
- ORGANIZATION: specific named institutions, companies, labs, universities, or agencies

For each entity, also extract any notable relationships to other entities mentioned in the text.

Return STRICT JSON with this shape (no markdown fences, no commentary):

{
  "entities": [
    {"name": "...", "type": "PERSON|CONCEPT|PAPER|ORGANIZATION", "description": "one-sentence context"}
  ],
  "relationships": [
    {"source": "entity name", "target": "entity name", "relationship": "verb phrase, 1-4 words"}
  ]
}

Text to analyze:

---
{TEXT}
---

Return only the JSON object."""


def _extract_via_claude(chunk_text: str, api_key: str) -> dict[str, Any] | None:
    """Claude Haiku entity extraction. Returns the parsed JSON dict, or None
    on any failure so the caller can fall back to spaCy."""
    try:
        from anthropic import Anthropic  # type: ignore
    except ImportError:
        return None

    prompt = EXTRACTION_PROMPT.replace("{TEXT}", chunk_text[:8000])

    try:
        client = Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text if msg.content else ""
        # Strip any accidental markdown fences
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw.rsplit("\n", 1)[0]
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        data.setdefault("entities", [])
        data.setdefault("relationships", [])
        return data
    except Exception:
        return None


# --------------------------------------------------------------------------- #
#  Path 2: spaCy NER (local, no API key required)
# --------------------------------------------------------------------------- #

# Map spaCy NER labels to our entity types. We intentionally skip GPE/LOC
# (geographic places), DATE, MONEY, CARDINAL, etc. — they are rarely
# useful as persistent knowledge-base nodes. WORK_OF_ART covers paper/book
# titles reasonably well in practice.
_SPACY_LABEL_MAP = {
    "PERSON": "PERSON",
    "ORG": "ORGANIZATION",
    "WORK_OF_ART": "PAPER",
}

_spacy_nlp = None
_spacy_lock = threading.Lock()


def _get_spacy():
    """Lazy-load en_core_web_sm.

    setup-models.py downloads en_core_web_sm into ITS uv-managed venv
    (one specific cached venv hash). graph.py's caller (typically
    index_source.py) runs in a DIFFERENT uv venv with different deps and
    therefore a different cache hash, so the model package exists in
    setup-models's venv but is missing here. Each venv needs its own
    copy.

    On first call in any new venv: spacy.load() raises OSError, we
    download the model via spaCy's CLI (one-time ~50MB / ~10s), then
    retry the load. Subsequent calls in the same venv hit the cached
    package and load instantly.

    Raises on persistent failure so the caller's try/except in
    _extract_via_spacy returns the empty graph (degrade gracefully
    instead of breaking ingest)."""
    global _spacy_nlp
    if _spacy_nlp is not None:
        return _spacy_nlp
    with _spacy_lock:
        if _spacy_nlp is not None:
            return _spacy_nlp
        import spacy  # type: ignore
        try:
            _spacy_nlp = spacy.load("en_core_web_sm")
        except OSError:
            # Model not in this venv. Download it via spaCy's CLI so the
            # version matches the installed spacy package automatically.
            print(
                "[graph.py] en_core_web_sm not found in this venv; downloading "
                "via `python -m spacy download en_core_web_sm` (one-time, ~10s)...",
                file=sys.stderr,
                flush=True,
            )
            import subprocess
            subprocess.check_call(
                [sys.executable, "-m", "spacy", "download", "en_core_web_sm"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=180,
            )
            _spacy_nlp = spacy.load("en_core_web_sm")
            print(
                "[graph.py] en_core_web_sm download + load complete.",
                file=sys.stderr,
                flush=True,
            )
    return _spacy_nlp


def _extract_via_spacy(chunk_text: str) -> dict[str, Any]:
    """Local NER via spaCy. PERSON/ORG/WORK_OF_ART only. No relationships —
    spaCy's default pipeline doesn't emit them and adding a dependency
    parse just for subject-verb-object tuples would triple per-chunk cost.

    The entity-graph search path in search.py only needs (entity, chunk)
    pairs to be populated; typed edges are a nice-to-have, not required
    for the retrieval flow."""
    try:
        nlp = _get_spacy()
    except Exception as exc:
        print(
            f"[graph.py] spaCy load failed ({exc.__class__.__name__}: {exc}); "
            "returning empty graph for this chunk.",
            file=sys.stderr,
            flush=True,
        )
        return {"entities": [], "relationships": []}

    # Same per-call text cap as the Claude path so budgets match
    doc = nlp(chunk_text[:8000])

    entities: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for ent in doc.ents:
        if ent.label_ not in _SPACY_LABEL_MAP:
            continue
        name = ent.text.strip()
        # Filter junk: too short, too long, all-numeric
        if len(name) < 2 or len(name) > 60:
            continue
        if name.replace(" ", "").replace("-", "").isdigit():
            continue
        key = (name.lower(), ent.label_)
        if key in seen:
            continue
        seen.add(key)
        entities.append({
            "name": name,
            "type": _SPACY_LABEL_MAP[ent.label_],
            "description": "",  # no description without an LLM; pages are
                                 # still usable with just the name + type
        })

    return {"entities": entities, "relationships": []}


# --------------------------------------------------------------------------- #
#  Public API — orchestrates Claude → spaCy → empty
# --------------------------------------------------------------------------- #

def extract_entities(chunk_text: str, api_key: str | None = None) -> dict[str, Any]:
    """Extract entities + relationships from a chunk. Never raises.

    Tries Claude Haiku first if ANTHROPIC_API_KEY is available (or passed
    in). If that path fails or is unavailable, falls back to spaCy NER.
    If spaCy also fails (e.g. en_core_web_sm not installed), returns an
    empty graph — ingest continues, but the knowledge graph stays sparse
    for this chunk.
    """
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        result = _extract_via_claude(chunk_text, api_key)
        if result is not None:
            return result
    return _extract_via_spacy(chunk_text)


# --------------------------------------------------------------------------- #
#  Storage
# --------------------------------------------------------------------------- #

def _normalize(name: str) -> str:
    """Canonical form for entity lookup (lowercased, whitespace-collapsed)."""
    return " ".join(name.lower().split())


def store_entity(
    conn: sqlite3.Connection,
    project: str,
    name: str,
    entity_type: str,
    description: str = "",
    embedding_blob: bytes | None = None,
) -> int:
    """Upsert an entity. Returns its row id.

    Entities are unique per (project, type, normalized_name). If the entity already
    exists, its description is NOT overwritten (first ingest wins — subsequent
    ingests enrich the graph with new relationships, not new descriptions).
    """
    normalized = _normalize(name)
    ts = datetime.now(timezone.utc).isoformat()

    row = conn.execute(
        "SELECT id FROM graph_entities WHERE project=? AND type=? AND normalized_name=?",
        (project, entity_type, normalized),
    ).fetchone()
    if row:
        return int(row[0])

    cursor = conn.execute(
        """INSERT INTO graph_entities
               (project, name, type, normalized_name, description, embedding, created_ts)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (project, name, entity_type, normalized, description, embedding_blob, ts),
    )
    return int(cursor.lastrowid)


def store_relationship(
    conn: sqlite3.Connection,
    source_id: int,
    target_id: int,
    relationship: str,
    weight: float = 1.0,
) -> None:
    """Insert or strengthen a relationship between two entities."""
    row = conn.execute(
        """SELECT id, weight FROM entity_relationships
           WHERE source_id=? AND target_id=? AND relationship=?""",
        (source_id, target_id, relationship),
    ).fetchone()
    if row:
        new_weight = float(row[1]) + weight
        conn.execute(
            "UPDATE entity_relationships SET weight=? WHERE id=?",
            (new_weight, int(row[0])),
        )
    else:
        conn.execute(
            """INSERT INTO entity_relationships(source_id, target_id, relationship, weight)
               VALUES (?, ?, ?, ?)""",
            (source_id, target_id, relationship, weight),
        )


def link_chunk_to_entity(conn: sqlite3.Connection, chunk_id: int, entity_id: int) -> None:
    """Link a chunk to an entity (many-to-many)."""
    conn.execute(
        "INSERT OR IGNORE INTO chunk_entities(chunk_id, entity_id) VALUES (?, ?)",
        (chunk_id, entity_id),
    )


# --------------------------------------------------------------------------- #
#  Orchestrator
# --------------------------------------------------------------------------- #

def extract_and_store(
    conn: sqlite3.Connection,
    chunk_id: int,
    chunk_text: str,
    project: str,
    api_key: str | None = None,
) -> list[int]:
    """Extract entities from a chunk, store them, link to the chunk, build relationships.

    Returns a list of entity IDs linked to this chunk.
    """
    data = extract_entities(chunk_text, api_key=api_key)
    entity_ids_by_name: dict[str, int] = {}

    for ent in data.get("entities", []):
        name = ent.get("name", "").strip()
        etype = ent.get("type", "").strip().upper()
        if not name or etype not in {"PERSON", "CONCEPT", "PAPER", "ORGANIZATION"}:
            continue
        desc = ent.get("description", "")
        eid = store_entity(conn, project, name, etype, description=desc)
        entity_ids_by_name[_normalize(name)] = eid
        link_chunk_to_entity(conn, chunk_id, eid)

    for rel in data.get("relationships", []):
        src = _normalize(rel.get("source", ""))
        tgt = _normalize(rel.get("target", ""))
        rel_type = rel.get("relationship", "").strip()
        if src in entity_ids_by_name and tgt in entity_ids_by_name and rel_type:
            store_relationship(
                conn,
                entity_ids_by_name[src],
                entity_ids_by_name[tgt],
                rel_type,
            )

    conn.commit()
    return list(entity_ids_by_name.values())


# --------------------------------------------------------------------------- #
#  Graph query — used by search.py's _graph_search
# --------------------------------------------------------------------------- #

def query_graph(
    conn: sqlite3.Connection,
    entity_name: str,
    project: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Given an entity mention in a user query, return chunks associated with that entity.

    Used by search.py when spaCy's NER flags a likely-entity token in the query.
    """
    normalized = _normalize(entity_name)
    params: list[Any] = [normalized]
    sql = """
        SELECT c.id, c.project, c.content, e.name AS entity_name, e.type AS entity_type
        FROM graph_entities e
        JOIN chunk_entities ce ON ce.entity_id = e.id
        JOIN chunks c ON c.id = ce.chunk_id
        WHERE e.normalized_name = ?
    """
    if project:
        sql += " AND c.project = ?"
        params.append(project)
    sql += " LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [
        {"id": r[0], "project": r[1], "content": r[2], "entity_name": r[3], "entity_type": r[4]}
        for r in rows
    ]


if __name__ == "__main__":
    print("graph.py is a library module. Invoke via the ingest-source skill.", file=sys.stderr)
    sys.exit(1)
