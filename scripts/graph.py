# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "anthropic>=0.40.0",
# ]
# ///
"""
graph.py — Entity extraction + storage for Paperwik's knowledge graph.

Called at ingest time by ingest-source. Takes a chunk of text, extracts
entities via Claude API (PERSON / CONCEPT / PAPER / ORGANIZATION), and
stores them in knowledge.db's graph_entities, entity_relationships, and
chunk_entities tables.

Ported from CoWork's framework/graph.py. Gemini branch dropped for v1 —
dad is authenticated to Claude via OAuth anyway, so reusing that path is
simpler than adding a Google SDK dependency.

Usage:
    from graph import extract_and_store

    entity_ids = extract_and_store(conn, chunk_id, chunk_text, project)
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any


# --------------------------------------------------------------------------- #
#  Entity extraction via Claude API
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


def extract_entities(chunk_text: str, api_key: str | None = None) -> dict[str, Any]:
    """Call Claude API to extract entities + relationships from a chunk.

    Returns {"entities": [...], "relationships": [...]} or {"entities": [], "relationships": []} on failure.
    Never raises — entity extraction failures should not block ingest.
    """
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        # Fall back: graph stays empty. Entity graph degrades gracefully.
        return {"entities": [], "relationships": []}

    try:
        from anthropic import Anthropic  # type: ignore
    except ImportError:
        return {"entities": [], "relationships": []}

    prompt = EXTRACTION_PROMPT.replace("{TEXT}", chunk_text[:8000])  # Cap to ~8K chars per call

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
        # Sanity-check shape
        if not isinstance(data, dict):
            return {"entities": [], "relationships": []}
        data.setdefault("entities", [])
        data.setdefault("relationships", [])
        return data
    except Exception:
        return {"entities": [], "relationships": []}


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
