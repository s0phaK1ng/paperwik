#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""SubagentStop hook -- detects when all section writers have finished and
signals Phase 4 (Editor) to run.

Action item A7 (paperwik action item #411). Fires per subagent completion.
Per CoWork V3 probe findings, SubagentStop has a known identity-correlation
bug (#7881). We sidestep it entirely by using draft-file-presence as the
completion signal:

1. Read latest run_id
2. Read pending_sections.json (list of section_ids the Editor is waiting on)
3. Sleep 500ms (paperwik-specific settle delay -- open-Q g resolution -- to
   let the section writer's final flush land on disk before we stat)
4. For each pending section, check if drafts/<section_id>.md exists AND is non-empty
5. If all drafts present, write a `ready_to_stitch` sentinel file and emit a
   stdout message so Claude Code can surface it
6. Update registry entries to "completed" status (best-effort; bug #7881 may
   cause misattribution here -- audit-only, doesn't affect correctness)

Execution budget: <2000ms (500ms settle + typical ~50ms of work). Failure
is silent.

Paperwik-specific: 500ms settle delay added before the ready_to_stitch
check; STATE_ROOT uses explicit USERPROFILE fallback for Windows.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path


def _resolve_state_root() -> Path:
    """Windows-safe state root with explicit USERPROFILE fallback."""
    override = os.environ.get("DEEP_RESEARCH_STATE_ROOT")
    if override:
        return Path(override)
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        return Path(userprofile) / "Paperwik" / ".claude" / "skills" / "state" / "deep-research"
    return Path.home() / "Paperwik" / ".claude" / "skills" / "state" / "deep-research"


STATE_ROOT = _resolve_state_root()


def main() -> int:
    # Read payload (not strictly needed -- we use filesystem state -- but keeps the
    # hook compatible with the Claude Code payload format)
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}

    prompt = payload.get("prompt") or payload.get("tool_input", {}).get("prompt") or ""
    agent_id = payload.get("agent_id") or "unknown"

    latest_file = STATE_ROOT / "latest_run_id.txt"
    if not latest_file.exists():
        return 0
    run_id = latest_file.read_text(encoding="utf-8").strip()
    if not run_id:
        return 0

    run_dir = STATE_ROOT / "runs" / run_id
    pending_file = run_dir / "pending_sections.json"
    drafts_dir = run_dir / "drafts"
    sentinel = run_dir / "ready_to_stitch"

    if not pending_file.exists():
        return 0  # No research run active -- exit silently
    if sentinel.exists():
        return 0  # Already signaled -- idempotent, don't re-fire

    try:
        pending = json.loads(pending_file.read_text(encoding="utf-8"))
        if not isinstance(pending, list):
            return 0
    except Exception:
        return 0

    # Best-effort registry update (may misattribute due to bug #7881 -- audit only)
    registry_file = run_dir / "subagent_registry.json"
    m = re.search(r"section_id:\s*(s\d+)", prompt)
    if m and registry_file.exists():
        try:
            registry = json.loads(registry_file.read_text(encoding="utf-8"))
            # Find most recent entry for this section_id that's still "started"
            for entry in reversed(registry):
                if entry.get("section_id") == m.group(1) and entry.get("status") == "started":
                    entry["status"] = "completed"
                    entry["completed_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
                    entry["completed_by_agent_id"] = agent_id
                    break
            registry_file.write_text(json.dumps(registry, indent=2), encoding="utf-8")
        except Exception:
            pass

    # Paperwik-specific: 500ms settle delay before filesystem stat check.
    # Resolves open-Q g from the CoWork handoff -- under heavy load, a
    # subagent's final write may still be in flight when SubagentStop
    # fires; a short settle window prevents a false "missing section"
    # on a run that would otherwise succeed.
    time.sleep(0.5)

    # Primary signal: check draft file presence
    missing = []
    for section_id in pending:
        draft_file = drafts_dir / f"{section_id}.md"
        if not draft_file.exists() or draft_file.stat().st_size < 50:
            missing.append(section_id)

    if missing:
        # Not all sections in yet -- wait for more completions
        return 0

    # All drafts present -- signal ready
    try:
        sentinel.write_text(
            json.dumps({
                "signaled_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "run_id": run_id,
                "all_sections_complete": pending,
            }, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass

    # Emit a stdout signal the parent session can surface. Claude Code hook
    # stdout for SubagentStop is NOT injected as additionalContext (that's
    # SessionStart behavior), but it is captured in the transcript -- and a
    # user can read it if they're watching the session.
    print(json.dumps({
        "research_status": "all_sections_complete",
        "run_id": run_id,
        "sections": pending,
        "next_phase": "stitch_and_sanitize",
    }))

    return 0


if __name__ == "__main__":
    sys.exit(main())
