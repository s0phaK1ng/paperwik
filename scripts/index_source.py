# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     "fastembed>=0.4.0",
#     "anthropic>=0.40.0",
#     "spacy>=3.7.0",
# ]
# ///
#
# Python pinned to 3.12.x for wheel compatibility. See embeddings.py
# for the detailed reason (py-rust-stemmers / MSVC-link shadow).
#
# spacy is here because we import graph.py which uses spaCy NER as its
# fallback entity-extraction path when ANTHROPIC_API_KEY is unset (the
# default state for Claude Pro/Max OAuth users). Without spacy listed
# here, `uv run index_source.py` would create an env without spacy and
# the fallback would silently return empty.
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
    from embeddings import embed_batch, to_blob, mean_vector
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
    # happen upstream (the paperwik-ingest skill converts before calling us).
    return source_path.read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- #
#  Chunking
# --------------------------------------------------------------------------- #

TARGET_CHUNK_CHARS = 1000
MIN_CHUNK_CHARS = 100           # drop pieces smaller than this (headers-only, etc.)
LARGE_PARA_THRESHOLD = TARGET_CHUNK_CHARS * 2

# v0.6.3: HARD upper bound on any single chunk. Beyond this size, the
# downstream embedder (fastembed -> ONNX MatMul kernel) tries to allocate
# multi-GB scratch buffers per call, which crashes on low-RAM machines
# even at batch_size=1. The PG article in the v0.6.2 sandbox had a single
# 18 KB paragraph with no sentence boundaries the previous splitter could
# find, producing an 18 KB chunk that demanded a 6 GB ONNX allocation and
# blew up. We post-process every chunk after the paragraph/sentence
# splitters and force-split anything that's still too large on whitespace
# / line boundaries. Slightly worse semantic boundaries, but bounded
# memory.
MAX_CHUNK_CHARS = 2000


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


def _force_cap_chunk(chunk: str, max_chars: int) -> list[str]:
    """v0.6.3: hard-split a chunk that's still oversized after the
    paragraph + sentence splitters. Tries to break on (in order of
    preference): newline, period+space, comma+space, then bare whitespace.

    Bounded: every output piece is <= max_chars.
    """
    if len(chunk) <= max_chars:
        return [chunk]

    pieces: list[str] = []
    i = 0
    n = len(chunk)
    while i < n:
        end = min(i + max_chars, n)
        if end < n:
            # Search backward from end for a good break point in the
            # second half of [i, end). Prefer newlines, then sentence
            # ends, then commas, then any whitespace. If nothing useful,
            # accept a hard split at max_chars.
            for sep in ("\n", ". ", "! ", "? ", ", ", " "):
                k = chunk.rfind(sep, i + max_chars // 2, end)
                if k != -1:
                    end = k + len(sep)
                    break
        piece = chunk[i:end].strip()
        if piece:
            pieces.append(piece)
        i = end
    return pieces


def chunk_text(text: str, target_size: int = TARGET_CHUNK_CHARS) -> list[str]:
    """Paragraph-aware chunker.

    * Splits text on double-newline (paragraph) boundaries.
    * Greedily groups paragraphs up to ~target_size chars each.
    * If a single paragraph is larger than 2*target_size, splits it further
      on sentence boundaries.
    * v0.6.3: post-process every chunk against MAX_CHUNK_CHARS as a hard
      cap; any oversized chunk is force-split on whitespace boundaries.
      Defends against pathological paragraphs (no sentence punctuation,
      single quote blocks, etc.).
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

    # v0.6.3: enforce MAX_CHUNK_CHARS as a hard cap on every chunk.
    capped: list[str] = []
    for ch in chunks:
        capped.extend(_force_cap_chunk(ch, MAX_CHUNK_CHARS))

    # Drop tiny chunks (title-only lines, isolated short headers, etc.)
    return [c for c in capped if len(c) >= MIN_CHUNK_CHARS]


# --------------------------------------------------------------------------- #
#  DB helpers
# --------------------------------------------------------------------------- #

def _get_db_path() -> Path:
    user_profile = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    return user_profile / "Paperwik" / "knowledge.db"


def _to_vault_relative(source_path: Path) -> str:
    """Return file_path relative to the vault root for the sources table."""
    user_profile = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    vault_root = user_profile / "Paperwik" / "Vault"
    try:
        rel = source_path.resolve().relative_to(vault_root.resolve())
        return str(rel).replace("\\", "/")
    except ValueError:
        # Source is outside the vault (e.g. still in Inbox on a different drive) —
        # fall back to the absolute path so we at least record something useful.
        return str(source_path)


def _slugify(name: str) -> str:
    """Mirror of project_router._slugify; kept local to avoid an import."""
    slug = re.sub(r"\s+", "-", name.lower().strip())
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    return slug[:50] or "project"


def _ensure_project_row(
    conn: sqlite3.Connection,
    project: str,
    chunk_embeddings: list[list[float]],
    ts: str,
) -> None:
    """v0.6.3: ensure the projects table has a row for `project`.

    If a row already exists (matched by name), do nothing. Otherwise
    insert one with a centroid computed from the chunk embeddings being
    indexed (mean vector). One source's worth of chunks is a noisy
    centroid signal but is far better than the project being absent
    from routing decisions entirely.

    Self-healing for the v0.6.0/v0.6.1/v0.6.2 failure mode where the
    agent ran the indexer without first running the router. With this
    fix, programmatic / fix-up / drag-and-drop ingest flows can never
    leave a project orphaned from the routing system.
    """
    from embeddings import to_blob, mean_vector  # type: ignore

    existing = conn.execute(
        "SELECT id FROM projects WHERE name = ?",
        (project,),
    ).fetchone()
    if existing is not None:
        return  # Row already present; nothing to do.

    # Compute centroid from chunks. mean_vector raises on empty list, but
    # callers always have >=1 chunk by this point (RuntimeError is raised
    # earlier if chunks is empty).
    centroid = mean_vector(chunk_embeddings)
    centroid_blob = to_blob(centroid)

    # Slug must be unique; on collision append a numeric suffix until free.
    base_slug = _slugify(project)
    slug = base_slug
    suffix = 1
    while conn.execute("SELECT 1 FROM projects WHERE slug = ?", (slug,)).fetchone():
        suffix += 1
        slug = f"{base_slug}-{suffix}"

    conn.execute(
        """INSERT INTO projects
               (name, slug, centroid_embedding, source_count, last_activity_ts, archived, created_ts)
           VALUES (?, ?, ?, 0, ?, 0, ?)""",
        (project, slug, centroid_blob, ts, ts),
    )
    conn.commit()
    log(
        f"Self-healed missing projects-table row for '{project}' "
        f"(slug='{slug}'); centroid computed from {len(chunk_embeddings)} chunk(s)."
    )


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
#  v0.6.4 hard-gate validation: refuse to index if the agent skipped
#  Step 4 (label generation) or Step 5 (write_summary with source_type).
# --------------------------------------------------------------------------- #

class IngestPreflightError(RuntimeError):
    """Raised when v0.6.4 pre-flight checks fail. The agent has work
    to do (write a real label, regenerate the summary with source_type)
    before re-running the indexer."""


def _label_path_for(project: str) -> Path:
    user_profile = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    return (
        user_profile / "Paperwik" / "Vault" / "Projects"
        / project / ".paperwik" / "label.txt"
    )


def _project_dir_for(project: str) -> Path:
    user_profile = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    return user_profile / "Paperwik" / "Vault" / "Projects" / project


def _check_label_populated(project: str) -> None:
    """v0.6.4: refuse to index if the project's label.txt is empty or
    still has the TODO marker. Forces the agent to populate it (via
    populate_label.py) before indexing.

    Skipped when label.txt is genuinely missing entirely -- that means
    this is an old v0.5.x project and we shouldn't penalize the user
    for the legacy state.
    """
    p = _label_path_for(project)
    if not p.exists():
        # Legacy project (pre-v0.6.0). Don't block; the install.ps1 c10
        # backfill will create a TODO marker on next install.
        return
    text = p.read_text(encoding="utf-8").strip()
    if not text:
        raise IngestPreflightError(
            f"Project '{project}' has an EMPTY .paperwik/label.txt. "
            f"Populate it with a real one-sentence descriptive label "
            f"before indexing. Use:\n"
            f"  uv run \"$PAPERWIK_PLUGIN/scripts/populate_label.py\" "
            f"--project \"{project}\" --label \"<one descriptive sentence>\""
        )
    if text.startswith("TODO:"):
        raise IngestPreflightError(
            f"Project '{project}' .paperwik/label.txt still has the TODO "
            f"marker. Replace it with a real one-sentence descriptive "
            f"label before indexing. Use:\n"
            f"  uv run \"$PAPERWIK_PLUGIN/scripts/populate_label.py\" "
            f"--project \"{project}\" --label \"<one descriptive sentence>\""
        )


def _check_summary_has_source_type(project: str, source_path: Path) -> None:
    """v0.6.4: refuse to index if no summary page in the project folder
    has a `source_type:` field in YAML frontmatter referencing this
    source. Forces the agent to use write_summary.py (which always
    emits source_type) instead of hand-writing summary YAML.

    Heuristic: scan all top-level *.md files in the project directory.
    If at least one has a YAML `source_type:` field, the gate passes.
    We don't require the matching summary to reference THIS specific
    source -- the indexer doesn't know the agent's mapping between
    source path and summary slug. The looser check is "has the agent
    written *some* summary with source_type for this project?" which
    is the right gate for typical 1-source-per-ingest flows.
    """
    project_dir = _project_dir_for(project)
    if not project_dir.exists():
        # Project folder doesn't exist yet -- this shouldn't happen since
        # _ensure_project_row ran before this. Defensive only.
        return

    md_files = [
        p for p in project_dir.glob("*.md")
        if p.is_file()
    ]
    if not md_files:
        raise IngestPreflightError(
            f"Project '{project}' has no summary markdown files yet. "
            f"Write the summary page first (use write_summary.py with a "
            f"JSON spec containing source_type), then re-run the indexer."
        )

    for md in md_files:
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Accept either inside a frontmatter block (---...---) or at
        # the top of the file. Loose regex; strict YAML parsing is overkill
        # for a one-line check.
        if re.search(r"(?m)^source_type:\s*\S+", text[:2000]):
            return  # at least one summary has source_type -- pass

    raise IngestPreflightError(
        f"Project '{project}' has summary file(s) but none contain a "
        f"`source_type:` YAML field. Regenerate the summary using "
        f"write_summary.py (which always emits source_type), or add the "
        f"field to the existing YAML frontmatter:\n"
        f"  uv run \"$PAPERWIK_PLUGIN/scripts/write_summary.py\" "
        f"--json /path/to/spec.json"
    )


def _run_preflight_checks(project: str, source_path: Path) -> None:
    """v0.6.4: run all pre-flight checks. Raises IngestPreflightError on
    any failure. Caller should let the exception propagate (it has a
    rich error message instructing the agent how to fix)."""
    _check_label_populated(project)
    _check_summary_has_source_type(project, source_path)


# --------------------------------------------------------------------------- #
#  Main indexing pipeline
# --------------------------------------------------------------------------- #

def index_source(
    source_path: Path,
    project: str,
    title: str | None = None,
    skip_preflight: bool = False,
) -> dict:
    """Chunk, embed, and index a single source. Returns a stats dict.

    Raises on hard failures (file missing, DB unreachable, embedding failure).
    Entity extraction failures are logged but do not raise.

    v0.6.4: pre-flight checks now refuse to run if the project's label.txt
    is unpopulated (empty / TODO marker) or if no summary page in the
    project has a `source_type:` YAML field. Skip with skip_preflight=True
    only for migration / fix-up scenarios where you know the project's
    state is intentionally incomplete.
    """
    if not source_path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    if not skip_preflight:
        # v0.6.4: hard gate. Will raise IngestPreflightError with a clear
        # message if the agent skipped Step 4 or Step 5.
        _run_preflight_checks(project, source_path)

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
        # v0.6.3: ensure a projects-table row exists for `project` BEFORE we
        # insert sources/chunks. The router (project_router._create_project)
        # is normally responsible for inserting projects rows, but if the
        # agent ever runs the indexer without first running the router
        # (programmatic ingest, manual fix-up, drag-and-drop UI without
        # the routing step, etc.), the projects table will silently lack
        # the row -- which makes future routing decisions IGNORE this
        # project as a candidate, even though its content is fully
        # indexed in chunks/sources.
        #
        # Self-healing fix: INSERT OR IGNORE a projects row, computing
        # the centroid from this source's chunk embeddings (mean of all
        # chunks). One source is a noisy centroid signal but it's still
        # vastly better than the project being absent.
        _ensure_project_row(conn, project, embeddings, ts)

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
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help=(
            "v0.6.4: skip the source_type-in-YAML and label.txt-populated "
            "pre-flight checks. Use ONLY for migration / fix-up scenarios "
            "where the project's state is intentionally incomplete. Normal "
            "ingest flows MUST NOT use this flag -- the pre-flight is the "
            "architectural enforcement that fixed the v0.6.0/v0.6.1/v0.6.2 "
            "agent-skip failure mode."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    try:
        stats = index_source(
            Path(args.source),
            args.project,
            title=args.title,
            skip_preflight=args.skip_preflight,
        )
    except FileNotFoundError as exc:
        log(f"FATAL: {exc}", level="ERROR")
        print(json.dumps({"error": str(exc), "kind": "not_found"}), file=sys.stdout)
        return 2
    except IngestPreflightError as exc:
        # v0.6.4: pre-flight failures are an EXPECTED outcome, not a crash.
        # Emit the clear, actionable error message to stderr (so the agent
        # sees it inline) and return a distinguishable exit code.
        log(f"PREFLIGHT FAILED: {exc}", level="ERROR")
        print(json.dumps({"error": str(exc), "kind": "preflight_failed"}, indent=2), file=sys.stdout)
        return 3
    except Exception as exc:
        log(f"FATAL: {exc}", level="ERROR")
        print(json.dumps({"error": str(exc), "kind": "index_failed"}), file=sys.stdout)
        return 1

    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
