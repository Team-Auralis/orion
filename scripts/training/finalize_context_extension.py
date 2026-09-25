#!/usr/bin/env python3
"""Fix the context-extension checkpoint usability bug.

extend_context.py saved a LoRA adapter WITHOUT the YaRN config (peft stores
only adapter metadata; model.config changes are lost). This script produces
the intended artifact: a standalone ORION 100M model with YaRN rope scaling
baked into config.json and the LoRA merged into the weights.

    python scripts/training/finalize_context_extension.py \
        --base models/comp001/100m-real \
        --adapter models/comp001/100m-context8k \
        --out models/comp001/100m-context8k-merged
"""

import argparse
import json
import sys
from pathlib import Path

import torch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--base", type=str, default=str(REPO_ROOT / "models" / "comp001" / "100m-real")
    )
    ap.add_argument(
        "--adapter",
        type=str,
        default=str(REPO_ROOT / "models" / "comp001" / "100m-context8k"),
    )
    ap.add_argument(
        "--out",
        type=str,
        default=str(REPO_ROOT / "models" / "comp001" / "100m-context8k-merged"),
    )
    ap.add_argument("--factor", type=int, default=8)
    args = ap.parse_args()

    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    base_dir, adapter_dir, out_dir = Path(args.base), Path(args.adapter), Path(args.out)
    tokenizer = AutoTokenizer.from_pretrained(base_dir, local_files_only=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    base = AutoModelForCausalLM.from_pretrained(
        base_dir, dtype=torch.float32, local_files_only=True, low_cpu_mem_usage=True
    )
    print(f"[LOAD] base {base_dir.name} | adapter {adapter_dir.name}")
    model = PeftModel.from_pretrained(base, str(adapter_dir))
    print("[MERGE] folding LoRA into base weights...")
    merged = model.merge_and_unload()

    # Bake YaRN config into the merged model and persist it
    cfg = merged.config
    cfg.max_position_embeddings = 512 * args.factor
    cfg.rope_scaling = {
        "type": "yarn",
        "factor": float(args.factor),
        "original_max_position_embeddings": 512,
        "attention_factor": 1.0,
        "beta_fast": 32.0,
        "beta_slow": 1.0,
        "mscale": 1.0,
        "mscale_all_dim": 0.707,
    }
    merged.config = cfg
    out_dir.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(str(out_dir))
    tokenizer.save_pretrained(str(out_dir))

    # Verify persisted config round-trips
    with open(out_dir / "config.json", "r", encoding="utf-8") as f:
        saved_cfg = json.load(f)
    assert saved_cfg.get("rope_scaling", {}).get("type") == "yarn", saved_cfg
    assert saved_cfg["max_position_embeddings"] == 512 * args.factor, saved_cfg
    print(f"[OK] saved standalone YaRN model -> {out_dir}")
    print(
        f"     rope_scaling={saved_cfg['rope_scaling']['type']} "
        f"max_pos={saved_cfg['max_position_embeddings']}"
    )


if __name__ == "__main__":
    main()
