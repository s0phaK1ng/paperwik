# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     "fastembed>=0.4.0",
#     "flashrank>=0.2.9",
#     "spacy>=3.7.0",
# ]
# ///
#
# Python pinned to 3.12.x for wheel compatibility. See embeddings.py
# for the detailed reason (py-rust-stemmers / MSVC-link shadow).
"""
setup-models.py — First-ingest retrieval-model bootstrap.

Invoked by the ingest-source skill the first time the user asks to process a
source. Preloads fastembed (nomic-embed-text-v1.5), FlashRank
(ms-marco-MiniLM-L-12-v2), and the spaCy en_core_web_sm pipeline. Each
library caches the downloaded model under ~/.cache/ (fastembed/flashrank) or
via pip (spaCy), so subsequent invocations are instant.

Total first-run download: ~600 MB on a 50 Mbps connection = 3–5 minutes.

Shows friendly progress messages to stderr (which Claude Code relays to the
user via the surrounding skill). Exits 0 on success, non-zero on failure —
the calling skill is expected to interpret a non-zero exit as "tell the user
to check their network."
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def log(msg: str, level: str = "INFO") -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", file=sys.stderr, flush=True)


def write_diag(msg: str) -> None:
    """Append to Documents\\Paperwik-Diagnostics.log. Never raises."""
    try:
        user_profile = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
        log_path = user_profile / "Documents" / "Paperwik-Diagnostics.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{ts}] [setup-models] {msg}\n")
    except Exception:
        pass


def load_fastembed() -> bool:
    """Preload the nomic-embed-text-v1.5 ONNX model."""
    log("Loading embedding model (fastembed, nomic-embed-text-v1.5, ~400 MB)...")
    try:
        from fastembed import TextEmbedding

        model = TextEmbedding(model_name="nomic-ai/nomic-embed-text-v1.5", threads=4)
        # Warm up — also confirms the model actually loaded
        _ = list(model.embed(["warmup"]))
        log("Embedding model ready.")
        return True
    except Exception as exc:
        log(f"Embedding model failed to load: {exc}", level="ERROR")
        write_diag(f"fastembed load failure: {exc}")
        return False


def load_flashrank() -> bool:
    """Preload the MiniLM cross-encoder reranker."""
    log("Loading reranker (FlashRank, ms-marco-MiniLM-L-12-v2, ~150 MB)...")
    try:
        from flashrank import Ranker

        ranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2")
        # Warm up with a trivial rerank to materialize the model on disk.
        # Newer flashrank versions take a RerankRequest object; older ones use kwargs.
        try:
            from flashrank import RerankRequest
            _ = ranker.rerank(RerankRequest(query="warmup", passages=[{"id": "1", "text": "warmup"}]))
        except ImportError:
            _ = ranker.rerank(query="warmup", passages=[{"id": 1, "text": "warmup"}])
        log("Reranker ready.")
        return True
    except Exception as exc:
        log(f"Reranker failed to load: {exc}", level="ERROR")
        write_diag(f"flashrank load failure: {exc}")
        return False


def load_spacy() -> bool:
    """Ensure spaCy's en_core_web_sm model is installed and loadable."""
    log("Loading query-decomposition model (spaCy en_core_web_sm, ~50 MB)...")
    try:
        import spacy

        try:
            nlp = spacy.load("en_core_web_sm")
        except OSError:
            log("en_core_web_sm not found locally; downloading now...")
            import subprocess

            subprocess.run(
                [sys.executable, "-m", "spacy", "download", "en_core_web_sm"],
                check=True,
            )
            nlp = spacy.load("en_core_web_sm")

        _ = nlp("warmup")
        log("Query-decomposition model ready.")
        return True
    except Exception as exc:
        log(f"spaCy model failed to load: {exc}", level="ERROR")
        write_diag(f"spacy load failure: {exc}")
        return False


def main() -> int:
    log("Paperwik first-ingest model bootstrap starting.")
    log("This is a one-time download (~600 MB total) — approximately 3-5 minutes on a typical home connection.")
    log("")

    ok_fastembed = load_fastembed()
    ok_flashrank = load_flashrank()
    ok_spacy = load_spacy()

    if ok_fastembed and ok_flashrank and ok_spacy:
        log("")
        log("All retrieval models ready. Subsequent ingests will skip this setup.")
        write_diag("All retrieval models loaded successfully on first run.")
        return 0

    log("")
    log("One or more models failed to load — see Documents\\Paperwik-Diagnostics.log.", level="ERROR")
    log("Common causes: no internet connection, corporate firewall blocking huggingface.co, antivirus interference.")
    log("Retry after fixing the network issue by running an ingest again.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
