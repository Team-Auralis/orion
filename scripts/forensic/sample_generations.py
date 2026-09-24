#!/usr/bin/env python3
"""F5 qualitative generation diagnostics for checkpoint-1919.

Ten prompts: 5 in-domain corpus-prefix prompts (first 32 BPE tokens of the
first 5 rows of train-fw-part-00000) + 5 out-of-domain prompts (ORION eval
set). Greedy decoding (do_sample=False, temperature unused), max 32 new
tokens.

QUALITATIVE DIAGNOSTICS ONLY. These samples show what the model emits; they
are NOT capability evidence. Small checkpoint, held-out probes, greedy
decoding - do not draw capability conclusions from them.

Output: logs/forensic/generations.txt
"""

from __future__ import annotations

import gc
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import psutil  # noqa: E402
import torch  # noqa: E402

from scripts.forensic.eval_suite import (  # noqa: E402
    load_model_from_checkpoint,
    load_tokenizer,
)
from scripts.forensic.orion_eval_set import ORION_ITEMS  # noqa: E402
from scripts.training.orion_corpus import row_text  # noqa: E402

CKPT_DIR = REPO_ROOT / "models" / "comp001" / "100m-real" / "checkpoint-1919"
CORPUS_DIR = REPO_ROOT / "data" / "training" / "corpus"
OUT_TXT = REPO_ROOT / "logs" / "forensic" / "generations.txt"
PAD_ID, EOS_ID = 0, 2
MAX_NEW = 32


def gen(model, tokenizer, prompt_ids) -> list[int]:
    with torch.no_grad():
        out = model.generate(
            input_ids=torch.tensor([prompt_ids], dtype=torch.long),
            max_new_tokens=MAX_NEW,
            do_sample=False,  # greedy, temperature 0
            pad_token_id=PAD_ID,
            eos_token_id=EOS_ID,
        )
    return out[0, len(prompt_ids):].tolist()


def main() -> int:
    torch.set_num_threads(6)
    model, cfg, step, _l, n_params, note = load_model_from_checkpoint(CKPT_DIR)
    tokenizer = load_tokenizer()

    # in-domain: first 32 BPE tokens of the first 5 FineWeb-Edu rows
    in_prompts = []
    count = 0
    with open(CORPUS_DIR / "train-fw-part-00000.jsonl", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            text = row_text(json.loads(line))
            ids = tokenizer.encode(text).ids[:32]
            in_prompts.append(
                {"label": "in-domain corpus prefix",
                 "prompt": tokenizer.decode(ids, skip_special_tokens=True)}
            )
            count += 1
            if count >= 5:
                break

    # out-of-domain: ORION eval set completions
    out_prompts = [
        {"label": "out-of-domain ORION set", "prompt": it["prompt"]}
        for it in ORION_ITEMS
        if it["kind"] == "completion"
    ][:5]

    blocks = []
    for pr in in_prompts + out_prompts:
        ids = tokenizer.encode(pr["prompt"]).ids[:512]
        gen_ids = gen(model, tokenizer, ids)
        text = tokenizer.decode(gen_ids, skip_special_tokens=True)
        blocks.append({"label": pr["label"], "prompt": pr["prompt"],
                       "continuation": text, "new_tokens": len(gen_ids)})

    del model
    gc.collect()

    lines = [
        "ORION 100m-real checkpoint-1919 - QUALITATIVE GENERATION DIAGNOSTICS",
        "=" * 78,
        "WARNING: these samples are QUALITATIVE DIAGNOSTICS ONLY and are NOT",
        "capability evidence. The checkpoint is a 110M-param model trained on a",
        "small corpus; prompts are held-out or corpus-prefix probes and decoding",
        "is greedy (temperature 0, max 32 new tokens). Nothing here should be",
        "read as a claim about general knowledge, fluency, or capability.",
        "-" * 78,
        f"timestamp: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        f"checkpoint: {CKPT_DIR} (step {step}, {n_params:,} params)",
        f"load: {note}",
        "",
    ]
    for i, b in enumerate(blocks, 1):
        lines += [
            f"=== sample {i} [{b['label']}] ===",
            f"PROMPT: {b['prompt']}",
            f"CONTINUATION ({b['new_tokens']} new tokens): {b['continuation']}",
            "",
        ]
    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OUT] wrote {OUT_TXT}")
    for i, b in enumerate(blocks, 1):
        print(f"  {i:2d} [{b['label']}] {b['prompt'][:60]!r} -> {b['continuation'][:60]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())