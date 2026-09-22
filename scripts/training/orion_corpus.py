#!/usr/bin/env python3
"""ORION corpus intake + real BPE tokenizer helpers (Task 2).

One stable entry point that every training harness reads from:

- `resolve_corpus()` prefers real shards under `data/training/corpus/`
  (`.txt` / `.jsonl`) for serious runs and falls back to the 9 KB smoke
  dataset `data/training/orion_dataset.jsonl` when no shard exists.
- `bpe_tokenizer_available()` / `load_bpe_tokenizer()` gate the real BPE
  tokenizer trained by `bpe_tokenizer.py` into `models/tokenizer_bpe/`.
  Training scripts use the BPE tokenizer only when 1) it was trained AND
  2) the corpus resolves to real shards; otherwise they keep the crc32
  surrogate path, so a fresh checkout with no tokenizer artifacts trains fine.
- `emit_adequacy_gate()` records the corpus-adequacy verdict (`ADEQUATE` vs
  `SMOKE_ONLY`) into the experiment ledger via
  `scripts/repro.py::record_experiment` - the honest gate for a later real
  pre-training run (T4).
"""

import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psutil

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = REPO_ROOT / "data" / "training" / "corpus"
SMOKE_DATASET = REPO_ROOT / "data" / "training" / "orion_dataset.jsonl"
BPE_DIR = REPO_ROOT / "models" / "tokenizer_bpe"
BPE_TOKENIZER_JSON = BPE_DIR / "tokenizer.json"

# Special-token ids - mirror the trainer special-token order in bpe_tokenizer.py.
PAD_ID, BOS_ID, EOS_ID, UNK_ID = 0, 1, 2, 3

# A 100M-parameter model needs a first meaningful pre-training signal. 50M
# tokens (~250 MB of text) is ~0.5 tokens per parameter - a warm-start floor
# that moves every 100M weight measurably. Chinchilla-optimal would be ~2B.
REQUIRED_TOKENS_FOR_100M = 50_000_000
THRESHOLD_RATIONALE = (
    "A 100M-parameter model should see at least ~50M tokens (~0.5 tokens/param; "
    "Chinchilla-optimal would be ~2B) to count as a real pre-training run "
    "rather than a smoke validation."
)

_SUFFIXES = (".txt", ".jsonl")


def _git_commit() -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "unknown"


# --- corpus intake ----------------------------------------------------------


def shard_files(corpus_dir: Path = CORPUS_DIR) -> list:
    """All `.txt` / `.jsonl` shards under the corpus dir, sorted for determinism."""
    if not corpus_dir.is_dir():
        return []
    return sorted(
        p
        for p in corpus_dir.iterdir()
        if p.is_file() and p.suffix.lower() in _SUFFIXES and not p.name.startswith(".")
    )


def resolve_corpus(corpus_dir: Path = CORPUS_DIR) -> tuple:
    """Return (files, source, is_real).

    Prefers real corpus shards for serious runs; falls back to the 9 KB smoke
    dataset so a repo with no corpus still works end to end (is_real=False).
    """
    files = shard_files(corpus_dir)
    if files:
        return files, "corpus-shards", True
    return [SMOKE_DATASET], "smoke-fallback", False


def format_sample(s: dict) -> str:
    return f"INSTRUCTION: {s['instruction']}\nRESPONSE: {s['response']}"


def iter_texts(files):
    """Yield one text document per jsonl row / per txt shard (for BPE training)."""
    for path in files:
        if path.suffix.lower() == ".jsonl":
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    if (
                        isinstance(row, dict)
                        and "instruction" in row
                        and "response" in row
                    ):
                        yield format_sample(row)
                    elif isinstance(row, dict) and "text" in row:
                        yield row["text"]
        else:
            yield path.read_text(encoding="utf-8", errors="ignore")


def load_samples(files):
    """SFT samples (instruction/response) from jsonl shards; txt shards carry
    raw pre-training text and are ignored by the SFT harnesses."""
    rows = []
    for path in files:
        if path.suffix.lower() == ".jsonl":
            with open(path, "r", encoding="utf-8") as f:
                rows.extend(json.loads(line) for line in f if line.strip())
    return rows


def corpus_bytes(files) -> int:
    return sum(p.stat().st_size for p in files)


def corpus_sha256(files) -> str:
    """SHA-256 over the concatenated raw bytes of every shard (stable ordering)."""
    hasher = hashlib.sha256()
    for p in files:
        hasher.update(p.read_bytes())
    return hasher.hexdigest()


def num_documents(files) -> int:
    return sum(1 for _ in iter_texts(files))


# --- BPE tokenizer loading / HF-ish shim ------------------------------------


def bpe_tokenizer_available() -> bool:
    return BPE_TOKENIZER_JSON.exists()


def load_bpe_tokenizer():
    from tokenizers import Tokenizer

    return Tokenizer.from_file(str(BPE_TOKENIZER_JSON))


class BpeCompatTokenizer:
    """Thin HF-like adapter over a raw `tokenizers.Tokenizer` so the training
    scripts keep their existing `tokenizer(texts, padding=True, max_length=...,
    return_tensors="pt")` call sites unchanged."""

    def __init__(self, tokenizer):
        self._tok = tokenizer
        self.pad_token_id = PAD_ID
        self.bos_token_id = BOS_ID
        self.eos_token_id = EOS_ID
        self.vocab_size = tokenizer.get_vocab_size()

    def encode(self, text):
        return self._tok.encode(text)

    def decode(self, ids, skip_special_tokens=False):
        return self._tok.decode(ids, skip_special_tokens=skip_special_tokens)

    def save_pretrained(self, out_dir):
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        self._tok.save(str(out_dir / "tokenizer.json"))
        (out_dir / "tokenizer_config.json").write_text(
            json.dumps(
                {
                    "bos_token": "<bos>",
                    "eos_token": "<eos>",
                    "pad_token": "<pad>",
                    "unk_token": "<unk>",
                    "bos_token_id": BOS_ID,
                    "eos_token_id": EOS_ID,
                    "pad_token_id": PAD_ID,
                    "unk_token_id": UNK_ID,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def __call__(
        self,
        texts,
        padding=False,
        truncation=False,
        max_length=None,
        return_tensors=None,
    ):
        if isinstance(texts, str):
            texts = [texts]
        encs = self._tok.encode_batch(list(texts))
        ids = [e.ids[:max_length] if max_length else e.ids for e in encs]
        masks = [[1] * len(seq) for seq in ids]
        if padding:
            width = max((len(seq) for seq in ids), default=0) or 1
            ids = [seq + [self.pad_token_id] * (width - len(seq)) for seq in ids]
            masks = [m + [0] * (width - len(m)) for m in masks]
        if return_tensors == "pt":
            import torch

            return {
                "input_ids": torch.tensor(ids, dtype=torch.long),
                "attention_mask": torch.tensor(masks, dtype=torch.long),
            }
        return {"input_ids": ids, "attention_mask": masks}


def load_bpe_compat():
    return BpeCompatTokenizer(load_bpe_tokenizer())


def count_corpus_tokens(tokenizer, files) -> tuple:
    """(total_tokens, unique_token_ids) over the resolved corpus texts."""
    total, seen = 0, set()
    for text in iter_texts(files):
        ids = tokenizer.encode(text).ids
        total += len(ids)
        seen.update(ids)
    return total, len(seen)


# --- corpus-adequacy gate ---------------------------------------------------


def emit_adequacy_gate(
    corpus_dir: Path = CORPUS_DIR,
    actual_tokens: int = None,
    vocab_size: int = None,
) -> dict:
    """Record the corpus-adequacy verdict into the experiment ledger via
    scripts/repro.py::record_experiment (experiment `corpus-adequacy-gate`).

    Verdict: ADEQUATE when actual_tokens >= REQUIRED_TOKENS_FOR_100M, else
    SMOKE_ONLY. Re-encodes the corpus when actual_tokens is not supplied.
    """
    files, source, is_real = resolve_corpus(corpus_dir)
    sha = corpus_sha256(files)
    size = corpus_bytes(files)

    if actual_tokens is None or vocab_size is None:
        tok = load_bpe_tokenizer()
        if actual_tokens is None:
            actual_tokens, _ = count_corpus_tokens(tok, files)
        if vocab_size is None:
            vocab_size = tok.get_vocab_size()

    verdict = "ADEQUATE" if actual_tokens >= REQUIRED_TOKENS_FOR_100M else "SMOKE_ONLY"
    needed = max(0, REQUIRED_TOKENS_FOR_100M - actual_tokens)

    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from scripts.repro import record_experiment  # noqa: E402

    record = {
        "run_id": f"corpus-gate-{uuid.uuid4().hex[:8]}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "COMPLETED",
        "base_model_name": "corpus-adequacy-gate",
        "model_type": "corpus-adequacy-gate",
        "dataset_path": str(files[0]) if files else str(SMOKE_DATASET),
        "dataset_hash": sha,
        "num_samples": num_documents(files),
        "seed": 42,
        "epochs": 0,
        "learning_rate": 0.0,
        "starting_loss": 0.0,
        "ending_loss": 0.0,
        "loss_reduction_pct": 0.0,
        "eval_loss": 0.0,
        "checkpoint_path": "",
        "output_differs": False,
        "hardware": {
            "cpu_cores": psutil.cpu_count(logical=False),
            "cpu_threads": psutil.cpu_count(logical=True),
            "available_ram_gb": round(psutil.virtual_memory().available / (1024**3), 2),
            "git_commit": _git_commit(),
        },
        "corpus_path": str(corpus_dir),
        "corpus_source": source,
        "corpus_bytes": size,
        "corpus_sha256": sha,
        "tokenizer_vocab_size": vocab_size,
        "actual_tokens": actual_tokens,
        "required_tokens_for_100m": REQUIRED_TOKENS_FOR_100M,
        "threshold_rationale": THRESHOLD_RATIONALE,
        "verdict": verdict,
        "tokens_short_of_threshold": needed,
        "error_message": "",
    }
    record_experiment(
        "corpus-adequacy-gate",
        {
            "corpus": str(corpus_dir),
            "vocab_size": vocab_size,
            "threshold": REQUIRED_TOKENS_FOR_100M,
        },
        record,
    )

    print(f"[GATE] corpus source={source} shards={[p.name for p in files]}")
    print(f"[GATE] corpus bytes={size:,} | sha256={sha[:16]}...")
    print(
        f"[GATE] tokenizer vocab={vocab_size:,} | actual_tokens={actual_tokens:,} "
        f"| required_tokens_for_100m={REQUIRED_TOKENS_FOR_100M:,}"
    )
    print(f"[GATE] verdict={verdict} (tokens short of 50M threshold: {needed:,})")
    return record


if __name__ == "__main__":
    # Standalone: (re)emit the gate with the current corpus + tokenizer.
    if len(sys.argv) > 1 and sys.argv[1] in ("--gate-only",):
        emit_adequacy_gate(Path(sys.argv[2]) if len(sys.argv) > 2 else CORPUS_DIR)
    else:
        print("usage: python orion_corpus.py --gate-only [CORPUS_DIR]")
