#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Windows wake-lock wrapper for the paperwik research engine.

Action item #412. Prevents the laptop from sleeping mid-run. A 10-minute
research session on a consumer Windows laptop WILL be interrupted by the
default sleep timer (30 min idle, but the mid-run cadence of the research
skill mostly looks like idle time -- the agent is waiting for subagents,
not actively typing).

Mechanism: powercfg /change standby-timeout-ac VALUE. Works on standard
user accounts (no admin required). AC-only because these runs assume the
laptop is plugged in (a 10-min WebSearch-heavy run on battery would be a
different kind of bad).

Usage (from SKILL.md Phase 0):

    import sys
    from pathlib import Path
    PLUGIN_ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
    from wake_lock import enforce_wake_lock, release_wake_lock

    enforce_wake_lock()
    try:
        run_engine(topic)
    finally:
        release_wake_lock()

Design notes:
- Silent on failure (check=False). If powercfg errors, the engine still
  runs -- the worst case is the laptop sleeps mid-session, which the user
  can detect (partial output) and retry.
- Does NOT touch -dc (battery) timeout. Users on battery get the default
  behavior (sleep after idle), which is actually what you want -- runs
  started on battery will produce a partial output + the user learns to
  plug in next time.
"""
from __future__ import annotations

import subprocess

# Default AC standby timeout to restore on teardown. 30 minutes is Windows
# default; if the user has set it differently, this restore overwrites
# their preference -- acceptable for v0.4.0.
DEFAULT_STANDBY_TIMEOUT_MIN = 30


def enforce_wake_lock() -> None:
    """Disable AC-power sleep for the duration of the research run."""
    subprocess.run(
        ["powercfg", "/change", "standby-timeout-ac", "0"],
        shell=False,
        check=False,
        capture_output=True,
    )


def release_wake_lock(restore_minutes: int = DEFAULT_STANDBY_TIMEOUT_MIN) -> None:
    """Restore AC-power sleep to a reasonable default."""
    subprocess.run(
        ["powercfg", "/change", "standby-timeout-ac", str(restore_minutes)],
        shell=False,
        check=False,
        capture_output=True,
    )


if __name__ == "__main__":
    import argparse
    import sys

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["enforce", "release"])
    p.add_argument("--restore-minutes", type=int, default=DEFAULT_STANDBY_TIMEOUT_MIN)
    args = p.parse_args()

    if args.action == "enforce":
        enforce_wake_lock()
        print(f"wake_lock: enforced (standby-timeout-ac=0)")
    else:
        release_wake_lock(args.restore_minutes)
        print(f"wake_lock: released (standby-timeout-ac={args.restore_minutes})")
    sys.exit(0)
