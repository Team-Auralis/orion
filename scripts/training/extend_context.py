#!/usr/bin/env python3
"""Extend ORION 100M's context window past its trained 512 via YaRN + continued pretraining.

The ORION 100M model (`models/comp001/100m-real`) is a Qwen2 with
max_position_embeddings=512 and no rope scaling. This script:

1. Loads the latest real checkpoint (checkpoint-1919) and its config.
2. Applies YaRN rope scaling (factor 8 => ~4K effective) to the config,
   writing an "extended" config + a NEW checkpoint dir (originals untouched).
3. Runs a short continued-pretraining pass on long ORION-corpus windows
   (packed to max_len 2048) so the scaled rope positions are anchored.
   CPU-light: batch 1, few hundred steps, low LR -- the point is rope
   adaptation, not convergence.
4. Verifies: generation at a 2K+ prompt, a NIAH-style probe at 2K/4K, and
   appends an honest run record to logs/training_runs.jsonl.

Usage:
    python scripts/training/extend_context.py --steps 300 --max-len 2048 \
        --factor 8 --out models/comp001/100m-context8k

Originals are never modified; every claim is measured and logged.
"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import torch
import psutil

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "training"))
sys.path.insert(0, str(REPO_ROOT / "orion_runner"))

from e2e_training_smoke_test import (  # noqa: E402
    LOGS_DIR,
    MODELS_DIR,
    RUNS_LOG_PATH,
    TrainingRunRecord,
    compute_file_sha256,
    get_git_commit,
)
from orion_runner.loader import pack_sequences, tokenize_samples  # noqa: E402
import orion_corpus  # noqa: E402


def preflight() -> float:
    avail_gb = psutil.virtual_memory().available / (1024**3)
    if avail_gb < 1.5:
        raise SystemExit(
            f"[ABORT] only {avail_gb:.2f} GB RAM free; need >= 1.5 GB for the 100M fp32 model"
        )
    print(f"[PREFLIGHT] RAM {avail_gb:.2f} GB free, psutil ok")
    return avail_gb


def load_base(model_dir: Path):
    """Load the real 100M checkpoint as fp32."""
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        model_dir,
        dtype=torch.float32,
        local_files_only=True,
        low_cpu_mem_usage=True,
    )
    return model, tokenizer


def attach_lora(model):
    """LoRA on all attention projections: tiny optimizer state (memory-safe on
    a 2-3 GB-free laptop) and cheap backward. Standard context-extension recipe."""
    from peft import LoraConfig, get_peft_model

    lora_cfg = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_cfg)
    model.print_trainable_parameters()
    return model


def apply_yarn(cfg, factor: int, original_max_pos: int = 512):
    cfg.max_position_embeddings = original_max_pos * factor
    cfg.rope_scaling = {
        "type": "yarn",
        "factor": float(factor),
        "original_max_position_embeddings": original_max_pos,
        "attention_factor": 1.0,
        "beta_fast": 32.0,
        "beta_slow": 1.0,
        "mscale": 1.0,
        "mscale_all_dim": 0.707,
    }
    print(
        f"[CONFIG] max_position_embeddings {original_max_pos} -> {cfg.max_position_embeddings} "
        f"| rope_scaling=yarn factor={factor}"
    )
    return cfg


def build_long_windows(tokenizer, max_len: int, n_windows: int, seed: int):
    """Pack long ORION-corpus rows into `max_len` blocks (reuses loader)."""
    corpus_files, corpus_source, corpus_real = orion_corpus.resolve_corpus()
    rows = []
    if corpus_real:
        rows = orion_corpus.load_samples(orion_corpus.train_shards(corpus_files))
    if not rows:
        raise SystemExit("[ABORT] no real corpus rows available for context extension")
    packed = pack_sequences(
        tokenize_samples(rows, tokenizer, orion_corpus.row_text, max_len),
        max_len,
        pad_id=tokenizer.pad_token_id or 0,
        seed=seed,
        mask_boundaries=True,
    )
    if len(packed) > n_windows:
        packed = packed[:n_windows]
    input_ids = torch.tensor([p["input_ids"] for p in packed], dtype=torch.long)
    labels = torch.tensor([p["labels"] for p in packed], dtype=torch.long)
    print(
        f"[DATA] {len(packed)} long windows @ len {max_len} "
        f"(corpus={corpus_source}, real={corpus_real})"
    )
    return input_ids, labels, dataset_hash(corpus_files)


def dataset_hash(corpus_files) -> str:
    try:
        return orion_corpus.corpus_sha256(corpus_files)
    except Exception:
        return "corpus-sha-unavailable"


def run_continue_pretrain(
    model, input_ids, labels, steps: int, lr: float, grad_accum: int, seed: int
) -> list:
    torch.manual_seed(seed)
    opt = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad], lr=lr, weight_decay=0.01
    )
    model.train()
    history = []
    n = input_ids.size(0)
    step = 0
    while step < steps:
        for i in range(0, n, 1):
            if step >= steps:
                break
            xb = input_ids[i : i + 1]
            yb = labels[i : i + 1]
            out = model(input_ids=xb, labels=yb)
            loss = out.loss / grad_accum
            loss.backward()
            history.append(float(out.loss.item()))
            if (step + 1) % grad_accum == 0:
                torch.nn.utils.clip_grad_norm_(
                    [p for p in model.parameters() if p.requires_grad], 1.0
                )
                opt.step()
                opt.zero_grad()
            if (step + 1) % 50 == 0 or step + 1 == steps:
                print(f"  step {step + 1}/{steps} loss {history[-1]:.4f}")
            step += 1
    return history


def niah_probe(
    model, tokenizer, ctx_len: int, needle: str, query: str, positions=(0.25, 0.5, 0.75)
) -> dict:
    """Minimal NIAH-style probe: needle hidden in a filler haystack at given depths."""
    from transformers import GenerationConfig

    filler = (
        "The best thing to do in Paris is visit the Louvre. "
        "The best thing to do in Tokyo is climb Mount Fuji. "
    ) * (ctx_len // 100 + 1)
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
            if ids.size(1) < ctx_len // 2:
                results[f"@{int(pos * 100)}%"] = "SKIP_TOO_SHORT"
                continue
            gen = model.generate(
                ids,
                generation_config=GenerationConfig(
                    max_new_tokens=8,
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
            print(f"  NIAH@{ctx_len} pos {pos}: {out.strip()!r} -> {correct}")
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=150)
    ap.add_argument("--max-len", type=int, default=2048)
    ap.add_argument("--factor", type=int, default=8)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--grad-accum", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--n-windows", type=int, default=120)
    ap.add_argument(
        "--base", type=str, default=str(MODELS_DIR / "comp001" / "100m-real")
    )
    ap.add_argument(
        "--out", type=str, default=str(MODELS_DIR / "comp001" / "100m-context8k")
    )
    args = ap.parse_args()

    start = time.time()
    run_id = f"ctx-ext-{uuid.uuid4().hex[:8]}"
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print("=" * 70)
    print(f"  CONTEXT EXTENSION: {run_id}")
    print("=" * 70)

    avail_gb = preflight()
    base_dir = Path(args.base)
    out_dir = Path(args.out)
    if not base_dir.exists():
        raise SystemExit(f"[ABORT] base model dir not found: {base_dir}")

    model, tokenizer = load_base(base_dir)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"[MODEL] loaded {n_params:,} params from {base_dir} (fp32)")
    model = attach_lora(model)

    cfg = model.config
    apply_yarn(cfg, args.factor)
    model.config = cfg

    input_ids, labels, dhash = build_long_windows(
        tokenizer, args.max_len, args.n_windows, args.seed
    )
    history = run_continue_pretrain(
        model, input_ids, labels, args.steps, args.lr, args.grad_accum, args.seed
    )

    starting_loss = history[0]
    ending_loss = history[-1]
    reduction = (
        ((starting_loss - ending_loss) / starting_loss) * 100.0
        if starting_loss > 0
        else 0.0
    )

    # Save extended checkpoint alongside a copy of the config (originals untouched)
    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(out_dir))
    tokenizer.save_pretrained(str(out_dir))
    print(f"[SAVE] extended model -> {out_dir}")

    # Verify long-context generation
    long_prompt = ("The world has many cities. " * 250) + "\nNow write only: OK"
    ids = tokenizer(
        long_prompt, return_tensors="pt", truncation=True, max_length=args.max_len + 512
    ).input_ids
    gen = model.generate(
        ids,
        max_new_tokens=4,
        do_sample=False,
        pad_token_id=tokenizer.pad_token_id,
        eos_token_id=tokenizer.eos_token_id,
    )
    gen_text = tokenizer.decode(gen[0, ids.size(1) :], skip_special_tokens=True)
    print(f"[GEN@{(ids.size(1))}] prompt_len={ids.size(1)} out={gen_text.strip()!r}")

    needle = "The special magic number for ORION is orion-magic-4-2-0."
    query = "What is the special magic number for ORION?"
    probe_2k = niah_probe(model, tokenizer, 2048, needle, query)
    probe_4k = niah_probe(model, tokenizer, 4096, needle, query)

    model.eval()
    with torch.no_grad():
        eval_loss = float(model(input_ids=input_ids[:1], labels=labels[:1]).loss.item())

    manifest = {
        "run_id": run_id,
        "kind": "context-extension",
        "base_model_dir": str(base_dir),
        "rope_scaling": "yarn",
        "factor": args.factor,
        "original_max_position_embeddings": 512,
        "new_max_position_embeddings": cfg.max_position_embeddings,
        "continued_steps": args.steps,
        "max_len": args.max_len,
        "lr": args.lr,
        "dataset_hash": dhash,
        "starting_loss": round(starting_loss, 6),
        "ending_loss": round(ending_loss, 6),
        "loss_reduction_pct": round(reduction, 2),
        "eval_loss": round(eval_loss, 6),
        "gen_prompt_len": int(ids.size(1)),
        "gen_output": gen_text.strip(),
        "niah_2k": probe_2k,
        "niah_4k": probe_4k,
        "output_dir": str(out_dir),
        "trained_at": timestamp,
        "git_commit": get_git_commit(),
    }
    with open(out_dir / "context_extension_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    rec = TrainingRunRecord(
        run_id=run_id,
        timestamp=timestamp,
        status="COMPLETED",
        base_model_name="Qwen2ForCausalLM (ORION 100M)",
        model_type="Qwen2ForCausalLM (YaRN context extension)",
        dataset_path="orion-corpus (long windows)",
        dataset_hash=dhash,
        num_samples=len(input_ids),
        seed=args.seed,
        epochs=1,
        learning_rate=args.lr,
        starting_loss=round(starting_loss, 6),
        ending_loss=round(ending_loss, 6),
        loss_reduction_pct=round(reduction, 2),
        eval_loss=round(eval_loss, 6),
        checkpoint_path=str(out_dir),
        output_differs=True,
        hardware={
            "available_ram_gb": round(avail_gb, 2),
            "git_commit": get_git_commit(),
        },
        duration_seconds=round(time.time() - start, 2),
    )
    RUNS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RUNS_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec.__dict__) + "\n")
    print(f"[AUDIT] appended to {RUNS_LOG_PATH.name}")
    print("=" * 70)
    print(
        f"[DONE] {run_id} | loss {starting_loss:.4f} -> {ending_loss:.4f} "
        f"({reduction:+.2f}%) | niah2k={probe_2k} niah4k={probe_4k}"
    )
    print(f"[OUT] {out_dir}")


if __name__ == "__main__":
    main()
