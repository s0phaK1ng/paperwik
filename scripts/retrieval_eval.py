# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""
retrieval_eval.py — NDCG@10 + MRR + Recall@5 against a user-authored question set.

Reads <vault>/eval.json, replays each question against the current search
pipeline, computes metrics, stores results in the eval_runs table of
knowledge.db, and alerts the diagnostic log if any metric drops ≥0.05 WoW.

Usage (invoked by /measure-retrieval skill or weekly Task Scheduler cron):
    uv run retrieval_eval.py

Exit codes: 0 = ran successfully (metrics in DB); non-zero = hard failure.
A drop alert is NOT a non-zero exit; it's an entry in the diagnostic log.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


# --------------------------------------------------------------------------- #
#  Metric primitives
# --------------------------------------------------------------------------- #

def ndcg_at_k(retrieved_ids: list, expected_ids: list, k: int = 10) -> float:
    """Normalized Discounted Cumulative Gain at k.

    Treats expected_ids as binary relevance (1 if in expected set, else 0).
    retrieved_ids: ranked list returned by the search pipeline.
    expected_ids: set of chunk IDs the user said SHOULD be in the top results.
    """
    if not expected_ids:
        return 0.0
    expected_set = set(expected_ids)
    top_k = retrieved_ids[:k]

    dcg = 0.0
    for i, chunk_id in enumerate(top_k, start=1):
        rel = 1.0 if chunk_id in expected_set else 0.0
        dcg += rel / math.log2(i + 1)

    # Ideal DCG: relevant items in the top positions, up to min(|expected|, k)
    ideal_n = min(len(expected_set), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_n + 1))
    if idcg == 0.0:
        return 0.0
    return dcg / idcg


def mrr(retrieved_ids: list, expected_ids: list) -> float:
    """Mean Reciprocal Rank (single query). Returns 1/rank_of_first_relevant, or 0 if none."""
    expected_set = set(expected_ids)
    for i, chunk_id in enumerate(retrieved_ids, start=1):
        if chunk_id in expected_set:
            return 1.0 / i
    return 0.0


def recall_at_k(retrieved_ids: list, expected_ids: list, k: int = 5) -> float:
    """Fraction of expected items that appear in the top-k retrieved list."""
    if not expected_ids:
        return 0.0
    expected_set = set(expected_ids)
    top_k = set(retrieved_ids[:k])
    return len(top_k & expected_set) / len(expected_set)


# --------------------------------------------------------------------------- #
#  Eval runner
# --------------------------------------------------------------------------- #

def run_eval(
    eval_path: Path,
    search_fn: Callable[[str], list],
    db_path: Path,
    config_snapshot: str | None = None,
) -> dict:
    """Run the eval set and persist results. Returns a dict of averaged metrics.

    search_fn: callable that takes a query string and returns a ranked list of chunk IDs.
    """
    if not eval_path.exists():
        raise FileNotFoundError(f"eval.json not found at {eval_path}")

    data = json.loads(eval_path.read_text(encoding="utf-8"))
    questions = data.get("questions", [])
    if not questions:
        raise ValueError("eval.json has no questions — dad needs to fill in at least one")

    per_question = []
    for q in questions:
        query = q["question"]
        expected = q.get("expected_chunks", [])
        retrieved = search_fn(query)  # list of chunk IDs (ints)

        per_question.append({
            "question": query,
            "ndcg_at_10": ndcg_at_k(retrieved, expected, k=10),
            "mrr": mrr(retrieved, expected),
            "recall_at_5": recall_at_k(retrieved, expected, k=5),
            "retrieved_count": len(retrieved),
            "expected_count": len(expected),
        })

    avg_ndcg = sum(p["ndcg_at_10"] for p in per_question) / len(per_question)
    avg_mrr = sum(p["mrr"] for p in per_question) / len(per_question)
    avg_recall = sum(p["recall_at_5"] for p in per_question) / len(per_question)

    ts = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            INSERT INTO eval_runs (run_ts, ndcg_at_10, mrr, recall_at_5, questions_run, config_snapshot)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (ts, avg_ndcg, avg_mrr, avg_recall, len(questions), config_snapshot or ""),
        )
        conn.commit()
    finally:
        conn.close()

    # Update eval.json with last-run info
    data["last_run"] = ts
    data["last_run_metrics"] = {
        "ndcg_at_10": avg_ndcg,
        "mrr": avg_mrr,
        "recall_at_5": avg_recall,
        "questions_run": len(questions),
    }
    eval_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    return {
        "ndcg_at_10": avg_ndcg,
        "mrr": avg_mrr,
        "recall_at_5": avg_recall,
        "per_question": per_question,
        "ts": ts,
    }


# --------------------------------------------------------------------------- #
#  Week-over-week drop detection
# --------------------------------------------------------------------------- #

def check_drop(db_path: Path, alert_threshold: float = 0.05) -> dict | None:
    """Compare the most recent eval_run to the one immediately prior.

    Returns a dict describing the drop if any metric dropped by ≥ alert_threshold,
    else None.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT run_ts, ndcg_at_10, mrr, recall_at_5 FROM eval_runs ORDER BY id DESC LIMIT 2"
        ).fetchall()
    finally:
        conn.close()
    if len(rows) < 2:
        return None
    newest, prior = rows[0], rows[1]
    drops = {}
    for name, i in [("ndcg_at_10", 1), ("mrr", 2), ("recall_at_5", 3)]:
        prior_v = prior[i] or 0.0
        newest_v = newest[i] or 0.0
        delta = prior_v - newest_v
        if delta >= alert_threshold:
            drops[name] = {"prior": prior_v, "newest": newest_v, "delta": delta}
    if not drops:
        return None
    return {
        "prior_ts": prior[0],
        "newest_ts": newest[0],
        "drops": drops,
    }


def write_alert(drop: dict) -> None:
    """Append a DIAG alert to Paperwik-Diagnostics.log so the maintainer sees it on weekly review."""
    user_profile = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    log_path = user_profile / "Documents" / "Paperwik-Diagnostics.log"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    drops_fmt = ", ".join(
        f"{k}: {v['prior']:.3f} -> {v['newest']:.3f} (delta -{v['delta']:.3f})"
        for k, v in drop["drops"].items()
    )
    line = (
        f"[{ts}] [ALERT] [retrieval_eval] WoW retrieval drop detected. "
        f"Prior run {drop['prior_ts']}, newest {drop['newest_ts']}. {drops_fmt}"
    )
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #

def main() -> int:
    user_profile = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    vault = user_profile / "Paperwik" / "Vault"
    eval_path = vault / "eval.json"
    db_path = vault / "knowledge.db"

    if not eval_path.exists():
        print(f"eval.json not found at {eval_path}", file=sys.stderr)
        return 2

    # Lazy import: avoid loading the retrieval stack if search.py is missing
    try:
        from search import search as hybrid_search  # type: ignore
    except ImportError:
        print("search.py not yet ported — eval harness scaffolding only", file=sys.stderr)
        return 3

    def _search_fn(q: str) -> list:
        # hybrid_search returns a list of dicts with 'id' keys; convert to id list
        results = hybrid_search(q, limit=10)
        return [r["id"] for r in results]

    try:
        metrics = run_eval(eval_path, _search_fn, db_path)
    except Exception as exc:
        print(f"Eval failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"Eval complete. NDCG@10={metrics['ndcg_at_10']:.3f} "
        f"MRR={metrics['mrr']:.3f} Recall@5={metrics['recall_at_5']:.3f}"
    )

    drop = check_drop(db_path)
    if drop:
        write_alert(drop)
        print("Alert written: see Documents\\Paperwik-Diagnostics.log", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
