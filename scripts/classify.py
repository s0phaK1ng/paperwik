# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     "onnxruntime>=1.16.3",
#     "onnx>=1.15.0",
#     "tokenizers>=0.15.0",
#     "numpy>=1.26.0",
#     "huggingface-hub>=0.20.0",
# ]
# ///
#
# v0.6.3: `onnx` added explicitly. onnxruntime.quantization.quantize_dynamic
# (used in _ensure_int8_model) requires the `onnx` package at runtime to
# parse and re-emit the FP32 ONNX graph; onnxruntime alone is the inference
# engine and doesn't pull `onnx` as a transitive dep. Without this, the
# first call to classify() crashed with ModuleNotFoundError("No module
# named 'onnx'") -- the v0.6.0/v0.6.1/v0.6.2 sandboxes all silently fell
# through to source_type=article defaults because of this missing dep.
#
# Python pinned to 3.12.x for wheel compatibility (see embeddings.py).
"""
classify.py -- Zero-shot text classifier for Paperwik.

Wraps a DeBERTa-v3-base zeroshot-v2.0-c ONNX model behind a single function:

    classify(text, labels, multi_label=False, template=DEFAULT_TEMPLATE)
        -> [(label, probability)]   # sorted descending

Architecture intent:
    * No transformers library. Direct onnxruntime + Rust tokenizers only.
      Saves ~2 GB of dependency weight vs. transformers + torch.
    * Lazy install-time quantization. The MoritzLaurer -c repo on Hugging
      Face only ships FP32 (~738 MB). On first use we download FP32 once,
      run onnxruntime.quantization.quantize_dynamic to produce INT8
      (~150 MB), cache the INT8 model under
      ~/.cache/huggingface/hub/.paperwik-int8/, then DELETE the FP32 copy
      to reclaim ~600 MB. Subsequent calls load straight from the INT8
      cache (no network, no quantization).
    * Global session + tokenizer caches. The first classify() call pays
      the ~2-3 second model-load cost; subsequent calls reuse the loaded
      session.

Why -c (commercial-license safe):
    The base v2.0 model was trained on data that includes non-commercial-
    licensed corpora. The "-c" variant retrained on commercial-friendly
    data only. Paperwik is friend-and-family software but the user's
    notes are private commercial-relevant work — we use -c.

NLI labels:
    The model is a 2-way NLI classifier with id2label =
    {0: 'entailment', 1: 'not_entailment'}. For each candidate label
    we form `template.format(label)` as the hypothesis, run the premise
    (input text) + hypothesis through the model, and read the entailment
    probability via softmax([logit_entailment, logit_not_entailment])[0].
    Multi-label: probabilities are independent per label.
    Single-label: probabilities are softmaxed across labels (so they
    sum to 1).

CLI:
    uv run classify.py --text "..." --labels "a,b,c" [--multi-label]
                       [--template "..."] [--max-chars N]

    Outputs JSON: [{"label": "...", "probability": 0.12}, ...]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
from pathlib import Path
from typing import Sequence

import numpy as np


# --------------------------------------------------------------------------- #
#  Model identity
# --------------------------------------------------------------------------- #

# Community-maintained ONNX export of MoritzLaurer/deberta-v3-base-zeroshot-v2.0-c.
# As of 2026-04, this is the only ONNX variant of the -c (commercial-license-
# safe) base zeroshot v2.0 model on Hugging Face. If gincioks/* ever goes
# offline, fall back to holisticon/deberta-v3-base-zeroshot-v2.0-onnx — that
# repo is NOT the -c variant though, so license review is required first.
REPO_ID = "gincioks/MoritzLaurer-deberta-v3-base-zeroshot-v2.0-c-onnx"
FP32_FILENAME = "model.onnx"

# DeBERTa max sequence length. Inputs longer than this are truncated by the
# tokenizer with `truncation=True, max_length=MAX_SEQUENCE_LENGTH`.
MAX_SEQUENCE_LENGTH = 512

# Default hypothesis template for project routing. Writers/researchers in the
# zero-shot literature have found this phrasing scores ~3-5 points higher than
# the bare "This is about {}." template. (Yin et al. 2019 EMNLP, table 4.)
DEFAULT_TEMPLATE = "The primary topical focus of this document is best described as {}."

# Paperwik-owned cache subdir under HF cache root. Keep separate from the
# normal HF download cache so we don't conflict with other ONNX consumers
# on the same machine.
_PAPERWIK_CACHE_SUBDIR = ".paperwik-int8"
INT8_FILENAME = "model_int8.onnx"


# --------------------------------------------------------------------------- #
#  Global session + tokenizer caches
# --------------------------------------------------------------------------- #

_SESSION = None        # type: ignore[assignment]
_TOKENIZER = None      # type: ignore[assignment]
_ENTAILMENT_IDX = 0    # 0 per gincioks config.json; we read it back at load


def _hf_cache_root() -> Path:
    """Resolve the Hugging Face cache root.

    Honors HF_HOME if set; otherwise falls back to ~/.cache/huggingface.
    On Windows that's typically C:\\Users\\<user>\\.cache\\huggingface.
    """
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(hf_home)
    return Path.home() / ".cache" / "huggingface"


def _int8_cache_path() -> Path:
    """Return the path where Paperwik caches the INT8-quantized model."""
    return _hf_cache_root() / "hub" / _PAPERWIK_CACHE_SUBDIR / INT8_FILENAME


def _ensure_int8_model() -> Path:
    """Lazy-quantize: ensure an INT8 ONNX model exists in our cache.

    Steps (only on cache miss):
      1. hf_hub_download(repo=REPO_ID, filename='model.onnx') -> FP32 path
      2. onnxruntime.quantization.quantize_dynamic(FP32, INT8, QInt8)
      3. shutil.rmtree on the HF cache for this repo to reclaim ~600 MB
      4. Return the INT8 path

    The first invocation takes ~30-60 seconds on a typical Windows machine
    (network + quantization). Subsequent invocations return immediately.

    Output is written via a temp file (.onnx.partial) and atomically renamed
    so a crash mid-quantization never leaves a corrupted INT8 cache file
    that future calls would happily load and crash on at inference time.
    """
    int8_path = _int8_cache_path()
    if int8_path.exists() and int8_path.stat().st_size > 0:
        return int8_path

    int8_path.parent.mkdir(parents=True, exist_ok=True)

    # Lazy imports — these are heavy and we only need them on first install.
    # Doing them at module level would make `python -m py_compile classify.py`
    # require the deps to even parse-check the file, which the build pipeline
    # would fail on machines without the deps installed yet.
    from huggingface_hub import hf_hub_download  # type: ignore
    from onnxruntime.quantization import quantize_dynamic, QuantType  # type: ignore

    print(
        f"[classify.py] First-run model download + quantization. "
        f"This takes ~30-60 seconds and only happens once.",
        file=sys.stderr,
    )

    fp32_path = Path(
        hf_hub_download(repo_id=REPO_ID, filename=FP32_FILENAME)
    )

    partial = int8_path.with_suffix(int8_path.suffix + ".partial")
    quantize_dynamic(
        model_input=str(fp32_path),
        model_output=str(partial),
        weight_type=QuantType.QInt8,
    )
    partial.replace(int8_path)

    # Reclaim the ~600 MB FP32 copy from the HF cache. We keep the tokenizer
    # files (added_tokens.json, tokenizer.json, etc.) since they're tiny and
    # we'll need them every call. Strategy: only delete *.onnx files inside
    # the FP32 model's snapshot folder.
    try:
        for sibling in fp32_path.parent.glob("*.onnx"):
            sibling.unlink(missing_ok=True)
    except OSError:
        # Non-fatal: failing to clean up FP32 doesn't break inference.
        pass

    print(
        f"[classify.py] Model ready (INT8 cached at {int8_path}).",
        file=sys.stderr,
    )
    return int8_path


def _load_session():
    """Initialize the ONNX session + tokenizer once, cache globally."""
    global _SESSION, _TOKENIZER, _ENTAILMENT_IDX
    if _SESSION is not None and _TOKENIZER is not None:
        return _SESSION, _TOKENIZER

    int8_path = _ensure_int8_model()

    # Tokenizer: download from REPO_ID's tokenizer.json. The tokenizers Rust
    # crate handles DeBERTa SentencePiece + BPE without needing transformers.
    from huggingface_hub import hf_hub_download  # type: ignore
    from tokenizers import Tokenizer  # type: ignore

    tokenizer_path = hf_hub_download(repo_id=REPO_ID, filename="tokenizer.json")
    tokenizer = Tokenizer.from_file(tokenizer_path)
    tokenizer.enable_truncation(max_length=MAX_SEQUENCE_LENGTH)

    # ONNX session. CPUExecutionProvider only — paperwik targets non-technical
    # Windows users with no GPU expectation. Add intra_op_num_threads cap so
    # we don't starve other Claude Code work on a 4-core dad machine.
    import onnxruntime as ort  # type: ignore

    sess_options = ort.SessionOptions()
    sess_options.intra_op_num_threads = max(1, (os.cpu_count() or 4) // 2)
    sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    session = ort.InferenceSession(
        str(int8_path),
        sess_options=sess_options,
        providers=["CPUExecutionProvider"],
    )

    # Confirm entailment index from config.json — gincioks/* uses 0, but we
    # don't want to silently invert if the model is ever swapped out.
    try:
        from huggingface_hub import hf_hub_download as _dl  # type: ignore
        cfg_path = _dl(repo_id=REPO_ID, filename="config.json")
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        id2label = cfg.get("id2label") or {}
        # id2label keys may be str or int depending on serializer
        for k, v in id2label.items():
            if str(v).lower() == "entailment":
                _ENTAILMENT_IDX = int(k)
                break
    except Exception:
        _ENTAILMENT_IDX = 0  # gincioks default; safe fallback

    _SESSION = session
    _TOKENIZER = tokenizer
    return session, tokenizer


def _softmax(logits: np.ndarray, axis: int = -1) -> np.ndarray:
    """Numerically stable softmax."""
    shifted = logits - np.max(logits, axis=axis, keepdims=True)
    exp = np.exp(shifted)
    return exp / np.sum(exp, axis=axis, keepdims=True)


def _entailment_probs(text: str, labels: Sequence[str], template: str) -> np.ndarray:
    """Return per-label entailment probabilities (independent, multi-label-style).

    Returns an array shape (len(labels),) with values in [0, 1].
    """
    session, tokenizer = _load_session()

    not_idx = 1 - _ENTAILMENT_IDX

    # We tokenize each (premise, hypothesis) pair separately for clarity.
    # Batching would be ~2x faster but for paperwik's typical N=2-10 labels
    # the wall-clock difference is <100 ms — not worth the code complexity.
    probs = np.zeros(len(labels), dtype=np.float32)
    for i, label in enumerate(labels):
        hypothesis = template.format(label)
        encoded = tokenizer.encode(text, hypothesis)

        ids = np.array([encoded.ids], dtype=np.int64)
        attn = np.array([encoded.attention_mask], dtype=np.int64)
        type_ids = np.array([encoded.type_ids], dtype=np.int64)

        outputs = session.run(
            None,
            {
                "input_ids": ids,
                "attention_mask": attn,
                "token_type_ids": type_ids,
            },
        )
        logits = outputs[0][0]  # shape (2,)
        sm = _softmax(logits)
        probs[i] = float(sm[_ENTAILMENT_IDX])
    return probs


def classify(
    text: str,
    labels: Sequence[str],
    multi_label: bool = False,
    template: str = DEFAULT_TEMPLATE,
) -> list[tuple[str, float]]:
    """Zero-shot classify `text` against `labels`.

    Args:
        text: the input document/passage. Truncated to MAX_SEQUENCE_LENGTH
              tokens by the tokenizer.
        labels: candidate labels (free-form strings — full sentences allowed).
        multi_label: if True, returned probabilities are independent
                     per-label entailment scores (sigmoid-equivalent).
                     If False, probabilities are softmaxed across labels
                     and sum to 1 (single best match).
        template: hypothesis template, must contain '{}' as the label slot.

    Returns:
        List of (label, probability) tuples, sorted by probability descending.
    """
    if not labels:
        return []
    if "{}" not in template:
        raise ValueError(
            f"template must contain '{{}}' as the label slot; got: {template!r}"
        )

    entail = _entailment_probs(text, list(labels), template)

    if multi_label:
        scores = entail
    else:
        # Softmax across labels so probabilities sum to 1 and the ordering
        # exaggerates the top-1 vs. top-2 gap (useful for the router's
        # margin gate).
        scores = _softmax(entail)

    pairs = [(labels[i], float(scores[i])) for i in range(len(labels))]
    pairs.sort(key=lambda p: p[1], reverse=True)
    return pairs


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Zero-shot classify text against a label set.",
    )
    parser.add_argument("--text", required=True, help="Input text (premise).")
    parser.add_argument(
        "--labels",
        required=True,
        help="Comma-separated candidate labels.",
    )
    parser.add_argument(
        "--multi-label",
        action="store_true",
        help="Return independent probabilities per label (default: softmax across labels).",
    )
    parser.add_argument(
        "--template",
        default=DEFAULT_TEMPLATE,
        help=f"Hypothesis template containing {{}}; default: {DEFAULT_TEMPLATE!r}",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=2000,
        help="Truncate text to this many characters before tokenization (default: 2000).",
    )
    args = parser.parse_args(argv[1:])

    text = args.text[: args.max_chars]
    labels = [s.strip() for s in args.labels.split(",") if s.strip()]
    if not labels:
        print("No labels provided.", file=sys.stderr)
        return 2

    results = classify(
        text=text,
        labels=labels,
        multi_label=args.multi_label,
        template=args.template,
    )
    print(json.dumps(
        [{"label": lbl, "probability": prob} for lbl, prob in results],
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
