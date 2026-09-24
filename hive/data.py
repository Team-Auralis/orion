"""Corpus slice + block building, shared identically by coordinator and workers.

Every process builds the SAME deterministic block list from the same train-*
shard slice (orion_corpus + orion_runner.loader, fixed seeds), so block
indices handed out by the coordinator line up in every worker. Each worker
keeps its own copy in memory - in the sim every "device" reads the fleet data
from its local store, exactly like a real device would read its own disk.
"""

import json
import sys
from pathlib import Path

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


def load_train_rows(budget: int):
    """Rows from train-* shards until `budget` corpus tokens are consumed."""
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


def build_blocks(rows, tokenizer, seed: int):
    """Packed 512-token blocks with attention-mask token counts, deterministic."""
    samples = tokenize_samples(
        rows, tokenizer, orion_corpus.row_text, max_len=MAX_LEN, truncation=True
    )
    packed = pack_sequences(
        samples,
        max_len=MAX_LEN,
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


def load_train_blocks(budget: int, seed: int):
    rows, slice_tokens, tokenizer = load_train_rows(budget)
    return build_blocks(rows, tokenizer, seed), slice_tokens


def load_val_blocks(max_blocks: int = MAX_EVAL_BLOCKS):
    files, _ = resolve()
    val_files = sorted(p for p in files if p.name.startswith("val-"))
    rows = orion_corpus.load_samples(val_files)
    tokenizer = orion_corpus.load_bpe_compat()
    return build_blocks(rows, tokenizer, seed=42)[:max_blocks]


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
