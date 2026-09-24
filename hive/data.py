"""Corpus and custom dataset slice + block building for ORION-HIVE.

Supports:
1. Standard local ORION corpus shards (`data/training/corpus/`)
2. Hugging Face dataset streams/downloads (`--hf-dataset <name>`, e.g. `wikitext`, `openwebtext`, `imdb`, or custom repo)
3. Custom databases (SQLite `.db` / `.sqlite`, PostgreSQL connection string, or JSONL / raw text directories)
"""

import json
import sqlite3
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (
    str(REPO_ROOT),
    str(REPO_ROOT / "scripts"),
    str(REPO_ROOT / "scripts" / "training"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import torch  # noqa: E402

import orion_corpus  # noqa: E402
from orion_runner.loader import tokenize_samples, pack_sequences  # noqa: E402

from hive.model import MAX_LEN, PAD_ID  # noqa: E402

MAX_EVAL_BLOCKS = 60  # ~30k held-out tokens; wall guard for CPU eval


def resolve():
    files, source, is_real = orion_corpus.resolve_corpus()
    if not is_real or not orion_corpus.bpe_tokenizer_available():
        raise SystemExit(
            "[HIVE] need real corpus shards under data/training/corpus/ and a "
            "trained BPE tokenizer at models/tokenizer_bpe/tokenizer.json"
        )
    return files, source


def load_from_sqlite(db_path: str, table: str = "texts", column: str = "text", budget: int = 120000):
    """Load text samples directly from an SQLite database."""
    tokenizer = orion_corpus.load_bpe_compat()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(f"SELECT {column} FROM {table}")
    rows, slice_tokens = [], 0
    for r in cur:
        text = str(r[0]) if r[0] else ""
        if not text.strip():
            continue
        row = {"text": text, "provenance": f"sqlite://{db_path}/{table}"}
        rows.append(row)
        slice_tokens += len(tokenizer.encode(text).ids)
        if slice_tokens >= budget:
            break
    conn.close()
    return rows, slice_tokens, tokenizer


def load_from_huggingface(dataset_name: str, config: Optional[str] = None, split: str = "train", text_column: str = "text", budget: int = 120000):
    """Stream or load text rows directly from Hugging Face datasets.
    
    Dynamically finds string columns (e.g. English, Hinglish, text, sentence, document, translation).
    """
    from datasets import load_dataset

    if dataset_name == "wikitext" and not config:
        config = "wikitext-2-raw-v1"

    tokenizer = orion_corpus.load_bpe_compat()
    print(f"[DATASET] Streaming Hugging Face dataset {dataset_name} (split={split})...")
    ds = load_dataset(dataset_name, config, split=split, streaming=True)
    rows, slice_tokens = [], 0
    for item in ds:
        text = ""
        if text_column in item and isinstance(item[text_column], str):
            text = item[text_column]
        elif "content" in item and isinstance(item["content"], str):
            text = item["content"]
        else:
            # Auto-detect all string fields or paired translation fields (e.g. English + Hinglish)
            pieces = []
            for k, v in item.items():
                if isinstance(v, str) and v.strip():
                    pieces.append(v.strip())
            text = " \n ".join(pieces)
        
        if not text.strip():
            continue
        row = {"text": text, "provenance": f"hf://{dataset_name}/{split}"}
        rows.append(row)
        slice_tokens += len(tokenizer.encode(text).ids)
        if slice_tokens >= budget:
            break
    print(f"[DATASET] Loaded {len(rows)} samples ({slice_tokens:,} tokens) from {dataset_name}")
    return rows, slice_tokens, tokenizer


def load_train_rows(budget: int, hf_dataset: Optional[str] = None, sqlite_db: Optional[str] = None):
    """Rows from either custom HF dataset, SQLite DB, or default train-* shards until `budget` tokens are consumed."""
    if hf_dataset:
        return load_from_huggingface(hf_dataset, budget=budget)
    if sqlite_db:
        return load_from_sqlite(sqlite_db, budget=budget)

    files, _ = resolve()
    tokenizer = orion_corpus.load_bpe_compat()
    train_files = orion_corpus.train_shards(files)
    rows, slice_tokens = [], 0
    for path in train_files:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                rows.append(row)
                slice_tokens += len(tokenizer.encode(orion_corpus.row_text(row)).ids)
                if slice_tokens >= budget:
                    break
        if slice_tokens >= budget:
            break
    return rows, slice_tokens, tokenizer


def build_blocks(rows, tokenizer, seed: int, max_seq_len: int = MAX_LEN):
    """Packed blocks with attention-mask token counts, deterministic."""
    samples = tokenize_samples(
        rows, tokenizer, orion_corpus.row_text, max_len=max_seq_len, truncation=True
    )
    packed = pack_sequences(
        samples,
        max_len=max_seq_len,
        pad_id=PAD_ID,
        seed=seed,
        mask_boundaries=True,
        pad_to_max=True,
    )
    blocks = []
    for b in packed:
        ids = torch.tensor(b["input_ids"], dtype=torch.long)
        attn = torch.tensor(b["attention_mask"], dtype=torch.long)
        labels = torch.tensor(b["labels"], dtype=torch.long)
        blocks.append(
            {
                "input_ids": ids,
                "attention_mask": attn,
                "labels": labels,
                "block_tokens": int(attn.sum().item()),
            }
        )
    return blocks


def load_train_blocks(budget: int, seed: int, hf_dataset: Optional[str] = None, sqlite_db: Optional[str] = None, max_seq_len: int = MAX_LEN):
    rows, slice_tokens, tokenizer = load_train_rows(budget, hf_dataset=hf_dataset, sqlite_db=sqlite_db)
    return build_blocks(rows, tokenizer, seed, max_seq_len=max_seq_len), slice_tokens


def load_val_blocks(max_blocks: int = MAX_EVAL_BLOCKS, max_seq_len: int = MAX_LEN):
    files, _ = resolve()
    val_files = sorted(p for p in files if p.name.startswith("val-"))
    rows = orion_corpus.load_samples(val_files)
    tokenizer = orion_corpus.load_bpe_compat()
    return build_blocks(rows, tokenizer, seed=42, max_seq_len=max_seq_len)[:max_blocks]


@torch.no_grad()
def eval_blocks(model, blocks, batch: int = 4):
    """Mean CE loss per token over packed blocks (labels already -100-masked)."""
    model.eval()
    total_loss, total_tok = 0.0, 0
    for i in range(0, len(blocks), batch):
        bs = blocks[i : i + batch]
        ids = torch.stack([x["input_ids"] for x in bs])
        attn = torch.stack([x["attention_mask"] for x in bs])
        labels = torch.stack([x["labels"] for x in bs])
        out = model(input_ids=ids, attention_mask=attn, labels=labels)
        n = int(attn.sum().item())
        total_loss += out.loss.item() * n
        total_tok += n
    if total_tok == 0:
        return float("nan"), 0
    return total_loss / total_tok, total_tok


def corpus_sha() -> str:
    files, _ = resolve()
    return orion_corpus.corpus_sha256(files)
