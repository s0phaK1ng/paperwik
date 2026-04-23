# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "sqlite-vec>=0.1.0",
#     "spacy>=3.7.0",
# ]
# ///
"""
search.py — Hybrid retrieval orchestrator for Paperwik.

Components (all toggleable via retrieval_config.json):
    1. Query decomposition   (spaCy — splits compound queries into sub-queries)
    2. Vector search         (sqlite-vec MATCH against chunks.embedding)
    3. BM25 keyword search   (SQLite FTS5 over chunks_fts)
    4. RRF fusion            (Reciprocal Rank Fusion of vector + BM25 results)
    5. Graph search          (entity-hit expansion via graph.query_graph)
    6. Cross-encoder rerank  (FlashRank)
    7. Adaptive skip         (skip rerank when top result is already confident)

Entry point:
    search(query, limit=10, project=None, config=None) -> list[dict]

Ported algorithmic logic from CoWork's framework/search.py (PostgreSQL/pgvector);
SQL dialect adapted to SQLite. Interface preserved so skills can port cleanly.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
from pathlib import Path
from typing import Any

# Local imports
try:
    from embeddings import embed_query, to_blob, from_blob
    from reranker import rerank, should_skip
    from graph import query_graph
except ImportError:
    raise


# --------------------------------------------------------------------------- #
#  Config
# --------------------------------------------------------------------------- #

DEFAULT_CONFIG = {
    "vector_search": True,
    "bm25_search": True,
    "rrf_fusion": True,
    "query_decomposition": True,
    "reranker": True,
    "graph_search": True,
    "adaptive_skip": True,
    "rrf_weights": {"bm25": 0.6, "vector": 0.4},
    "rrf_k": 60,
}


def _load_config() -> dict[str, Any]:
    """Load retrieval_config.json from the vault's .claude/ dir, falling back to defaults."""
    user_profile = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    cfg_path = user_profile / "Paperwik" / ".claude" / "retrieval_config.json"
    if not cfg_path.exists():
        return dict(DEFAULT_CONFIG)
    try:
        user_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        merged = dict(DEFAULT_CONFIG)
        for k, v in user_cfg.items():
            if k.startswith("$"):  # skip comment fields
                continue
            merged[k] = v
        return merged
    except Exception:
        return dict(DEFAULT_CONFIG)


# --------------------------------------------------------------------------- #
#  sqlite-vec loader (cached)
# --------------------------------------------------------------------------- #

_vec_loader_lock = threading.Lock()


def _open_db(db_path: Path) -> sqlite3.Connection:
    """Open knowledge.db with sqlite-vec extension loaded."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    with _vec_loader_lock:
        try:
            conn.enable_load_extension(True)
            import sqlite_vec  # type: ignore

            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
        except Exception:
            # sqlite-vec may not be available in all environments (unit tests, etc.)
            # Vector search will degrade gracefully (returns empty).
            pass
    return conn


# --------------------------------------------------------------------------- #
#  spaCy (lazy, shared)
# --------------------------------------------------------------------------- #

_nlp = None
_nlp_lock = threading.Lock()


def _get_nlp():
    global _nlp
    if _nlp is not None:
        return _nlp
    with _nlp_lock:
        if _nlp is not None:
            return _nlp
        try:
            import spacy  # type: ignore

            _nlp = spacy.load("en_core_web_sm")
        except Exception:
            _nlp = None
    return _nlp


# --------------------------------------------------------------------------- #
#  Query decomposition
# --------------------------------------------------------------------------- #

def _decompose_query(query: str) -> list[str]:
    """Split a compound query into sub-queries using spaCy sentence boundaries and conjunctions.

    "What does Sinclair say about NAD+ and how does it affect longevity?" →
    ["What does Sinclair say about NAD+?", "how does it affect longevity?"]
    """
    nlp = _get_nlp()
    if nlp is None:
        return [query]

    doc = nlp(query)
    sents = [s.text.strip() for s in doc.sents if s.text.strip()]
    if len(sents) > 1:
        return sents

    # Also split on 'and' / 'or' + coordinating conjunctions when sentence split didn't catch it
    # Simple heuristic: if there's exactly one sentence but > 15 tokens, look for cc tokens
    if len(doc) >= 15:
        pieces = []
        current = []
        for tok in doc:
            if tok.dep_ == "cc" and tok.lower_ in {"and", "or", "but"}:
                if current:
                    pieces.append(" ".join(t.text for t in current).strip())
                    current = []
                continue
            current.append(tok)
        if current:
            pieces.append(" ".join(t.text for t in current).strip())
        if len(pieces) > 1 and all(len(p.split()) >= 3 for p in pieces):
            return pieces

    return [query]


def _should_use_graph(query: str) -> bool:
    """Heuristic: use graph search if the query mentions a probable named entity.

    Triggers: spaCy-tagged PROPN tokens, capitalized multiword sequences, or explicit
    entity-scope phrases like "who is / what does X say / papers by X".
    """
    nlp = _get_nlp()
    if nlp is None:
        # Defensive fallback: capitalized words present and query is short
        caps = [w for w in query.split() if w and w[0].isupper()]
        return len(caps) >= 1

    doc = nlp(query)
    # Any PROPN or labeled NER entity → yes
    if any(tok.pos_ == "PROPN" for tok in doc):
        return True
    if doc.ents:
        return True
    return False


# --------------------------------------------------------------------------- #
#  Primitive searches
# --------------------------------------------------------------------------- #

def _vector_search(
    conn: sqlite3.Connection,
    query_embedding: list[float],
    project: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Top-N chunks by cosine similarity via sqlite-vec."""
    try:
        qblob = to_blob(query_embedding)
    except Exception:
        return []

    try:
        if project:
            rows = conn.execute(
                """SELECT c.id, c.project, c.content, c.source_id,
                          vec_distance_cosine(c.embedding, ?) AS distance
                   FROM chunks c
                   WHERE c.project = ?
                     AND c.embedding IS NOT NULL
                   ORDER BY distance ASC
                   LIMIT ?""",
                (qblob, project, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT c.id, c.project, c.content, c.source_id,
                          vec_distance_cosine(c.embedding, ?) AS distance
                   FROM chunks c
                   WHERE c.embedding IS NOT NULL
                   ORDER BY distance ASC
                   LIMIT ?""",
                (qblob, limit),
            ).fetchall()
    except sqlite3.OperationalError:
        # sqlite-vec not loaded or table empty — fall back silently
        return []

    return [
        {
            "id": r["id"],
            "project": r["project"],
            "content": r["content"],
            "source_id": r["source_id"],
            "vector_score": 1.0 - float(r["distance"]),  # convert distance → similarity
        }
        for r in rows
    ]


def _bm25_search(
    conn: sqlite3.Connection,
    query: str,
    project: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Top-N chunks by BM25 keyword match via FTS5.

    FTS5 'rank' column returns negative BM25 (smaller = better match). We negate
    to make it a similarity-style score (larger = better).
    """
    # Sanitize query for FTS5 — escape double-quotes, wrap multi-word in quotes
    # We accept the user's natural-language query; FTS5's porter tokenizer handles stopwords.
    safe_q = query.replace('"', '""')
    fts_query = f'"{safe_q}"'

    try:
        if project:
            rows = conn.execute(
                """SELECT c.id, c.project, c.content, c.source_id, fts.rank AS rank
                   FROM chunks_fts fts
                   JOIN chunks c ON c.id = fts.rowid
                   WHERE chunks_fts MATCH ?
                     AND c.project = ?
                   ORDER BY rank
                   LIMIT ?""",
                (fts_query, project, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT c.id, c.project, c.content, c.source_id, fts.rank AS rank
                   FROM chunks_fts fts
                   JOIN chunks c ON c.id = fts.rowid
                   WHERE chunks_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (fts_query, limit),
            ).fetchall()
    except sqlite3.OperationalError:
        # FTS query syntax errors on empty/special queries
        return []

    return [
        {
            "id": r["id"],
            "project": r["project"],
            "content": r["content"],
            "source_id": r["source_id"],
            "bm25_score": -float(r["rank"]),  # FTS5 rank is negative; flip sign
        }
        for r in rows
    ]


def _graph_search_helper(
    conn: sqlite3.Connection,
    query: str,
    project: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """For each named entity in the query, return chunks associated with that entity."""
    nlp = _get_nlp()
    entity_names: set[str] = set()

    if nlp is not None:
        doc = nlp(query)
        for ent in doc.ents:
            entity_names.add(ent.text.strip())
        for tok in doc:
            if tok.pos_ == "PROPN":
                entity_names.add(tok.text.strip())
    else:
        # Fallback: any capitalized token of length ≥ 3
        entity_names.update(w for w in query.split() if len(w) >= 3 and w[0].isupper())

    if not entity_names:
        return []

    hits: dict[int, dict[str, Any]] = {}
    per_entity_limit = max(5, limit // max(1, len(entity_names)))
    for name in entity_names:
        for row in query_graph(conn, name, project=project, limit=per_entity_limit):
            cid = row["id"]
            if cid not in hits:
                hits[cid] = {
                    "id": cid,
                    "project": row["project"],
                    "content": row["content"],
                    "source_id": None,
                    "graph_score": 1.0,
                    "graph_entities": [row.get("entity_name")],
                }
            else:
                hits[cid]["graph_score"] += 1.0
                hits[cid]["graph_entities"].append(row.get("entity_name"))

    return list(hits.values())


# --------------------------------------------------------------------------- #
#  RRF fusion
# --------------------------------------------------------------------------- #

def _rrf_fusion(
    ranked_lists: list[list[dict[str, Any]]],
    weights: list[float],
    k: int = 60,
) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion over multiple ranked lists.

    rrf_score(d) = sum_i weight_i * 1 / (k + rank_i(d))

    Input lists must already be sorted best-to-worst. Docs are keyed by 'id'.
    Weights list must match ranked_lists length.
    """
    if len(ranked_lists) != len(weights):
        raise ValueError("ranked_lists and weights must be same length")

    scores: dict[int, float] = {}
    metadata: dict[int, dict[str, Any]] = {}

    for lst, weight in zip(ranked_lists, weights):
        for rank, doc in enumerate(lst, start=1):
            doc_id = doc["id"]
            contribution = weight / (k + rank)
            scores[doc_id] = scores.get(doc_id, 0.0) + contribution
            if doc_id not in metadata:
                metadata[doc_id] = dict(doc)
            else:
                # Merge any extra keys (e.g. graph_entities) from additional lists
                for key, val in doc.items():
                    if key not in metadata[doc_id]:
                        metadata[doc_id][key] = val

    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    results = []
    for doc_id, score in ordered:
        out = dict(metadata[doc_id])
        out["rrf_score"] = score
        results.append(out)
    return results


# --------------------------------------------------------------------------- #
#  Top-level search
# --------------------------------------------------------------------------- #

def search(
    query: str,
    limit: int = 10,
    project: str | None = None,
    config: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Run the hybrid retrieval pipeline.

    Returns a list of chunk dicts ordered by final relevance, each with:
      id, project, content, source_id, and whatever scores the pipeline emitted
      (vector_score, bm25_score, graph_score, rrf_score, rerank_score).
    """
    cfg = config or _load_config()

    if db_path is None:
        user_profile = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
        db_path = user_profile / "Paperwik" / "knowledge.db"

    if not db_path.exists():
        return []

    # Overfetch factor — we'll fuse then rerank, so gather more candidates than final limit
    candidate_limit = max(40, limit * 4)

    conn = _open_db(db_path)
    try:
        # 1. Query decomposition — run the pipeline for each sub-query and merge
        sub_queries = _decompose_query(query) if cfg.get("query_decomposition") else [query]

        all_candidates_per_subquery: list[list[dict[str, Any]]] = []
        for sub_q in sub_queries:
            ranked_lists = []
            weights = []

            if cfg.get("vector_search"):
                qemb = embed_query(sub_q)
                vec = _vector_search(conn, qemb, project, candidate_limit)
                if vec:
                    ranked_lists.append(vec)
                    weights.append(cfg["rrf_weights"].get("vector", 0.4))

            if cfg.get("bm25_search"):
                bm25 = _bm25_search(conn, sub_q, project, candidate_limit)
                if bm25:
                    ranked_lists.append(bm25)
                    weights.append(cfg["rrf_weights"].get("bm25", 0.6))

            if cfg.get("graph_search") and _should_use_graph(sub_q):
                gs = _graph_search_helper(conn, sub_q, project, candidate_limit // 2)
                if gs:
                    # Graph hits are strong signal — give them a substantial RRF weight
                    ranked_lists.append(gs)
                    weights.append(0.35)

            if not ranked_lists:
                continue

            if cfg.get("rrf_fusion"):
                fused = _rrf_fusion(ranked_lists, weights, k=cfg.get("rrf_k", 60))
            else:
                # No fusion — use whichever list ranked first
                fused = ranked_lists[0]

            all_candidates_per_subquery.append(fused[:candidate_limit])

        if not all_candidates_per_subquery:
            return []

        # 2. Merge sub-query results (each sub-query gets an equal voice)
        if len(all_candidates_per_subquery) == 1:
            merged = all_candidates_per_subquery[0]
        else:
            merged = _rrf_fusion(
                all_candidates_per_subquery,
                [1.0] * len(all_candidates_per_subquery),
                k=cfg.get("rrf_k", 60),
            )

        # 3. Rerank (optional + adaptive skip)
        do_rerank = cfg.get("reranker", True)
        if do_rerank and cfg.get("adaptive_skip"):
            top_score = merged[0].get("rrf_score", 0.0) if merged else 0.0
            # Normalize rrf_score roughly — RRF scores are unbounded but small; a high-confidence
            # top hit typically scores >0.03 with these weights. We adapt the threshold here.
            if top_score >= 0.03 and len(merged) <= 3:
                do_rerank = False

        if do_rerank and len(merged) > 1:
            reranked = rerank(query, merged, top_k=limit)
            return reranked

        return merged[:limit]

    finally:
        conn.close()


# --------------------------------------------------------------------------- #
#  CLI — quick query tester
# --------------------------------------------------------------------------- #

def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: uv run search.py <query> [project] [limit]", file=sys.stderr)
        return 2
    query = argv[1]
    project = argv[2] if len(argv) > 2 else None
    limit = int(argv[3]) if len(argv) > 3 else 10

    results = search(query, limit=limit, project=project)
    print(json.dumps(
        [{"id": r["id"], "project": r["project"], "content": r["content"][:200]} for r in results],
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
