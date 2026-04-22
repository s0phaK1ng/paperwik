# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
r"""
scaffold-vault.py — First-run setup for Paperwik.

Runs via `uv run` from the SessionStart hook. Idempotent: skips the body if
the sentinel file %USERPROFILE%\Knowledge\.claude\.scaffolded already exists.

Responsibilities:
    1. Create the vault directory tree at %USERPROFILE%\Knowledge\ if missing
    2. Copy template files from ${CLAUDE_PLUGIN_ROOT}/templates/vault/ into place
    3. Initialize knowledge.db with the full schema (chunks, graph_entities,
       entity_relationships, chunk_entities, projects)
    4. Write the .scaffolded sentinel so subsequent launches skip this work

The scaffolder deliberately has no external Python dependencies — it uses
stdlib only so `uv run` doesn't need to resolve anything. Retrieval-stack
dependencies (fastembed, flashrank, spacy) live in the ingest-time scripts
that need them.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


# --------------------------------------------------------------------------- #
#  Paths
# --------------------------------------------------------------------------- #

def get_paths() -> dict[str, Path]:
    """Resolve the canonical Paperwik paths from env vars."""
    user_profile = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    vault_root = user_profile / "Knowledge"
    plugin_root_env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root_env:
        plugin_root = Path(plugin_root_env)
    else:
        # Fallback: assume this script lives in <plugin>/scripts/
        plugin_root = Path(__file__).resolve().parent.parent

    template_root = plugin_root / "templates" / "vault"
    documents = user_profile / "Documents"

    return {
        "user_profile": user_profile,
        "vault_root": vault_root,
        "plugin_root": plugin_root,
        "template_root": template_root,
        "documents": documents,
        "sentinel": vault_root / ".claude" / ".scaffolded",
        "knowledge_db": vault_root / "knowledge.db",
        "diag_log": documents / "Paperwik-Diagnostics.log",
    }


# --------------------------------------------------------------------------- #
#  Logging
# --------------------------------------------------------------------------- #

def log(msg: str, level: str = "INFO", diag_log: Path | None = None) -> None:
    """Write a timestamped line to the diagnostic log. Never raises."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    line = f"[{ts}] [{level}] [scaffold-vault] {msg}"
    print(line, file=sys.stderr)
    if diag_log is None:
        return
    try:
        diag_log.parent.mkdir(parents=True, exist_ok=True)
        with diag_log.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        # Don't let a logging failure break the scaffolder
        pass


# --------------------------------------------------------------------------- #
#  Vault filesystem layout
# --------------------------------------------------------------------------- #

def copy_template_tree(template_root: Path, vault_root: Path, diag: Path) -> None:
    """Copy everything under templates/vault/ into the user's vault.

    Uses shutil.copytree with dirs_exist_ok=True so re-running (if sentinel was
    manually deleted) is safe — existing user content is not clobbered.
    """
    if not template_root.exists():
        raise RuntimeError(
            f"Template directory not found at {template_root}. "
            f"Set CLAUDE_PLUGIN_ROOT env var or verify the plugin install."
        )

    log(f"Copying template tree: {template_root} -> {vault_root}", diag_log=diag)
    shutil.copytree(
        src=str(template_root),
        dst=str(vault_root),
        dirs_exist_ok=True,
    )
    log("Template tree copied successfully.", diag_log=diag)


# --------------------------------------------------------------------------- #
#  SQLite schema
# --------------------------------------------------------------------------- #

SCHEMA_SQL = """
-- Paperwik knowledge.db schema v1
-- Created by scripts/scaffold-vault.py on first run.
-- Ported from CoWork's PostgreSQL/pgvector schema; adapted for SQLite + sqlite-vec.
-- The sqlite-vec extension is loaded at retrieval time, not here.

BEGIN;

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    centroid_embedding BLOB,            -- avg embedding across this project's chunks
    source_count INTEGER DEFAULT 0,
    last_activity_ts TEXT,              -- ISO8601; used for 180-day archive policy
    archived INTEGER DEFAULT 0,
    created_ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    title TEXT,
    file_path TEXT NOT NULL,            -- relative to vault root
    source_type TEXT,                   -- pdf, md, url-clipping, etc.
    ingest_ts TEXT NOT NULL,
    content_hash TEXT,
    UNIQUE (project, file_path)
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    token_count INTEGER,
    embedding BLOB,                     -- 768-dim float32; queried via sqlite-vec MATCH
    created_ts TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE,
    UNIQUE (source_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_project ON chunks(project);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);

-- FTS5 virtual table for keyword search over chunk content
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    content='chunks',
    content_rowid='id',
    tokenize='porter'
);

-- Keep FTS in sync via triggers
CREATE TRIGGER IF NOT EXISTS chunks_fts_insert AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS chunks_fts_delete AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES ('delete', old.id, old.content);
END;
CREATE TRIGGER IF NOT EXISTS chunks_fts_update AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES ('delete', old.id, old.content);
    INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
END;

-- Entity graph (PERSON, CONCEPT, PAPER, ORGANIZATION)
CREATE TABLE IF NOT EXISTS graph_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    normalized_name TEXT,
    description TEXT,
    embedding BLOB,
    created_ts TEXT NOT NULL,
    UNIQUE (project, type, normalized_name)
);
CREATE INDEX IF NOT EXISTS idx_graph_entities_name ON graph_entities(normalized_name);
CREATE INDEX IF NOT EXISTS idx_graph_entities_project ON graph_entities(project);

CREATE TABLE IF NOT EXISTS entity_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    relationship TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    FOREIGN KEY (source_id) REFERENCES graph_entities(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES graph_entities(id) ON DELETE CASCADE,
    UNIQUE (source_id, target_id, relationship)
);

CREATE TABLE IF NOT EXISTS chunk_entities (
    chunk_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE CASCADE,
    FOREIGN KEY (entity_id) REFERENCES graph_entities(id) ON DELETE CASCADE,
    PRIMARY KEY (chunk_id, entity_id)
);

-- Eval harness history
CREATE TABLE IF NOT EXISTS eval_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_ts TEXT NOT NULL,
    ndcg_at_10 REAL,
    mrr REAL,
    recall_at_5 REAL,
    questions_run INTEGER,
    config_snapshot TEXT
);

-- User overrides for project routing (learning signal)
CREATE TABLE IF NOT EXISTS routing_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    original_project TEXT,
    corrected_project TEXT NOT NULL,
    override_ts TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE SET NULL
);

COMMIT;
"""


def init_knowledge_db(db_path: Path, diag: Path) -> None:
    """Create knowledge.db with the full schema, if missing."""
    if db_path.exists():
        log(f"knowledge.db already exists at {db_path} — leaving intact.", diag_log=diag)
        return
    log(f"Initializing knowledge.db at {db_path}", diag_log=diag)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()
    log("knowledge.db schema initialized.", diag_log=diag)


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #

def main() -> int:
    paths = get_paths()
    diag = paths["diag_log"]

    # Check sentinel
    if paths["sentinel"].exists():
        log("Sentinel file found; scaffold already completed. Skipping.", diag_log=diag)
        return 0

    log("First-run scaffold begins.", diag_log=diag)

    # 1. Ensure vault root exists
    paths["vault_root"].mkdir(parents=True, exist_ok=True)

    # 2. Copy template tree
    try:
        copy_template_tree(paths["template_root"], paths["vault_root"], diag)
    except Exception as exc:
        log(f"FATAL: template copy failed: {exc}", level="ERROR", diag_log=diag)
        return 1

    # 3. Initialize knowledge.db
    try:
        init_knowledge_db(paths["knowledge_db"], diag)
    except Exception as exc:
        log(f"FATAL: knowledge.db init failed: {exc}", level="ERROR", diag_log=diag)
        return 1

    # 4. Write the sentinel so we don't run again
    paths["sentinel"].parent.mkdir(parents=True, exist_ok=True)
    paths["sentinel"].write_text(
        json.dumps(
            {
                "scaffolded_at": datetime.now(timezone.utc).isoformat(),
                "plugin_root": str(paths["plugin_root"]),
                "vault_root": str(paths["vault_root"]),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    log("Scaffold complete.", diag_log=diag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
