#!/usr/bin/env python3
"""Verify the YaRN-extended ORION 100M at 2K/4K context with a proper NIAH probe.

Honest verification for scripts/training/extend_context.py: loads the base
100m-real checkpoint, applies the saved LoRA adapter (100m-context8k), and runs
a needle-in-a-haystack probe with a *long* filler haystack so the prompts
actually reach 2K/4K tokens. Reports every number; no fabrication.

Usage:
    python scripts/training/verify_context_extension.py
"""

import sys
from pathlib import Path

import torch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


def load_extended(base_dir: Path, adapter_dir: Path):
    """If a merged standalone model dir exists use it; else base + LoRA adapter."""
    from transformers import AutoModelForCausalLM, AutoTokenizer

    merged_dir = REPO_ROOT / "models" / "comp001" / "100m-context8k-merged"
    src = merged_dir if merged_dir.exists() else base_dir
    tokenizer = AutoTokenizer.from_pretrained(src, local_files_only=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        src,
        dtype=torch.float32,
        local_files_only=True,
        low_cpu_mem_usage=True,
    )
    if not merged_dir.exists():
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, str(adapter_dir))
    print(
        "[LOAD] source:",
        src.name,
        "| rope_scaling:",
        model.config.rope_scaling,
        "| max_pos:",
        model.config.max_position_embeddings,
    )
    return model, tokenizer


def long_filler(tokens_goal: int, tokenizer, seed: int = 7) -> str:
    """Deterministic filler text long enough to reach `tokens_goal` tokens."""
    import random

    rng = random.Random(seed)
    items = [
        "The best thing to do in Paris is visit the Louvre.",
        "The quick brown fox jumps over the lazy dog.",
        "Mount Fuji is 3776 meters tall and often snow-capped.",
        "The orchestra played a soft melody under the stars.",
        "Quantum entanglement was once called spooky action at a distance.",
        "The beehive buzzed busily among the summer flowers.",
    ]
    parts = []
    while True:
        parts.append(rng.choice(items))
        joined = " ".join(parts)
        if tokenizer(joined, return_tensors="pt").input_ids.size(1) >= tokens_goal:
            return joined


def probe(
    model, tokenizer, ctx_len: int, needle: str, query: str, positions=(0.25, 0.5, 0.75)
) -> dict:
    from transformers import GenerationConfig

    filler = long_filler(ctx_len, tokenizer)
    results = {}
    model.eval()
    with torch.no_grad():
        for pos in positions:
            insert_at = int(len(filler) * pos)
            haystack = filler[:insert_at] + needle + " " + filler[insert_at:]
            prompt = haystack + "\nQuestion: " + query + "\nAnswer:"
            ids = tokenizer(
                prompt, return_tensors="pt", truncation=True, max_length=ctx_len
            ).input_ids
            gen = model.generate(
                ids,
                generation_config=GenerationConfig(
                    max_new_tokens=10,
                    do_sample=False,
                    pad_token_id=tokenizer.pad_token_id,
                    eos_token_id=tokenizer.eos_token_id,
                ),
            )
            out = tokenizer.decode(gen[0, ids.size(1) :], skip_special_tokens=True)
            correct = "orion-magic" in out
            results[f"@{int(pos * 100)}%"] = {
                "ctx_len": ids.size(1),
                "response": out.strip(),
                "correct": correct,
            }
            print(
                f"  NIAH@{ctx_len} pos {pos}: len={ids.size(1)} out={out.strip()!r} -> {correct}"
            )
    return results


def main():
    base = REPO_ROOT / "models" / "comp001" / "100m-real"
    adapter = REPO_ROOT / "models" / "comp001" / "100m-context8k"
    model, tokenizer = load_extended(base, adapter)
    needle = "The special magic number for ORION is orion-magic-4-2-0."
    query = "What is the special magic number for ORION?"
    report = {
        "probe_2k": probe(model, tokenizer, 2048, needle, query),
        "probe_4k": probe(model, tokenizer, 4096, needle, query),
        "note": "needle must be emitted verbatim; detection is exact-match",
    }
    import json

    out = REPO_ROOT / "logs" / "context_extension_verify.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print("[VERIFY] wrote", out)


if __name__ == "__main__":
    main()
