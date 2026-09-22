#!/usr/bin/env python3
"""Train the custom ORION model (LoRA SFT on the local Qwen2 0.5B base).

Builds on the verified engine in e2e_training_smoke_test.py (same record
schema + audit log, so tests stay green) but trains on the ORION curriculum
built by orion_dataset.py.

Usage (CPU, 12 threads):
    python scripts/training/orion_train.py --dataset data/training/orion_dataset.jsonl \
        --epochs 3 --lr 2e-3 --seed 42 [--merge data/training/orion_merged]

--surrogate trains the architectural miniature instead of the real 0.5B
(used for fast verification and for machines with less than ~2.6 GB free RAM).
"""

import argparse
import json
import shutil
import sys
import time
import uuid
import zlib
from pathlib import Path

import torch
import psutil

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "training"))

from e2e_training_smoke_test import (  # noqa: E402
    LOGS_DIR,
    MODELS_DIR,
    RUNS_LOG_PATH,
    TrainingRunRecord,
    compute_file_sha256,
    get_git_commit,
)
from orion_runner import experiment, param, run_experiment  # noqa: E402
from orion_runner.loader import pack_sequences, tokenize_samples  # noqa: E402

MODEL_DIR = MODELS_DIR / "qwen_instruct"


def preflight() -> tuple:
    vmem = psutil.virtual_memory()
    avail_gb = vmem.available / (1024**3)
    return avail_gb, {
        "cpu_cores": psutil.cpu_count(logical=False),
        "cpu_threads": psutil.cpu_count(logical=True),
        "total_ram_gb": round(vmem.total / (1024**3), 2),
        "available_ram_gb": round(avail_gb, 2),
        "git_commit": get_git_commit(),
        "torch_version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
    }


def load_dataset(path: Path) -> list:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def format_sample(s: dict) -> str:
    return f"INSTRUCTION: {s['instruction']}\nRESPONSE: {s['response']}"


def run_orion_training(
    dataset_path: Path,
    epochs: int = 3,
    lr: float = 2e-3,
    seed: int = 42,
    checkpoint_dir: Path = None,
    surrogate: bool = False,
    merge_dir: Path = None,
    max_len: int = 384,
    batch_size: int = 2,
    grad_accum: int = 4,
    use_packing: bool = False,
) -> TrainingRunRecord:
    start = time.time()
    run_id = f"orion-train-{uuid.uuid4().hex[:8]}"
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print("=" * 70)
    print(f"  ORION CUSTOM MODEL TRAIN: {run_id}")
    print("=" * 70)

    avail_gb, hardware = preflight()
    print(f"[STAGE 0: PREFLIGHT] RAM {avail_gb:.2f} GB free")

    dataset_hash = compute_file_sha256(dataset_path)
    rows = load_dataset(dataset_path)
    print(f"[STAGE 1: DATA] {len(rows)} samples | sha256 {dataset_hash[:16]}...")

    torch.manual_seed(seed)
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        Qwen2Config,
        Qwen2ForCausalLM,
    )
    from peft import LoraConfig, get_peft_model

    use_real = not surrogate and avail_gb >= 2.6 and MODEL_DIR.exists()
    if surrogate:
        print("[STAGE 2: MODEL] architectural surrogate (verification mode)")
        cfg = Qwen2Config(
            vocab_size=1000,
            hidden_size=64,
            intermediate_size=128,
            num_hidden_layers=2,
            num_attention_heads=2,
            num_key_value_heads=2,
            max_position_embeddings=512,
            pad_token_id=0,
            bos_token_id=1,
            eos_token_id=2,
        )
        base = Qwen2ForCausalLM(cfg)
        tokenizer = None
        base_name = "qwen2-architectural-surrogate"
    elif use_real:
        print(f"[STAGE 2: MODEL] loading real 0.5B from {MODEL_DIR}")
        tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR, local_files_only=True)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        base = AutoModelForCausalLM.from_pretrained(
            MODEL_DIR,
            torch_dtype=torch.float32,
            local_files_only=True,
            low_cpu_mem_usage=True,
        )
        base_name = "qwen2:0.5b-local"
    else:
        print(
            "[STAGE 2: MODEL] RAM too low for 0.5B backprop - falling back to surrogate"
        )
        return run_orion_training(
            dataset_path,
            epochs,
            lr,
            seed,
            checkpoint_dir,
            surrogate=True,
            merge_dir=None,
            max_len=max_len,
            batch_size=batch_size,
            grad_accum=grad_accum,
        )

    lora_cfg = LoraConfig(
        r=8,
        lora_alpha=16,
        target_modules=["q_proj", "v_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(base, lora_cfg)
    model.print_trainable_parameters()

    texts = [format_sample(s) for s in rows]
    if tokenizer is not None:
        if use_packing:
            packed = pack_sequences(
                tokenize_samples(rows, tokenizer, format_sample, max_len),
                max_len,
                pad_id=tokenizer.pad_token_id or 0,
                seed=seed,
                mask_boundaries=True,
            )
            input_ids = torch.tensor([p["input_ids"] for p in packed], dtype=torch.long)
            labels = torch.tensor([p["labels"] for p in packed], dtype=torch.long)
            print(
                f"[STAGE 2: PACKING] {len(packed)} packed blocks "
                f"(max_len {max_len}, cross-sample labels masked)"
            )
        else:
            enc = tokenizer(
                texts,
                padding=True,
                truncation=True,
                max_length=max_len,
                return_tensors="pt",
            )
            input_ids, labels = enc["input_ids"], enc["input_ids"].clone()
            labels[labels == tokenizer.pad_token_id] = -100
    else:
        tokens = []
        for s in rows:
            combined = format_sample(s)
            ids = (
                [1] + [zlib.crc32(w.encode()) % 990 + 3 for w in combined.split()] + [2]
            )
            tokens.append(ids[:max_len])
        maxlen = max(len(t) for t in tokens)
        padded = [t + [0] * (maxlen - len(t)) for t in tokens]
        input_ids = torch.tensor(padded, dtype=torch.long)
        labels = input_ids.clone()
        labels[labels == 0] = -100

    n = input_ids.size(0)
    n_eval = min(4, n // 4)
    train_ids, train_labels = input_ids[: n - n_eval], labels[: n - n_eval]
    eval_ids, eval_labels = input_ids[n - n_eval :], labels[n - n_eval :]

    print(
        f"[STAGE 3: TRAIN SPLIT] {train_ids.size(0)} train / {n_eval} eval, "
        f"seq<= {input_ids.size(1)}"
    )

    optimizer = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad], lr=lr
    )
    model.train()
    history = []
    for epoch in range(epochs):
        model.zero_grad()
        losses = []
        for i in range(0, train_ids.size(0), batch_size):
            xb = train_ids[i : i + batch_size]
            yb = train_labels[i : i + batch_size]
            out = model(input_ids=xb, labels=yb)
            loss = out.loss / grad_accum
            loss.backward()
            losses.append(float(out.loss.item()))
            if (i // batch_size + 1) % grad_accum == 0:
                torch.nn.utils.clip_grad_norm_(
                    [p for p in model.parameters() if p.requires_grad], 1.0
                )
                optimizer.step()
                optimizer.zero_grad()
        history.append(sum(losses) / len(losses))
        print(f"  Epoch {epoch + 1}/{epochs} - mean loss: {history[-1]:.4f}")

    starting_loss = history[0]
    ending_loss = history[-1]
    reduction = (
        ((starting_loss - ending_loss) / starting_loss) * 100.0
        if starting_loss > 0
        else 0.0
    )
    print(
        f"  Loss trajectory: {starting_loss:.4f} -> {ending_loss:.4f} ({reduction:+.2f}%)"
    )

    if checkpoint_dir is None:
        checkpoint_dir = MODELS_DIR / "checkpoints" / run_id
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(checkpoint_dir))
    print(f"[STAGE 4: CHECKPOINT] LoRA adapter -> {checkpoint_dir}")

    model.eval()
    with torch.no_grad():
        eval_loss = float(model(input_ids=eval_ids, labels=eval_labels).loss.item())
        with model.disable_adapter():
            base_logits = model(input_ids=eval_ids).logits
        adapter_logits = model(input_ids=eval_ids).logits
    output_differs = float(torch.norm(adapter_logits - base_logits).item()) > 1e-4
    print(
        f"[STAGE 5: EVAL] eval_loss {eval_loss:.4f} | logit delta differs: {output_differs}"
    )

    saved_merge_dir = ""
    if merge_dir is not None:
        if tokenizer is None:
            print("[STAGE 6: MERGE] skip merge (surrogate has no tokenizer)")
        else:
            saved_merge_dir = _merge_adapter(model, Path(merge_dir), tokenizer)
            print(f"[STAGE 6: MERGE] merged model -> {saved_merge_dir}")

    manifest = {
        "run_id": run_id,
        "base_model": base_name,
        "adapter_type": "LoRA",
        "rank": 8,
        "alpha": 16,
        "target_modules": ["q_proj", "v_proj"],
        "dataset_hash": dataset_hash,
        "dataset_samples": len(rows),
        "trained_at": timestamp,
        "compatible_runtime": "peft / transformers / llama.cpp (with convert_lora_to_gguf.py)",
        "verified": reduction > 0 and output_differs,
    }
    with open(checkpoint_dir / "deployment_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    record = TrainingRunRecord(
        run_id=run_id,
        timestamp=timestamp,
        status="COMPLETED",
        base_model_name=base_name,
        model_type="Qwen2ForCausalLM (plus task_type CAUSAL_LM)",
        dataset_path=str(dataset_path),
        dataset_hash=dataset_hash,
        num_samples=len(rows),
        seed=seed,
        epochs=epochs,
        learning_rate=lr,
        starting_loss=round(starting_loss, 6),
        ending_loss=round(ending_loss, 6),
        loss_reduction_pct=round(reduction, 2),
        eval_loss=round(eval_loss, 6),
        checkpoint_path=str(checkpoint_dir),
        output_differs=output_differs,
        hardware=hardware,
        duration_seconds=round(time.time() - start, 2),
    )
    RUNS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RUNS_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record.__dict__) + "\n")
    print(f"[STAGE 7: AUDIT] appended to {RUNS_LOG_PATH.name}")
    print("=" * 70)
    print(
        f"[SUCCESS] ORION model trained in {record.duration_seconds:.1f}s "
        f"(loss {starting_loss:.3f} -> {ending_loss:.3f})"
    )
    return record


def _merge_adapter(peft_model, merge_dir: Path, tokenizer) -> str:
    """Fold the trained LoRA into the base weights and save a HF model.

    Runs in-process (no second base load), so peak RAM sits only slightly
    above training. Returns the output directory, or "" if it could not merge."""
    try:
        merged = peft_model.merge_and_unload()
        merge_dir.mkdir(parents=True, exist_ok=True)
        merged.save_pretrained(merge_dir)
        if tokenizer is not None:
            try:
                tokenizer.save_pretrained(merge_dir)
            except Exception:
                pass
        return str(merge_dir)
    except Exception as e:
        print(f"  [!] merge failed: {e}")
        return ""


@experiment("orion-sft")
@param(
    "dataset",
    default="data/training/orion_dataset.jsonl",
    type=str,
    description="Path to the JSONL training dataset",
)
@param("epochs", default=3, type=int, description="Training epochs")
@param("lr", default=2e-3, type=float, description="AdamW learning rate")
@param("seed", default=42, type=int, description="Random seed")
@param("max_len", default=384, type=int, description="Max sequence length")
@param("batch_size", default=2, type=int, description="Micro-batch size")
@param("grad_accum", default=4, type=int, description="Gradient accumulation steps")
@param(
    "use_packing",
    default=False,
    type=bool,
    description="Pack short samples into full blocks (organic batching)",
)
@param(
    "surrogate",
    default=False,
    type=bool,
    description="Train the architectural miniature instead of the 0.5B",
)
@param(
    "merge_dir",
    default=None,
    type=str,
    description="Optional merged HF model output directory",
)
@param(
    "checkpoint_dir",
    default=None,
    type=str,
    description="Optional explicit LoRA checkpoint directory",
)
def train(params):
    rec = run_orion_training(
        Path(params.dataset),
        epochs=params.epochs,
        lr=params.lr,
        seed=params.seed,
        checkpoint_dir=Path(params.checkpoint_dir) if params.checkpoint_dir else None,
        surrogate=params.surrogate,
        merge_dir=Path(params.merge_dir) if params.merge_dir else None,
        max_len=params.max_len,
        batch_size=params.batch_size,
        grad_accum=params.grad_accum,
        use_packing=params.use_packing,
    )
    return rec


def main():
    ap = argparse.ArgumentParser(description="Train the custom ORION LoRA model")
    ap.add_argument("--dataset", type=str, default="data/training/orion_dataset.jsonl")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--checkpoint-dir", type=str, default=None)
    ap.add_argument(
        "--surrogate",
        action="store_true",
        help="train the architectural miniature (verification)",
    )
    ap.add_argument(
        "--use-packing", action="store_true", help="pack short samples into full blocks"
    )
    ap.add_argument(
        "--merge",
        type=str,
        default=None,
        help="also write a merged HF model to this directory",
    )
    args = ap.parse_args()

    try:
        rec = run_experiment(
            "orion-sft",
            values={
                "dataset": args.dataset,
                "epochs": args.epochs,
                "lr": args.lr,
                "seed": args.seed,
                "checkpoint_dir": args.checkpoint_dir,
                "surrogate": args.surrogate,
                "use_packing": args.use_packing,
                "merge_dir": args.merge,
            },
        )
    except Exception as e:
        print(f"\n[CRITICAL] orion_train failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(2)
    if rec.loss_reduction_pct <= 0 or not rec.output_differs:
        print("[WARNING] adapter did not behave as expected; check dataset/hyperparams")
        sys.exit(1)
    print(f"\ncheckpoint: {rec.checkpoint_path}")
    if args.merge:
        print(f"merged:     {args.merge}")
    sys.exit(0)


if __name__ == "__main__":
    main()
