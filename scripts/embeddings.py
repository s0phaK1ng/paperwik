# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     "fastembed>=0.4.0",
# ]
# ///
#
# Python is pinned to 3.12.x because one of fastembed's transitive
# dependencies (py-rust-stemmers) lacks pre-built Windows wheels for
# Python 3.13+. Without a wheel, uv falls back to a Rust source build
# that requires MSVC's link.exe, which on machines with Git-for-Windows
# on PATH gets shadowed by GNU link and fails ("link: extra operand").
# 3.12 wheels exist, so no source build happens and the shadow issue
# becomes moot. Relax this when py-rust-stemmers ships 3.13 wheels.
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

import os
import struct
import threading
from typing import Iterable

# Lazy import of fastembed — only load on first real call so scaffolder doesn't pay the cost
_model = None
_model_lock = threading.Lock()
MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
EMBED_DIM = 768
THREADS = 4

# v0.6.1: cap fastembed's per-call batch size to keep ONNXRuntime allocations
# under the ~1 GB ceiling that 4 GB Windows Sandbox VMs hit. Default of 4 was
# chosen empirically — the v0.6.0 sandbox confirmed batch_size=2 worked
# without OOM (model.embed allocated <500 MB); 4 doubles throughput while
# staying safely under the 1.115 GB allocation that crashed the sandbox at
# fastembed's default batch.
#
# Power users on big-RAM machines (16 GB+) can override via the env var:
#     PAPERWIK_EMBED_BATCH_SIZE=32 uv run index_source.py ...
# Higher values trade memory for throughput — typical embed time per chunk
# is ~10-20 ms after warmup, so the speedup matters mainly for big ingests
# (1000+ chunks). For dad's friend/family workload (1-50 chunks per source),
# the default of 4 is plenty fast.
SAFE_DEFAULT_BATCH_SIZE = 4
_BATCH_SIZE_ENV_VAR = "PAPERWIK_EMBED_BATCH_SIZE"


def _resolve_batch_size(explicit: int | None = None) -> int:
    """Resolve the effective batch size: explicit arg > env var > safe default."""
    if explicit is not None:
        return max(1, int(explicit))
    raw = os.environ.get(_BATCH_SIZE_ENV_VAR)
    if raw:
        try:
            n = int(raw)
            if n >= 1:
                return n
        except ValueError:
            pass  # fall through to safe default if env var is malformed
    return SAFE_DEFAULT_BATCH_SIZE


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


def embed_batch(
    texts: Iterable[str],
    batch_size: int | None = None,
) -> list[list[float]]:
    """Embed many documents at once. Much faster than calling embed_doc per item.

    Args:
        texts: iterable of document chunks to embed.
        batch_size: per-fastembed-call batch size. If None (default), resolves
            from `PAPERWIK_EMBED_BATCH_SIZE` env var if set, else falls back
            to `SAFE_DEFAULT_BATCH_SIZE` (4 — safe for 4 GB Windows Sandbox).

    Returns:
        list of embedding vectors (each a list[float] of length EMBED_DIM).

    v0.6.1 background:
        v0.6.0's first-sandbox ingest (Grokipedia LLM page, 38 chunks) hit an
        ONNXRuntime allocation failure ("Failed to allocate memory for
        requested buffer of size 1115419904") because fastembed's default
        batch size triggers a ~1 GB MatMul scratch buffer that overruns
        4 GB Windows Sandbox memory headroom. Capping batch_size at 4 in
        this wrapper prevents that crash without measurably slowing typical
        small ingests.
    """
    model = _get_model()
    bs = _resolve_batch_size(batch_size)
    return [v.tolist() for v in model.embed(list(texts), batch_size=bs)]


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
