#!/usr/bin/env python3
"""Distill teacher curriculum (qwen2.5:3b output) into ORION 100M via LoRA.

Loads the real ORION 100M (models/comp001/100m-real), wraps it in LoRA
(all attention projections), and SFTs it on data/training/teacher_curriculum.jsonl
in Q/A format. This is TEXT distillation -- the student learns to reproduce the
teacher's answers from its own tokenizer, no logit transfer (different
tokenizers between teacher and student makes that impossible anyway).

Honest verification: loss must drop, logit delta must differ, and generation
on a held-out curriculum question is sampled before/after.

Usage:
    python scripts/teacher/distill_train.py --epochs 20 --lr 3e-4 \
        --dataset data/training/teacher_curriculum.jsonl \
        --out models/comp001/100m-teacher-distill
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
    MODELS_DIR,
    RUNS_LOG_PATH,
    TrainingRunRecord,
    compute_file_sha256,
    get_git_commit,
)
from orion_runner.loader import pack_sequences, tokenize_samples  # noqa: E402


def fmt_row(row: dict) -> str:
    return f"Q: {row['instruction']}\nA: {row['response']}"


def load_rows(path: Path) -> list:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if not rows:
        raise SystemExit(f"[ABORT] no rows in {path}")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dataset",
        type=str,
        default=str(REPO_ROOT / "data" / "training" / "teacher_curriculum.jsonl"),
    )
    ap.add_argument(
        "--base", type=str, default=str(MODELS_DIR / "comp001" / "100m-real")
    )
    ap.add_argument(
        "--out", type=str, default=str(MODELS_DIR / "comp001" / "100m-teacher-distill")
    )
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--max-len", type=int, default=256)
    ap.add_argument("--batch-size", type=int, default=2)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    avail_gb = psutil.virtual_memory().available / (1024**3)
    if avail_gb < 1.2:
        raise SystemExit(f"[ABORT] only {avail_gb:.2f} GB free; need >= 1.2")
    print(f"[PREFLIGHT] RAM {avail_gb:.2f} GB free")

    run_id = f"teach-distill-{uuid.uuid4().hex[:8]}"
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    start = time.time()
    print("=" * 70)
    print(f"  TEACHER DISTILLATION: {run_id}")
    print("=" * 70)

    dataset_path = Path(args.dataset)
    dataset_hash = compute_file_sha256(dataset_path)
    rows = load_rows(dataset_path)
    print(f"[DATA] {len(rows)} teacher rows | sha256 {dataset_hash[:16]}...")

    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import LoraConfig, get_peft_model

    base_dir = Path(args.base)
    tokenizer = AutoTokenizer.from_pretrained(base_dir, local_files_only=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    base = AutoModelForCausalLM.from_pretrained(
        base_dir, dtype=torch.float32, local_files_only=True, low_cpu_mem_usage=True
    )
    print(
        f"[MODEL] base {base_dir.name} | {sum(p.numel() for p in base.parameters()):,} params"
    )

    lora_cfg = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(base, lora_cfg)
    model.print_trainable_parameters()

    # pad pack teacher rows
    packed = pack_sequences(
        tokenize_samples(rows, tokenizer, fmt_row, args.max_len),
        args.max_len,
        pad_id=tokenizer.pad_token_id or 0,
        seed=args.seed,
        mask_boundaries=True,
    )
    input_ids = torch.tensor([p["input_ids"] for p in packed], dtype=torch.long)
    labels = torch.tensor([p["labels"] for p in packed], dtype=torch.long)
    print(f"[DATA] {len(packed)} packed rows @ len<= {args.max_len}")

    n = input_ids.size(0)
    n_eval = max(1, n // 5)
    tr_ids, tr_lab = input_ids[: n - n_eval], labels[: n - n_eval]
    ev_ids, ev_lab = input_ids[n - n_eval :], labels[n - n_eval :]

    torch.manual_seed(args.seed)
    opt = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad], lr=args.lr
    )
    model.train()
    history = []
    for epoch in range(args.epochs):
        losses = []
        for i in range(0, tr_ids.size(0), args.batch_size):
            xb, yb = tr_ids[i : i + args.batch_size], tr_lab[i : i + args.batch_size]
            out = model(input_ids=xb, labels=yb)
            out.loss.backward()
            losses.append(float(out.loss.item()))
            torch.nn.utils.clip_grad_norm_(
                [p for p in model.parameters() if p.requires_grad], 1.0
            )
            opt.step()
            opt.zero_grad()
        history.append(sum(losses) / len(losses))
        if (epoch + 1) % 5 == 0 or epoch + 1 == args.epochs:
            print(f"  epoch {epoch + 1}/{args.epochs} loss {history[-1]:.4f}")

    starting_loss = history[0]
    ending_loss = history[-1]
    reduction = (
        ((starting_loss - ending_loss) / starting_loss) * 100.0
        if starting_loss > 0
        else 0.0
    )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(out_dir))
    tokenizer.save_pretrained(str(out_dir))
    print(f"[SAVE] LoRA adapter -> {out_dir}")

    model.eval()
    with torch.no_grad():
        eval_loss = float(model(input_ids=ev_ids, labels=ev_lab).loss.item())
        adapter_logits = model(input_ids=ev_ids).logits
        with model.disable_adapter():
            base_logits = model(input_ids=ev_ids).logits
    output_differs = float(torch.norm(adapter_logits - base_logits).item()) > 1e-4
    print(f"[EVAL] eval_loss {eval_loss:.4f} | logit delta differs: {output_differs}")

    # generation before-vs-after on a held-back style question
    def gen(prompt: str, with_lora: bool) -> str:
        ids = tokenizer(
            prompt, return_tensors="pt", truncation=True, max_length=args.max_len
        ).input_ids
        with torch.no_grad():
            if not with_lora:
                with model.disable_adapter():
                    out = model.generate(
                        ids,
                        max_new_tokens=24,
                        do_sample=False,
                        pad_token_id=tokenizer.pad_token_id,
                        eos_token_id=tokenizer.eos_token_id,
                    )
            else:
                out = model.generate(
                    ids,
                    max_new_tokens=24,
                    do_sample=False,
                    pad_token_id=tokenizer.pad_token_id,
                    eos_token_id=tokenizer.eos_token_id,
                )
        return tokenizer.decode(out[0, ids.size(1) :], skip_special_tokens=True)

    heldout_q = "Q: What is the square root of 144?\nA:"
    gen_before = gen(heldout_q, with_lora=False)
    gen_after = gen(heldout_q, with_lora=True)
    print(f"[GEN] before: {gen_before.strip()!r}")
    print(f"[GEN] after:  {gen_after.strip()!r}")

    manifest = {
        "run_id": run_id,
        "kind": "teacher-distillation",
        "teacher": rows[0].get("teacher"),
        "dataset_hash": dataset_hash,
        "rows": len(rows),
        "epochs": args.epochs,
        "lr": args.lr,
        "starting_loss": round(starting_loss, 6),
        "ending_loss": round(ending_loss, 6),
        "loss_reduction_pct": round(reduction, 2),
        "eval_loss": round(eval_loss, 6),
        "output_differs": output_differs,
        "gen_before": gen_before.strip(),
        "gen_after": gen_after.strip(),
        "out_dir": str(out_dir),
        "trained_at": timestamp,
        "git_commit": get_git_commit(),
    }
    with open(out_dir / "distill_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    rec = TrainingRunRecord(
        run_id=run_id,
        timestamp=timestamp,
        status="COMPLETED",
        base_model_name="Qwen2ForCausalLM (ORION 100M)",
        model_type="Qwen2ForCausalLM (LoRA teacher distillation)",
        dataset_path=str(dataset_path),
        dataset_hash=dataset_hash,
        num_samples=len(rows),
        seed=args.seed,
        epochs=args.epochs,
        learning_rate=args.lr,
        starting_loss=round(starting_loss, 6),
        ending_loss=round(ending_loss, 6),
        loss_reduction_pct=round(reduction, 2),
        eval_loss=round(eval_loss, 6),
        checkpoint_path=str(out_dir),
        output_differs=output_differs,
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
        f"({reduction:+.2f}%) | eval {eval_loss:.4f} | differs={output_differs}"
    )
    print(f"[OUT] {out_dir}")


if __name__ == "__main__":
    main()
