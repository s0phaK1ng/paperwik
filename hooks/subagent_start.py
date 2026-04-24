#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""SubagentStart hook -- registers a spawned section-writer subagent in the
run's registry for correlation + auditing.

Action item A7 (paperwik action item #410). Fires when Claude Code's Task
tool spawns a subagent. Cannot block (SubagentStart is observability-only
per CoWork V3 probe findings).

Behavior:
1. Read the hook payload from stdin (JSON)
2. Check if we can identify this as a research section writer spawn by
   scanning the prompt for the `section_id: s<n>` marker the section writer
   prompt includes
3. If yes, append a tuple {agent_id, session_id, section_id, started_at} to
   ~/Paperwik/.claude/skills/state/deep-research/runs/<latest_run_id>/subagent_registry.json
4. If no match, exit silently (this isn't our subagent)

Bug #7881 note: SubagentStop cannot reliably correlate agent_id, so this
registry is audit-only -- the Editor uses draft-file-presence as the primary
completion signal. See hooks/subagent_stop.py.

Execution budget: <500ms. Failure is silent (never blocks agent work).

Paperwik-specific: STATE_ROOT defaults to %USERPROFILE%\\Paperwik\\.claude\\
skills\\state\\deep-research on Windows. Uses explicit USERPROFILE fallback
in case Python's Path.home() resolution differs from expected on older
Windows Python builds (verified on Python 3.11+ Windows: Path.home()
returns USERPROFILE, but the explicit fallback is defensive).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path


def _resolve_state_root() -> Path:
    """Windows-safe state root with explicit USERPROFILE fallback."""
    override = os.environ.get("DEEP_RESEARCH_STATE_ROOT")
    if override:
        return Path(override)
    # Prefer explicit USERPROFILE on Windows; fall back to Path.home() elsewhere.
    # Paperwik is Windows-only, so USERPROFILE is the canonical variable.
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        return Path(userprofile) / "Paperwik" / ".claude" / "skills" / "state" / "deep-research"
    return Path.home() / "Paperwik" / ".claude" / "skills" / "state" / "deep-research"


STATE_ROOT = _resolve_state_root()


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # Nothing to do if stdin is unreadable

    prompt = payload.get("prompt") or payload.get("tool_input", {}).get("prompt") or ""
    agent_id = payload.get("agent_id") or payload.get("session_id") or "unknown"
    session_id = payload.get("session_id") or "unknown"

    # Is this a research section writer? Look for the signature marker.
    m = re.search(r"section_id:\s*(s\d+)", prompt)
    if not m:
        return 0  # Not our subagent -- exit silently

    section_id = m.group(1)

    # Find the latest run
    latest_file = STATE_ROOT / "latest_run_id.txt"
    if not latest_file.exists():
        # No active run -- may be a stray invocation; log but don't crash
        return 0
    run_id = latest_file.read_text(encoding="utf-8").strip()
    if not run_id:
        return 0

    run_dir = STATE_ROOT / "runs" / run_id
    registry_file = run_dir / "subagent_registry.json"
    run_dir.mkdir(parents=True, exist_ok=True)

    try:
        if registry_file.exists():
            registry = json.loads(registry_file.read_text(encoding="utf-8"))
            if not isinstance(registry, list):
                registry = []
        else:
            registry = []
    except Exception:
        registry = []

    registry.append({
        "agent_id": agent_id,
        "session_id": session_id,
        "section_id": section_id,
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "status": "started",
    })

    try:
        registry_file.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    except Exception:
        pass  # Never block

    return 0


if __name__ == "__main__":
    sys.exit(main())
