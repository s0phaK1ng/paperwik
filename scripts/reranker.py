# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "flashrank>=0.2.9",
# ]
# ///
"""
reranker.py — FlashRank cross-encoder wrapper.

Uses ms-marco-MiniLM-L-12-v2 (~150 MB, CPU-only, ~120ms for 50 pairs). Reranks
candidates returned by hybrid search against the original query.

Ported from CoWork's framework/reranker.py. Preserves the adaptive-skip logic
(skip the rerank pass if the top hybrid result scores very high, since rerank
cost outweighs expected improvement).

Usage:
    from reranker import rerank, should_skip

    candidates = [{"id": 1, "text": "chunk 1"}, {"id": 2, "text": "chunk 2"}, ...]
    if should_skip(top_hybrid_score):
        ranked = candidates[:top_k]
    else:
        ranked = rerank("query text", candidates, top_k=10)
"""

from __future__ import annotations

import math
import threading
from typing import Any

_ranker = None
_ranker_lock = threading.Lock()
MODEL_NAME = "ms-marco-MiniLM-L-12-v2"

# Adaptive skip: if the top hybrid result has a score above this threshold,
# rerank is unlikely to reorder the top results meaningfully. CoWork measured
# 0.92 as the practical threshold for their corpus; tune against dad's eval set.
ADAPTIVE_SKIP_THRESHOLD = 0.92


def _get_ranker():
    """Lazy-load the cross-encoder. Safe under concurrent calls."""
    global _ranker
    if _ranker is not None:
        return _ranker
    with _ranker_lock:
        if _ranker is not None:
            return _ranker
        from flashrank import Ranker  # type: ignore

        _ranker = Ranker(model_name=MODEL_NAME)
    return _ranker


def _sigmoid(x: float) -> float:
    """Standard logistic sigmoid — maps raw cross-encoder scores to (0, 1)."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def should_skip(top_score: float, threshold: float = ADAPTIVE_SKIP_THRESHOLD) -> bool:
    """Return True if the rerank pass should be skipped.

    Call this on the top-ranked hybrid result's normalized score. If it's above
    threshold, the top of the pack is already confident and rerank won't help.
    """
    return top_score >= threshold


def rerank(query: str, candidates: list[dict[str, Any]], top_k: int = 10) -> list[dict[str, Any]]:
    """Rerank a list of candidate dicts against the query.

    Each candidate must have keys 'id' and 'text'. Returns the same dicts with an
    added 'rerank_score' key (sigmoid-normalized), sorted descending, truncated to top_k.
    """
    if not candidates:
        return []

    ranker = _get_ranker()

    # FlashRank expects a list of {"id": ..., "text": ...} dicts
    passages = [{"id": str(c["id"]), "text": c["text"]} for c in candidates]
    raw = ranker.rerank(query=query, passages=passages)

    # raw is a list of dicts with 'id', 'text', 'score' (raw logit)
    # map id -> score
    score_by_id = {r["id"]: _sigmoid(float(r["score"])) for r in raw}

    # Attach scores to original candidates, preserving any extra fields they had
    enriched = []
    for c in candidates:
        score = score_by_id.get(str(c["id"]), 0.0)
        out = dict(c)
        out["rerank_score"] = score
        enriched.append(out)

    enriched.sort(key=lambda c: c["rerank_score"], reverse=True)
    return enriched[:top_k]
