"""ORION Runner - organic sample batching.

The packing idea is inspired by higgsfield's LlamaLoader
(https://github.com/higgsfield-ai/higgsfield, Apache-2.0 - see THIRD_PARTY.md),
which packs many short samples into maximally filled blocks instead of wasting
tokens on padding. `pack_sequences` is ORION's native adaptation: it consumes
token id sequences, greedily packs as many as fit into blocks of `max_len`,
emits attention masks and -100-masked labels at padding and (optionally) at
sample boundaries.
"""
import random
from typing import Dict, List, Optional


def tokenize_samples(rows: List[dict], tokenizer, format_fn, max_len: int,
                     truncation: bool = True) -> List[Dict]:
    """Tokenize a list of rows with a HF tokenizer into id sequences."""
    texts = [format_fn(row) for row in rows]
    enc = tokenizer(texts, truncation=truncation, max_length=max_len)
    return [
        {"input_ids": list(ids), "attention_mask": list(mask)}
        for ids, mask in zip(enc["input_ids"], enc["attention_mask"])
    ]


def pack_sequences(samples: List[Dict], max_len: int, pad_id: int = 0,
                   seed: Optional[int] = None, mask_boundaries: bool = True,
                   pad_to_max: bool = True) -> List[Dict]:
    """Greedily pack sample sequences into blocks no longer than `max_len`.

    Each returned block contains input_ids / attention_mask / labels of length
    `max_len` (or of the last-incomplete length when `pad_to_max` is False).
    Labels mask padding with -100 and, when `mask_boundaries` is True, also
    mask the first token of each packed sample so no cross-sample credit is
    taken.
    """
    rng = random.Random(seed)
    items = [dict(s) for s in samples]
    if seed is not None:
        rng.shuffle(items)

    blocks = []
    for item in items:
        ids = list(item.get("input_ids", []))[:max_len]
        ids = ids or [pad_id]
        if blocks and len(blocks[-1]["ids"]) + len(ids) <= max_len:
            boundary = len(blocks[-1]["ids"])
            blocks[-1]["ids"] += ids
            if mask_boundaries:
                blocks[-1]["boundaries"].append(boundary)
        else:
            if blocks:
                add = max_len - len(blocks[-1]["ids"])
                if add:
                    blocks[-1]["ids"] += [pad_id] * add
            blocks.append({
                "ids": list(ids),
                "boundaries": [0] if mask_boundaries else [],
            })

    if blocks and pad_to_max:
        add = max_len - len(blocks[-1]["ids"])
        if add:
            blocks[-1]["ids"] += [pad_id] * add

    packed = []
    for block in blocks:
        ids = block["ids"][:max_len]
        labels = list(ids)
        attention = []
        for token in ids:
            attention.append(0 if token == pad_id else 1)
        for i, token in enumerate(labels):
            if token == pad_id:
                labels[i] = -100
        if mask_boundaries:
            for b in block["boundaries"]:
                if 0 <= b < len(labels):
                    labels[b] = -100
        packed.append({
            "input_ids": ids,
            "attention_mask": attention,
            "labels": labels,
        })
    return packed