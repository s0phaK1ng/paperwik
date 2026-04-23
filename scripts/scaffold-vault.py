# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = []
# ///
#
# Python pinned to 3.12.x for consistency with the rest of the Paperwik
# scripts. Scaffolder itself has no third-party dependencies so this
# wouldn't strictly matter here, but using the same Python version across
# all scripts lets uv share a single cached interpreter.
r"""
scaffold-vault.py — First-run setup for Paperwik.

Runs via `uv run` from the SessionStart hook (or directly from install.ps1).

Two-layer layout:
    %USERPROFILE%\Paperwik\          ← system root (Claude Code project dir)
        CLAUDE.md                    ← agent persona
        index.md                     ← agent-maintained catalog
        log.md                       ← agent-maintained audit trail
        eval.json                    ← retrieval-health questions
        knowledge.db                 ← retrieval DB (NOT in Obsidian's vault)
        .claude\                     ← Claude Code config (settings, skills state)
        .scaffolded                  ← idempotency sentinel
        Vault\                       ← Obsidian's vault (user-facing only)
            Welcome.md
            .obsidian\               ← Obsidian config (themes, hide-rules, plugins)
            Inbox\                   ← drop-zone for new sources
            Projects\                ← all project folders nest here

Responsibilities (in order):
    1. Always: refresh agent-managed config dirs (.claude/ and Vault/.obsidian/)
       so template fixes propagate to existing installs without forcing the
       user to wipe and re-scaffold.
    2. First run only (gated by .scaffolded sentinel): copy the rest of the
       template tree, init knowledge.db, write the sentinel.

User-content files (Welcome.md, anything in Vault/Projects/ or Vault/Inbox/)
are NEVER overwritten on re-run, so the user's notes are safe.

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
    """Resolve the canonical Paperwik paths from env vars.

    paperwik_root is the SYSTEM root where Claude Code runs (cwd).
    vault_root is the USER-FACING Obsidian vault, nested inside paperwik_root.
    """
    user_profile = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    paperwik_root = user_profile / "Paperwik"
    vault_root = paperwik_root / "Vault"
    plugin_root_env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root_env:
        plugin_root = Path(plugin_root_env)
    else:
        # Fallback: assume this script lives in <plugin>/scripts/
        plugin_root = Path(__file__).resolve().parent.parent

    template_root = plugin_root / "templates" / "paperwik"
    documents = user_profile / "Documents"

    return {
        "user_profile": user_profile,
        "paperwik_root": paperwik_root,
        "vault_root": vault_root,
        "plugin_root": plugin_root,
        "template_root": template_root,
        "documents": documents,
        "sentinel": paperwik_root / ".claude" / ".scaffolded",
        "knowledge_db": paperwik_root / "knowledge.db",
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

def copy_template_tree(template_root: Path, paperwik_root: Path, diag: Path) -> None:
    """Full first-run copy of the template tree into the user's Paperwik dir.

    template_root is plugin/templates/paperwik/ and contains both the system
    files (CLAUDE.md, index.md, log.md, eval.json, .claude/) AND the
    user-facing Vault/ subfolder. shutil.copytree with dirs_exist_ok=True
    overwrites existing files — fine on first run because the user has no
    customizations yet.

    Subsequent runs use refresh_managed_dirs() (selective overwrite) instead
    of this function, so user content is preserved.
    """
    if not template_root.exists():
        raise RuntimeError(
            f"Template directory not found at {template_root}. "
            f"Set CLAUDE_PLUGIN_ROOT env var or verify the plugin install."
        )

    log(f"Copying full template tree: {template_root} -> {paperwik_root}", diag_log=diag)
    shutil.copytree(
        src=str(template_root),
        dst=str(paperwik_root),
        dirs_exist_ok=True,
    )
    log("Full template tree copied.", diag_log=diag)


def refresh_managed_dirs(template_root: Path, paperwik_root: Path, diag: Path) -> None:
    """Selectively overwrite agent-managed config dirs from the template.

    Runs on EVERY scaffolder invocation (not gated by sentinel) so that
    template fixes — like new Obsidian app.json settings or updated Claude
    settings.json permissions — propagate to existing installs without
    requiring the user to wipe and re-scaffold.

    Refreshed:
      - Vault/.obsidian/  (Obsidian config: app.json, community-plugins.json)

    NOT touched on refresh (would risk overwriting user/agent state):
      - .claude/  (settings.json may have user mods, skills/state has agent
        memory)
      - CLAUDE.md, index.md, log.md, eval.json (might be edited)
      - Vault/Welcome.md, Vault/Inbox/*, Vault/Projects/*  (user content)
    """
    refresh_targets = [
        Path("Vault") / ".obsidian",
    ]
    for rel in refresh_targets:
        src = template_root / rel
        dst = paperwik_root / rel
        if not src.exists():
            log(f"Skipping refresh of {rel}: template source missing.", level="WARN", diag_log=diag)
            continue
        log(f"Refreshing managed dir: {rel}", diag_log=diag)
        # Wipe destination first so removed-from-template files actually disappear
        if dst.exists():
            shutil.rmtree(str(dst))
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src=str(src), dst=str(dst))
    log("Managed-dir refresh complete.", diag_log=diag)


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

    # On every run: refresh agent-managed config dirs so template fixes
    # (Obsidian app.json, etc.) propagate to existing installs even if the
    # full scaffold has already happened.
    paths["paperwik_root"].mkdir(parents=True, exist_ok=True)
    try:
        refresh_managed_dirs(paths["template_root"], paths["paperwik_root"], diag)
    except Exception as exc:
        # Non-fatal — log and continue. Refresh failures shouldn't block
        # ingest if the user has a working install.
        log(f"Managed-dir refresh failed (non-fatal): {exc}", level="WARN", diag_log=diag)

    # Check sentinel — if first-run scaffold has already happened, we're done
    if paths["sentinel"].exists():
        log("Sentinel found; first-run scaffold already done. Refresh-only mode complete.", diag_log=diag)
        return 0

    log("First-run scaffold begins.", diag_log=diag)

    # First-run: copy the full template tree (system + Vault) into ~/Paperwik/
    try:
        copy_template_tree(paths["template_root"], paths["paperwik_root"], diag)
    except Exception as exc:
        log(f"FATAL: template copy failed: {exc}", level="ERROR", diag_log=diag)
        return 1

    # First-run: initialize knowledge.db (lives at the SYSTEM root, not in Vault/)
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
