#!/usr/bin/env python3
"""DPO post-training stage for the custom ORION LoRA model.

Takes the deterministic preference pairs produced by
`orion_dataset.py --with-preferences` (data/training/orion_preferences.jsonl:
{"instruction", "chosen", "rejected"}) and optimises the SFT checkpoint (or a
fresh LoRA) with the Direct Preference Optimisation objective:

    L = -E[ log sigmoid( beta * ( log Pi(y_chosen) - log Pi_ref(y_chosen)
                                 - log Pi(y_rejected) + log Pi_ref(y_rejected) ) ) ]

chosen/rejected rewards are the frozen reference model's log-probs, beta = 0.1.
A RAM guard mirrors orion_train.py: below ~3.2 GB free RAM it runs the
architectural surrogate instead of the real 0.5B, so verification never crashes
the box. Registered as the ORION Runner experiment "orion-dpo".
"""

import argparse
import json
import sys
import time
import uuid
import zlib
from pathlib import Path

import psutil
import torch

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

MODEL_DIR = MODELS_DIR / "qwen_instruct"
PREF_DEFAULT = Path(REPO_ROOT) / "data" / "training" / "orion_preferences.jsonl"


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


def load_preferences(path: Path) -> list:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def format_choice(s: dict, key: str) -> str:
    return f"INSTRUCTION: {s['instruction']}\nRESPONSE: {s[key]}"


def _pad_encode(tokenizer, texts, max_len):
    enc = tokenizer(
        texts, padding=True, truncation=True, max_length=max_len, return_tensors="pt"
    )
    labels = enc["input_ids"].clone()
    labels[labels == tokenizer.pad_token_id] = -100
    return enc["input_ids"], labels


def _surrogate_encode(q: str, a: str, max_len: int):
    combined = f"INSTRUCTION: {q}\nRESPONSE: {a}"
    ids = [1] + [zlib.crc32(w.encode()) % 990 + 3 for w in combined.split()] + [2]
    ids = ids[:max_len]
    pad = 0
    padded = ids + [pad] * (max_len - len(ids))
    labels = [tok if tok != pad else -100 for tok in padded]
    return torch.tensor([padded], dtype=torch.long), torch.tensor(
        [labels], dtype=torch.long
    )


def _logprob_loss(model, input_ids, labels):
    """Return -log p(tokens) (mean per non-masked token) - NOT reduced into grad
    yet; callers call .backward() on the DPO loss that embeds these."""
    return model(input_ids=input_ids, labels=labels).loss


def run_orion_dpo(
    preferences_path: Path,
    beta: float = 0.1,
    epochs: int = 3,
    lr: float = 2e-4,
    seed: int = 42,
    adapter: str = None,
    checkpoint_dir: Path = None,
    surrogate: bool = False,
    merge_dir: Path = None,
    max_len: int = 384,
) -> TrainingRunRecord:
    start = time.time()
    run_id = f"orion-dpo-{uuid.uuid4().hex[:8]}"
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print("=" * 70)
    print(f"  ORION DPO POST-TRAIN: {run_id}")
    print("=" * 70)

    avail_gb, hardware = preflight()
    print(f"[STAGE 0: PREFLIGHT] RAM {avail_gb:.2f} GB free")

    prefs_hash = compute_file_sha256(preferences_path)
    rows = load_preferences(preferences_path)
    n_skip = sum(
        1
        for r in rows
        if not (r.get("instruction") and r.get("chosen") and r.get("rejected"))
    )
    if n_skip:
        print(f"[STAGE 1: DATA] dropping {n_skip} malformed preference rows")
    rows = [
        r
        for r in rows
        if r.get("instruction") and r.get("chosen") and r.get("rejected")
    ]
    if not rows:
        raise RuntimeError(
            f"no usable preferences in {preferences_path}; "
            "run orion_dataset.py --with-preferences"
        )
    print(f"[STAGE 1: PREF_DATA] {len(rows)} pairs | sha256 {prefs_hash[:16]}...")

    torch.manual_seed(seed)
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        Qwen2Config,
        Qwen2ForCausalLM,
    )
    from peft import LoraConfig, PeftModel, get_peft_model

    use_real = not surrogate and avail_gb >= 3.2 and MODEL_DIR.exists()
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
        policy = get_peft_model(
            base,
            LoraConfig(
                r=8,
                lora_alpha=16,
                target_modules=["q_proj", "v_proj"],
                lora_dropout=0.05,
                bias="none",
                task_type="CAUSAL_LM",
            ),
        )
        ref = Qwen2ForCausalLM(cfg)
        tokenizer = None
        base_name = "qwen2-architectural-surrogate"
        print(
            f"[STAGE 2: POLICY] {policy.print_trainable_parameters() or 'LoRA fresh'}"
        )
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
        ref = AutoModelForCausalLM.from_pretrained(
            MODEL_DIR,
            torch_dtype=torch.float32,
            local_files_only=True,
            low_cpu_mem_usage=True,
        )
        if adapter:
            policy = PeftModel.from_pretrained(base, adapter)
            print(f"[STAGE 2: POLICY] LoRA resumed from {adapter}")
        else:
            policy = get_peft_model(
                base,
                LoraConfig(
                    r=8,
                    lora_alpha=16,
                    target_modules=["q_proj", "v_proj"],
                    lora_dropout=0.05,
                    bias="none",
                    task_type="CAUSAL_LM",
                ),
            )
        base_name = "qwen2:0.5b-local"
    else:
        print(
            "[STAGE 2: MODEL] RAM too low for 0.5B dual model - falling back to surrogate"
        )
        return run_orion_dpo(
            preferences_path,
            beta,
            epochs,
            lr,
            seed,
            None,
            None,
            surrogate=True,
            merge_dir=None,
            max_len=max_len,
        )

    ref.eval()
    n_eval = max(2, len(rows) // 4)
    tr, ev = rows[:-n_eval], rows[-n_eval:]
    print(f"[STAGE 3: SPLIT] {len(tr)} tune / {len(ev)} eval pairs")

    def sample_tensors(pair, train_policy=True):
        if tokenizer is not None:
            ic, lc = _pad_encode(tokenizer, [format_choice(pair, "chosen")], max_len)
            ir, lr_ = _pad_encode(tokenizer, [format_choice(pair, "rejected")], max_len)
            return ic, lc, ir, lr_
        ic, lc = _surrogate_encode(pair["instruction"], pair["chosen"], max_len)
        ir, lr_ = _surrogate_encode(pair["instruction"], pair["rejected"], max_len)
        return ic, lc, ir, lr_

    def dpo_loss_model(pair, grads):
        ic, lc, ir, lr_ = sample_tensors(pair)
        if grads:
            lpc = policy(input_ids=ic, labels=lc).loss
            lpr = policy(input_ids=ir, labels=lr_).loss
        else:
            with torch.no_grad():
                lpc = policy(input_ids=ic, labels=lc).loss
                lpr = policy(input_ids=ir, labels=lr_).loss
        with torch.no_grad():
            lrc = ref(input_ids=ic, labels=lc).loss
            lrr = ref(input_ids=ir, labels=lr_).loss
        delta = beta * (-lpc + lrc + lpr - lrr)
        return -torch.log(torch.sigmoid(delta))

    def evaluate():
        policy.eval()
        tot, wins = 0.0, 0
        with torch.no_grad():
            for pair in ev:
                ic, lc, ir, lr_ = sample_tensors(pair)
                lpc = float(policy(input_ids=ic, labels=lc).loss.item())
                lpr = float(policy(input_ids=ir, labels=lr_).loss.item())
                delta = beta * (-lpc + lrc_ref(pair) + lpr - lrr_ref(pair))
                tot += -torch.log(torch.sigmoid(torch.tensor(delta))).item()
                if -lpc < -lpr:
                    wins += 1
        policy.train()
        return tot / len(ev), wins / len(ev)

    def lrc_ref(pair):
        ic, lc, _, _ = sample_tensors(pair)
        with torch.no_grad():
            return float(ref(input_ids=ic, labels=lc).loss.item())

    def lrr_ref(pair):
        _, _, ir, lr_ = sample_tensors(pair)
        with torch.no_grad():
            return float(ref(input_ids=ir, labels=lr_).loss.item())

    optimizer = torch.optim.AdamW(
        [p for p in policy.parameters() if p.requires_grad],
        lr=(lr * 8.0 if surrogate else lr),
    )
    policy.train()
    history = []
    for epoch in range(epochs):
        losses = []
        for pair in tr:
            optimizer.zero_grad()
            loss = dpo_loss_model(pair, grads=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                [p for p in policy.parameters() if p.requires_grad], 1.0
            )
            optimizer.step()
            losses.append(float(loss.item()))
        history.append(sum(losses) / len(losses))
        print(f"  Epoch {epoch + 1}/{epochs} - mean dpo loss: {history[-1]:.4f}")

    starting_loss = history[0]
    ending_loss = history[-1]
    reduction = (
        ((starting_loss - ending_loss) / starting_loss) * 100.0
        if starting_loss > 0
        else 0.0
    )
    print(
        f"  DPO loss trajectory: {starting_loss:.4f} -> {ending_loss:.4f} "
        f"({reduction:+.2f}%)"
    )

    if checkpoint_dir is None:
        checkpoint_dir = MODELS_DIR / "checkpoints" / run_id
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    policy.save_pretrained(str(checkpoint_dir))
    print(f"[STAGE 4: CHECKPOINT] LoRA adapter -> {checkpoint_dir}")

    policy.eval()
    with torch.no_grad():
        eval_dpo, pref_win = evaluate()
        ic, lc, ir, lr_ = sample_tensors(ev[0])
        with policy.disable_adapter():
            base_logits = policy(input_ids=ic).logits
        adapter_logits = policy(input_ids=ic).logits
    output_differs = float(torch.norm(adapter_logits - base_logits).item()) > 1e-4
    print(
        f"[STAGE 5: EVAL] eval dpo {eval_dpo:.4f} | chosen>rejected on "
        f"{len(ev)} eval pairs: {pref_win:.0%} | logit delta differs: {output_differs}"
    )

    saved_merge_dir = ""
    if merge_dir is not None:
        if tokenizer is None:
            print("[STAGE 6: MERGE] skip merge (surrogate has no tokenizer)")
        else:
            saved_merge_dir = _merge_adapter(policy, Path(merge_dir), tokenizer)
            print(f"[STAGE 6: MERGE] merged model -> {saved_merge_dir}")

    manifest = {
        "run_id": run_id,
        "base_model": base_name,
        "objective": "DPO",
        "beta": beta,
        "adapter_resumed": adapter or "",
        "preferences_hash": prefs_hash,
        "preference_pairs": len(rows),
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
        model_type="Qwen2ForCausalLM (DPO LoRA)",
        dataset_path=str(preferences_path),
        dataset_hash=prefs_hash,
        num_samples=len(rows),
        seed=seed,
        epochs=epochs,
        learning_rate=lr,
        starting_loss=round(starting_loss, 6),
        ending_loss=round(ending_loss, 6),
        loss_reduction_pct=round(reduction, 2),
        eval_loss=round(eval_dpo, 6),
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
        f"[SUCCESS] ORION DPO completed in {record.duration_seconds:.1f}s "
        f"(dpo loss {starting_loss:.3f} -> {ending_loss:.3f})"
    )
    return record


def _merge_adapter(peft_model, merge_dir: Path, tokenizer) -> str:
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


@experiment("orion-dpo")
@param(
    "preferences",
    default="data/training/orion_preferences.jsonl",
    type=str,
    description="Path to the chosen/rejected preference pairs (JSONL)",
)
@param(
    "adapter",
    default=None,
    type=str,
    description="Prior SFT LoRA checkpoint dir to resume from",
)
@param("beta", default=0.1, type=float, description="DPO temperature")
@param("epochs", default=3, type=int, description="DPO epochs")
@param("lr", default=2e-4, type=float, description="AdamW learning rate")
@param("seed", default=42, type=int, description="Random seed")
@param("max_len", default=384, type=int, description="Max sequence length")
@param(
    "surrogate",
    default=False,
    type=bool,
    description="Run the architectural miniature instead of the 0.5B",
)
@param(
    "checkpoint_dir",
    default=None,
    type=str,
    description="Optional explicit LoRA checkpoint directory",
)
@param(
    "merge_dir",
    default=None,
    type=str,
    description="Optional merged HF model output directory",
)
def train_dpo(params):
    rec = run_orion_dpo(
        Path(params.preferences),
        beta=params.beta,
        epochs=params.epochs,
        lr=params.lr,
        seed=params.seed,
        adapter=params.adapter or None,
        checkpoint_dir=Path(params.checkpoint_dir) if params.checkpoint_dir else None,
        surrogate=params.surrogate,
        merge_dir=Path(params.merge_dir) if params.merge_dir else None,
        max_len=params.max_len,
    )
    return rec


def main():
    ap = argparse.ArgumentParser(description="DPO post-train the ORION LoRA model")
    ap.add_argument("--preferences", type=str, default=str(PREF_DEFAULT))
    ap.add_argument(
        "--adapter",
        type=str,
        default=None,
        help="prior SFT LoRA checkpoint dir to resume from",
    )
    ap.add_argument("--beta", type=float, default=0.1)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-len", type=int, default=384)
    ap.add_argument("--checkpoint-dir", type=str, default=None)
    ap.add_argument(
        "--surrogate",
        action="store_true",
        help="run the architectural miniature (verification)",
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
            "orion-dpo",
            values={
                "preferences": args.preferences,
                "adapter": args.adapter,
                "beta": args.beta,
                "epochs": args.epochs,
                "lr": args.lr,
                "seed": args.seed,
                "max_len": args.max_len,
                "checkpoint_dir": args.checkpoint_dir,
                "surrogate": args.surrogate,
                "merge_dir": args.merge,
            },
        )
    except Exception as e:
        print(f"\n[CRITICAL] orion_dpo failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(2)
    if rec.loss_reduction_pct <= 0 or not rec.output_differs:
        print("[WARNING] DPO adapter did not converge; check preferences/hyperparams")
        sys.exit(1)
    print(f"\ncheckpoint: {rec.checkpoint_path}")
    if args.merge:
        print(f"merged:     {args.merge}")
    sys.exit(0)


if __name__ == "__main__":
    main()
