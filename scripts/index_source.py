# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "fastembed>=0.4.0",
#     "anthropic>=0.40.0",
# ]
# ///
"""
index_source.py — Chunk, embed, and index a source document into knowledge.db.

Called by the `ingest-source` skill after the project router has picked a
target project and after the summary/entity markdown pages have been written.
This script is the "index" hand-off: it reads the raw source, chunks it,
embeds every chunk, writes the chunks/embeddings/FTS rows into knowledge.db,
then invokes graph.extract_and_store for each chunk to populate the entity
graph.

Usage:
    uv run index_source.py --source "<path>" --project "<project>" [--title "<title>"]

Output: a single JSON object on stdout describing what was indexed:

    {
      "source_id": 1,
      "chunks": 68,
      "entities_linked": 93,
      "content_hash": "abc123...",
      "source_type": "md"
    }

Exits 0 on success, non-zero on hard failure (file missing, DB error, etc.).
A zero count for entities_linked is NOT a failure — it just means entity
extraction ran but found nothing (or ANTHROPIC_API_KEY was unset and the
Claude-based extractor in graph.py returned an empty list).

Design notes
------------
* The skill (ingest-source) is responsible for ensuring the summary page and
  entity pages are already on disk before this runs. This script does NOT
  generate markdown — only database rows.
* Chunking is paragraph-aware with a ~1000-char target. Oversized paragraphs
  are split on sentence boundaries.
* FTS5 index is maintained automatically by the triggers declared in
  scaffold-vault.py — we do not write to chunks_fts directly.
* Entity extraction via graph.py degrades gracefully: if ANTHROPIC_API_KEY
  is unset, the graph tables stay empty for this source but chunks/embeddings
  still land correctly, so vector + BM25 search works.
"""

from __future__ import annotations

import argparse
import hashlib
import html.parser
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Local imports (same scripts/ directory)
try:
    from embeddings import embed_batch, to_blob
    from graph import extract_and_store
except ImportError as exc:
    print(f"FATAL: cannot import sibling modules: {exc}", file=sys.stderr)
    print("Ensure this script is run from its own directory via `uv run`.", file=sys.stderr)
    sys.exit(1)


# --------------------------------------------------------------------------- #
#  Diagnostics (mirror the convention used by scaffold-vault.py / setup-models.py)
# --------------------------------------------------------------------------- #

def _diag_log_path() -> Path:
    user_profile = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    return user_profile / "Documents" / "Paperwik-Diagnostics.log"


def log(msg: str, level: str = "INFO") -> None:
    """Timestamped stderr line + append to Paperwik-Diagnostics.log."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    line = f"[{ts}] [{level}] [index-source] {msg}"
    print(line, file=sys.stderr, flush=True)
    try:
        log_path = _diag_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass  # never break indexing over a logging failure


# --------------------------------------------------------------------------- #
#  Source text extraction
# --------------------------------------------------------------------------- #

class _HtmlStripper(html.parser.HTMLParser):
    """Minimal HTML → plain text. Skips <script>, <style>, <noscript> bodies."""

    _SKIP_TAGS = {"script", "style", "noscript", "head"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._buf: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        # Treat block-level close as a paragraph break
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}:
            self._buf.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._buf.append(data)

    def text(self) -> str:
        raw = "".join(self._buf)
        # Collapse 3+ newlines to 2 (paragraph breaks only)
        return re.sub(r"\n{3,}", "\n\n", raw).strip()


def extract_text(source_path: Path) -> str:
    """Read the source and return plain text suitable for chunking."""
    suffix = source_path.suffix.lower()
    if suffix in {".md", ".markdown", ".txt"}:
        return source_path.read_text(encoding="utf-8", errors="replace")
    if suffix in {".html", ".htm"}:
        raw = source_path.read_text(encoding="utf-8", errors="replace")
        stripper = _HtmlStripper()
        stripper.feed(raw)
        stripper.close()
        return stripper.text()
    # Default: best-effort plain read. PDF/DOCX conversion is expected to
    # happen upstream (the ingest skill converts before calling us).
    return source_path.read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- #
#  Chunking
# --------------------------------------------------------------------------- #

TARGET_CHUNK_CHARS = 1000
MIN_CHUNK_CHARS = 100           # drop pieces smaller than this (headers-only, etc.)
LARGE_PARA_THRESHOLD = TARGET_CHUNK_CHARS * 2


def _split_large_paragraph(paragraph: str, target_size: int) -> list[str]:
    """Split a single oversized paragraph on sentence-ish boundaries."""
    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    pieces: list[str] = []
    current: list[str] = []
    current_size = 0
    for sent in sentences:
        sent_size = len(sent)
        if current_size + sent_size > target_size and current:
            pieces.append(" ".join(current))
            current = [sent]
            current_size = sent_size
        else:
            current.append(sent)
            current_size += sent_size + 1
    if current:
        pieces.append(" ".join(current))
    return pieces


def chunk_text(text: str, target_size: int = TARGET_CHUNK_CHARS) -> list[str]:
    """Paragraph-aware chunker.

    * Splits text on double-newline (paragraph) boundaries.
    * Greedily groups paragraphs up to ~target_size chars each.
    * If a single paragraph is larger than 2*target_size, splits it further
      on sentence boundaries.
    * Drops trivially short pieces.
    """
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if not text:
        return []
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks: list[str] = []
    current: list[str] = []
    current_size = 0

    for para in paragraphs:
        para_size = len(para)
        if para_size > LARGE_PARA_THRESHOLD:
            # Flush anything already accumulated
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_size = 0
            # Split the oversized paragraph and append each piece as its own chunk
            chunks.extend(_split_large_paragraph(para, target_size))
            continue

        if current_size + para_size > target_size and current:
            chunks.append("\n\n".join(current))
            current = [para]
            current_size = para_size
        else:
            current.append(para)
            current_size += para_size + 2  # +2 for the paragraph break

    if current:
        chunks.append("\n\n".join(current))

    # Drop tiny chunks (title-only lines, isolated short headers, etc.)
    return [c for c in chunks if len(c) >= MIN_CHUNK_CHARS]


# --------------------------------------------------------------------------- #
#  DB helpers
# --------------------------------------------------------------------------- #

def _get_db_path() -> Path:
    user_profile = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    return user_profile / "Knowledge" / "knowledge.db"


def _to_vault_relative(source_path: Path) -> str:
    """Return file_path relative to the vault root for the sources table."""
    user_profile = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    vault_root = user_profile / "Knowledge"
    try:
        rel = source_path.resolve().relative_to(vault_root.resolve())
        return str(rel).replace("\\", "/")
    except ValueError:
        # Source is outside the vault (e.g. still in Inbox on a different drive) —
        # fall back to the absolute path so we at least record something useful.
        return str(source_path)


def _upsert_source(
    conn: sqlite3.Connection,
    project: str,
    title: str,
    file_path: str,
    source_type: str,
    content_hash: str,
    ts: str,
) -> int:
    """Insert a sources row, or return the existing id if (project, file_path) already exists."""
    row = conn.execute(
        "SELECT id FROM sources WHERE project = ? AND file_path = ?",
        (project, file_path),
    ).fetchone()
    if row:
        source_id = int(row[0])
        # Update hash + timestamp so a re-ingest reflects the latest content
        conn.execute(
            "UPDATE sources SET title = ?, source_type = ?, ingest_ts = ?, content_hash = ? WHERE id = ?",
            (title, source_type, ts, content_hash, source_id),
        )
        # Clear old chunks for this source so we re-index cleanly
        conn.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))
        return source_id

    cur = conn.execute(
        """INSERT INTO sources (project, title, file_path, source_type, ingest_ts, content_hash)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (project, title, file_path, source_type, ts, content_hash),
    )
    return int(cur.lastrowid)


# --------------------------------------------------------------------------- #
#  Main indexing pipeline
# --------------------------------------------------------------------------- #

def index_source(
    source_path: Path,
    project: str,
    title: str | None = None,
) -> dict:
    """Chunk, embed, and index a single source. Returns a stats dict.

    Raises on hard failures (file missing, DB unreachable, embedding failure).
    Entity extraction failures are logged but do not raise.
    """
    if not source_path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    log(f"Indexing source: {source_path} into project '{project}'")

    # 1. Extract plain text
    text = extract_text(source_path)
    if not text.strip():
        raise RuntimeError(f"Source produced empty text after extraction: {source_path}")

    # 2. Chunk
    chunks = chunk_text(text)
    if not chunks:
        raise RuntimeError(f"Source produced zero chunks (all below min-size threshold): {source_path}")
    log(f"Produced {len(chunks)} chunks.")

    # 3. Embed every chunk in a single batch (much faster than per-chunk)
    log("Embedding chunks...")
    embeddings = embed_batch(chunks)
    if len(embeddings) != len(chunks):
        raise RuntimeError(f"Embedder returned {len(embeddings)} vectors for {len(chunks)} chunks")

    # 4. Content hash (for dedup + change detection)
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

    # 5. Write to DB
    db_path = _get_db_path()
    if not db_path.exists():
        raise FileNotFoundError(f"knowledge.db missing — scaffolder must run first: {db_path}")

    ts = datetime.now(timezone.utc).isoformat()
    source_type = source_path.suffix.lower().lstrip(".") or "txt"
    rel_path = _to_vault_relative(source_path)
    if title is None:
        title = source_path.stem

    conn = sqlite3.connect(str(db_path))
    try:
        # sources row
        source_id = _upsert_source(conn, project, title, rel_path, source_type, content_hash, ts)
        conn.commit()

        # chunks rows (FTS5 is maintained by triggers)
        chunk_ids: list[int] = []
        for idx, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            cur = conn.execute(
                """INSERT INTO chunks
                       (project, source_id, chunk_index, content, token_count, embedding, created_ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    project,
                    source_id,
                    idx,
                    chunk,
                    # Token-count approximation (whitespace-split). Good enough for
                    # heuristics; we don't use it for scoring.
                    len(chunk.split()),
                    to_blob(emb),
                    ts,
                ),
            )
            chunk_ids.append(int(cur.lastrowid))
        conn.commit()
        log(f"Inserted {len(chunk_ids)} chunks + embeddings.")

        # Entity graph (degrades gracefully if ANTHROPIC_API_KEY is unset)
        total_entity_links = 0
        for chunk_id, chunk_body in zip(chunk_ids, chunks):
            try:
                linked = extract_and_store(conn, chunk_id, chunk_body, project)
                total_entity_links += len(linked)
            except Exception as exc:
                log(f"Entity extraction failed for chunk {chunk_id}: {exc}", level="WARN")
        conn.commit()
        log(f"Linked {total_entity_links} chunk↔entity pairs.")

        return {
            "source_id": source_id,
            "chunks": len(chunk_ids),
            "entities_linked": total_entity_links,
            "content_hash": content_hash[:12],
            "source_type": source_type,
            "file_path": rel_path,
            "title": title,
            "project": project,
        }
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #

def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="index_source.py",
        description="Chunk, embed, and index a source into Paperwik's knowledge.db.",
    )
    parser.add_argument("--source", required=True, help="Path to the source file on disk.")
    parser.add_argument("--project", required=True, help="Target project (folder name in vault).")
    parser.add_argument("--title", default=None, help="Optional human-readable title; defaults to filename stem.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    try:
        stats = index_source(Path(args.source), args.project, title=args.title)
    except FileNotFoundError as exc:
        log(f"FATAL: {exc}", level="ERROR")
        print(json.dumps({"error": str(exc), "kind": "not_found"}), file=sys.stdout)
        return 2
    except Exception as exc:
        log(f"FATAL: {exc}", level="ERROR")
        print(json.dumps({"error": str(exc), "kind": "index_failed"}), file=sys.stdout)
        return 1

    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
