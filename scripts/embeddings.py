# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "fastembed>=0.4.0",
# ]
# ///
"""
embeddings.py — Fastembed wrapper for Paperwik.

Lazy-loads the nomic-embed-text-v1.5 ONNX model (~400 MB, CPU-only, 10ms/embed
after warmup). Provides query/doc embedding + SQLite BLOB serialization.

Ported from CoWork's framework/embeddings.py (PostgreSQL/pgvector version);
this is the SQLite/sqlite-vec adaptation.

Usage:
    from embeddings import embed_query, embed_doc, embed_batch, to_blob, from_blob

    qvec = embed_query("what do I know about ketosis?")
    dvecs = embed_batch(["chunk 1 text", "chunk 2 text"])
    # Store in SQLite:
    cursor.execute("INSERT INTO chunks(embedding, ...) VALUES (?, ...)", (to_blob(qvec), ...))
"""

from __future__ import annotations

import struct
import threading
from typing import Iterable

# Lazy import of fastembed — only load on first real call so scaffolder doesn't pay the cost
_model = None
_model_lock = threading.Lock()
MODEL_NAME = "nomic-embed-text-v1.5"
EMBED_DIM = 768
THREADS = 4


def _get_model():
    """Return the shared TextEmbedding instance, loading it if needed."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:  # double-check after acquiring lock
            return _model
        from fastembed import TextEmbedding  # type: ignore

        _model = TextEmbedding(model_name=MODEL_NAME, threads=THREADS)
    return _model


# --------------------------------------------------------------------------- #
#  Embedding primitives
# --------------------------------------------------------------------------- #

def embed_query(text: str) -> list[float]:
    """Embed a single query string. Returns a Python list[float] of length EMBED_DIM.

    Note: nomic-embed-text distinguishes query vs. doc prefixes internally via
    fastembed's passage/query API. We use the default (passage) mode for docs
    and rely on fastembed's built-in query encoding.
    """
    model = _get_model()
    vecs = list(model.query_embed([text]))
    if not vecs:
        raise RuntimeError(f"Embedding failed for query: {text!r}")
    return vecs[0].tolist()


def embed_doc(text: str) -> list[float]:
    """Embed a single document chunk. Returns list[float] of length EMBED_DIM."""
    model = _get_model()
    vecs = list(model.embed([text]))
    if not vecs:
        raise RuntimeError(f"Embedding failed for doc: {text!r}")
    return vecs[0].tolist()


def embed_batch(texts: Iterable[str]) -> list[list[float]]:
    """Embed many documents at once. Much faster than calling embed_doc per item."""
    model = _get_model()
    return [v.tolist() for v in model.embed(list(texts))]


# --------------------------------------------------------------------------- #
#  SQLite BLOB serialization (float32 little-endian, matches sqlite-vec format)
# --------------------------------------------------------------------------- #

def to_blob(vec: list[float]) -> bytes:
    """Serialize a Python list of floats to raw float32 bytes for SQLite BLOB storage.

    sqlite-vec expects little-endian float32. struct '<f' = little-endian float32.
    """
    if len(vec) != EMBED_DIM:
        raise ValueError(f"Expected {EMBED_DIM}-dim vector, got {len(vec)}")
    return struct.pack(f"<{EMBED_DIM}f", *vec)


def from_blob(blob: bytes) -> list[float]:
    """Deserialize bytes from SQLite BLOB back to list[float]."""
    expected = EMBED_DIM * 4
    if len(blob) != expected:
        raise ValueError(f"Expected {expected} bytes ({EMBED_DIM}*4), got {len(blob)}")
    return list(struct.unpack(f"<{EMBED_DIM}f", blob))


# --------------------------------------------------------------------------- #
#  Similarity (cosine) — used by project_router, and as a fallback when sqlite-vec
#  isn't loaded (e.g. in unit tests)
# --------------------------------------------------------------------------- #

def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two same-length vectors."""
    if len(a) != len(b):
        raise ValueError("Vector lengths differ")
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(y * y for y in b) ** 0.5
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


def mean_vector(vectors: list[list[float]]) -> list[float]:
    """Compute the elementwise mean of a list of vectors (used for project centroids)."""
    if not vectors:
        raise ValueError("Cannot mean an empty list of vectors")
    dim = len(vectors[0])
    out = [0.0] * dim
    for v in vectors:
        if len(v) != dim:
            raise ValueError("Inconsistent vector dims in mean_vector")
        for i in range(dim):
            out[i] += v[i]
    n = float(len(vectors))
    return [x / n for x in out]
