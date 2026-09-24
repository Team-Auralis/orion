#!/usr/bin/env python3
"""Unified scaling evaluation suite for ORION 100M custom-from-scratch checkpoints.

Evaluates an arbitrary checkpoint or model export across:
1. Held-out validation perplexity (val-* shards, token-weighted sum-NLL)
2. Held-out test perplexity (test-* shards, token-weighted sum-NLL)
3. HellaSwag (Rowan/hellaswag validation split, N=100 slice, seed 42, contamination screened)
4. ARC-Easy (allenai/ai2_arc ARC-Easy validation split, N=100 slice, seed 42, contamination screened)
5. WinoGrande (winogrande_debiased validation split, N=100 slice, seed 42, contamination screened)
6. ORION-specific unseen evaluation set (20-item offline probe from comp001_quality.py)
7. Inference speed (tok/s) on fixed greedy decode prompt
8. Peak RSS and checkpoint SHA-256 hash

Usage:
    python scripts/evaluation/scaling_eval.py --checkpoint models/comp001/100m-real/checkpoint-1919 --n 100
"""

import argparse
import hashlib
import json
import math
import os
import random
import re
import shutil
import sys
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "training"))

import psutil  # noqa: E402
import torch  # noqa: E402
from transformers import Qwen2Config, Qwen2ForCausalLM  # noqa: E402

import orion_corpus  # noqa: E402
from orion_runner.loader import pack_sequences, tokenize_samples  # noqa: E402
from scripts.evaluation.comp001_quality import PROBE_ITEMS  # noqa: E402

MAX_LEN = 512
EVAL_BATCH = 4
SLICE_SEED = 42
DEFAULT_N = 100
PAD_ID, BOS_ID, EOS_ID = 0, 1, 2
INFERENCE_PROMPT = "INSTRUCTION: What is the capital of France?\nRESPONSE: The capital of France is"
INFERENCE_NEW_TOKENS = 32
_WS_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    return _WS_RE.sub(" ", text).strip().lower()


def get_checkpoint_sha256(ckpt_path: Path) -> str:
    """Compute sha256 of the primary weights file in checkpoint."""
    target = None
    if (ckpt_path / "checkpoint.pt").exists():
        target = ckpt_path / "checkpoint.pt"
    elif (ckpt_path / "model.safetensors").exists():
        target = ckpt_path / "model.safetensors"
    if not target:
        return "none"
    h = hashlib.sha256()
    with open(target, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def load_model_from_checkpoint(ckpt_path: Path, hf_config_dir: Path):
    """Load model from either checkpoint.pt or directory with safetensors."""
    cfg = Qwen2Config.from_pretrained(str(hf_config_dir))
    model = Qwen2ForCausalLM(cfg)
    if (ckpt_path / "checkpoint.pt").exists():
        state = torch.load(ckpt_path / "checkpoint.pt", map_location="cpu", weights_only=False)
        model.load_state_dict(state["model"])
        step = state.get("step", 0)
        losses = state.get("losses", [])
    elif (ckpt_path / "model.safetensors").exists():
        model = Qwen2ForCausalLM.from_pretrained(str(ckpt_path))
        step = 0
        losses = []
    else:
        raise ValueError(f"No valid weights found in {ckpt_path}")
    model.eval()
    return model, cfg, step, losses


def eval_split(model, tokenizer, split: str) -> dict:
    """Per-shard + combined token-weighted CE loss/ppl for one split (val|test)."""
    files = sorted(p for p in orion_corpus.shard_files() if p.name.startswith(split + "-"))
    if not files:
        return {"loss": float("nan"), "ppl": float("nan"), "tokens": 0}
    total_nll, total_n, total_attn = 0.0, 0, 0
    for path in files:
        rows = orion_corpus.load_samples([path])
        blocks = pack_sequences(
            tokenize_samples(rows, tokenizer, orion_corpus.row_text, max_len=MAX_LEN, truncation=True),
            max_len=MAX_LEN,
            pad_id=orion_corpus.PAD_ID,
            seed=42,
            mask_boundaries=True,
            pad_to_max=True,
        )
        sh_nll, sh_n = 0.0, 0
        with torch.no_grad():
            for i in range(0, len(blocks), EVAL_BATCH):
                b = blocks[i : i + EVAL_BATCH]
                ids = torch.tensor([x["input_ids"] for x in b], dtype=torch.long)
                lbl = torch.tensor([x["labels"] for x in b], dtype=torch.long)
                out = model(input_ids=ids, labels=lbl)
                n_lbl = int((lbl != -100).sum().item())
                sh_nll += float(out.loss.item()) * n_lbl
                sh_n += n_lbl
        attn = sum(sum(b["attention_mask"]) for b in blocks)
        total_nll += sh_nll
        total_n += sh_n
        total_attn += attn
    loss = total_nll / max(total_n, 1)
    return {
        "loss": loss,
        "ppl": math.exp(loss) if loss < 100 else float("inf"),
        "tokens": total_attn,
        "loss_tokens": total_n,
    }


def score_candidates(model, tokenizer, ctx: str, endings: list) -> list:
    """Mean log-prob of each candidate's continuation tokens conditioned on ctx."""
    ctx_ids = tokenizer.encode(ctx).ids
    scores = []
    for cand in endings:
        cand_ids = tokenizer.encode(" " + cand).ids
        if not cand_ids:
            scores.append(float("-inf"))
            continue
        budget = MAX_LEN - 1
        cand_ids = cand_ids[: budget - min(len(ctx_ids), budget - 1) - 1]
        if len(ctx_ids) + len(cand_ids) > budget:
            keep = budget - len(cand_ids)
            ctx_use = ctx_ids[-max(keep, 1) :]
        else:
            ctx_use = ctx_ids
        full = ctx_use + cand_ids
        cand_start = len(ctx_use)
        if len(full) < 2 or cand_start < 1:
            scores.append(float("-inf"))
            continue
        with torch.no_grad():
            logits = model(input_ids=torch.tensor([full], dtype=torch.long)).logits[0]
        logp = torch.log_softmax(logits[:-1].float(), dim=-1)
        targets = torch.as_tensor(full[1:], dtype=torch.long)
        tok_logp = logp[torch.arange(len(full) - 1), targets]
        scores.append(float(tok_logp[cand_start - 1 :].mean().item()))
    return scores


class FastContaminationChecker:
    """Fast in-memory 13-token ngram index over training corpus."""
    def __init__(self):
        self.ngram_set = set()
        files = list(orion_corpus.shard_files())
        train_files = [p for p in files if p.name.startswith("train-")]
        for p in train_files:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                        text = orion_corpus.row_text(row)
                        tokens = normalize_text(text).split()
                        for i in range(0, len(tokens) - 13, 20):
                            self.ngram_set.add(" ".join(tokens[i : i + 13]))
                    except Exception:
                        pass

    def is_leaked(self, text: str) -> bool:
        norm = normalize_text(text)
        tokens = norm.split()
        if len(tokens) >= 13:
            ngram = " ".join(tokens[:13])
            return ngram in self.ngram_set
        return False


def screen_items_fast(checker: FastContaminationChecker, items_list: list, n: int):
    clean, dropped = [], 0
    for it in items_list:
        ctx_leak = checker.is_leaked(it["ctx"])
        gold_leak = checker.is_leaked(it["endings"][it["label"]])
        if not ctx_leak and not gold_leak:
            clean.append(it)
        else:
            dropped += 1
        if len(clean) >= n:
            break
    return clean, dropped


def eval_hellaswag(model, tokenizer, checker, n: int = 100, seed: int = 42):
    from datasets import load_dataset
    ds = load_dataset("Rowan/hellaswag", split="validation")
    rng = random.Random(seed)
    order = list(range(len(ds)))
    rng.shuffle(order)
    raw_items = [{"ctx": ds[i]["ctx"], "endings": list(ds[i]["endings"]), "label": int(ds[i]["label"])} for i in order[:n * 2]]
    items, leaked = screen_items_fast(checker, raw_items, n)
    correct = 0
    for it in items:
        scores = score_candidates(model, tokenizer, it["ctx"], it["endings"])
        pred = int(max(range(len(scores)), key=lambda k: scores[k]))
        correct += (pred == it["label"])
    return {
        "benchmark": "hellaswag",
        "n": len(items),
        "correct": correct,
        "accuracy": correct / len(items) if items else 0.0,
        "baseline": 0.25,
        "leaked_dropped": leaked,
    }


def eval_arc_easy(model, tokenizer, checker, n: int = 100, seed: int = 42):
    from datasets import load_dataset
    ds = load_dataset("allenai/ai2_arc", "ARC-Easy", split="validation")
    rng = random.Random(seed)
    order = list(range(len(ds)))
    rng.shuffle(order)
    raw_items = []
    for i in order:
        ex = ds[i]
        ch = ex["choices"]
        if ex["answerKey"] not in ch["label"]:
            continue
        raw_items.append({
            "ctx": "QUESTION: " + ex["question"] + "\nANSWER:",
            "endings": [str(t) for t in ch["text"]],
            "label": int(ch["label"].index(ex["answerKey"])),
        })
        if len(raw_items) >= n * 2:
            break
    items, leaked = screen_items_fast(checker, raw_items, n)
    correct = 0
    for it in items:
        scores = score_candidates(model, tokenizer, it["ctx"], it["endings"])
        pred = int(max(range(len(scores)), key=lambda k: scores[k]))
        correct += (pred == it["label"])
    return {
        "benchmark": "arc_easy",
        "n": len(items),
        "correct": correct,
        "accuracy": correct / len(items) if items else 0.0,
        "baseline": 0.25,
        "leaked_dropped": leaked,
    }


def eval_winogrande(model, tokenizer, checker, n: int = 100, seed: int = 42):
    from datasets import load_dataset
    ds = load_dataset("winogrande", "winogrande_debiased", split="validation")
    rng = random.Random(seed)
    order = list(range(len(ds)))
    rng.shuffle(order)
    raw_items = []
    for i in order:
        ex = ds[i]
        parts = ex["sentence"].split("_")
        if len(parts) != 2:
            continue
        raw_items.append({
            "ctx": parts[0],
            "endings": [ex["option1"] + parts[1], ex["option2"] + parts[1]],
            "label": int(ex["answer"]) - 1,
        })
        if len(raw_items) >= n * 2:
            break
    items, leaked = screen_items_fast(checker, raw_items, n)
    correct = 0
    for it in items:
        scores = score_candidates(model, tokenizer, it["ctx"], it["endings"])
        pred = int(max(range(len(scores)), key=lambda k: scores[k]))
        correct += (pred == it["label"])
    return {
        "benchmark": "winogrande",
        "n": len(items),
        "correct": correct,
        "accuracy": correct / len(items) if items else 0.0,
        "baseline": 0.50,
        "leaked_dropped": leaked,
    }


def eval_orion_probe(model, tokenizer):
    """Run the 20-item offline probe from comp001_quality.py."""
    correct = 0
    for prompt, expected in PROBE_ITEMS:
        input_ids = torch.tensor([tokenizer.encode(prompt).ids], dtype=torch.long)
        with torch.no_grad():
            out_ids = model.generate(
                input_ids=input_ids,
                max_new_tokens=12,
                do_sample=False,
                pad_token_id=PAD_ID,
                eos_token_id=EOS_ID,
            )
        completion = tokenizer.decode(out_ids[0, input_ids.shape[1] :].tolist()).strip().lower()
        if expected.lower() in completion:
            correct += 1
    return {
        "benchmark": "orion_probe_20",
        "n": len(PROBE_ITEMS),
        "correct": correct,
        "accuracy": correct / len(PROBE_ITEMS),
    }


def measure_inference(model, tokenizer):
    input_ids = torch.tensor([tokenizer.encode(INFERENCE_PROMPT).ids], dtype=torch.long)
    t0 = time.time()
    with torch.no_grad():
        out_ids = model.generate(
            input_ids=input_ids,
            max_new_tokens=INFERENCE_NEW_TOKENS,
            do_sample=False,
            pad_token_id=PAD_ID,
            eos_token_id=EOS_ID,
        )
    dur = time.time() - t0
    gen = int(out_ids.shape[1] - input_ids.shape[1])
    return gen / dur if dur > 0 else 0.0


def evaluate_checkpoint(ckpt_path: Path, hf_dir: Path, checker: FastContaminationChecker, n: int = DEFAULT_N):
    t0 = time.time()
    tokenizer = orion_corpus.load_bpe_compat()
    model, cfg, step, losses = load_model_from_checkpoint(ckpt_path, hf_dir)
    ckpt_hash = get_checkpoint_sha256(ckpt_path)

    print(f"[{ckpt_path.name}] evaluating held-out val/test splits...")
    val_res = eval_split(model, tokenizer, "val")
    test_res = eval_split(model, tokenizer, "test")

    print(f"[{ckpt_path.name}] evaluating HellaSwag (N={n})...")
    hs_res = eval_hellaswag(model, tokenizer, checker, n=n, seed=SLICE_SEED)

    print(f"[{ckpt_path.name}] evaluating ARC-Easy (N={n})...")
    arc_res = eval_arc_easy(model, tokenizer, checker, n=n, seed=SLICE_SEED)

    print(f"[{ckpt_path.name}] evaluating WinoGrande (N={n})...")
    wino_res = eval_winogrande(model, tokenizer, checker, n=n, seed=SLICE_SEED)

    print(f"[{ckpt_path.name}] evaluating ORION 20-item unseen probe...")
    probe_res = eval_orion_probe(model, tokenizer)

    print(f"[{ckpt_path.name}] measuring inference throughput...")
    infer_speed = measure_inference(model, tokenizer)
    peak_rss_mb = psutil.Process().memory_info().rss / 1024**2
    wall_time = time.time() - t0

    result = {
        "checkpoint": str(ckpt_path),
        "step": step,
        "checkpoint_hash": ckpt_hash[:16],
        "val_loss": round(val_res["loss"], 4),
        "val_ppl": round(val_res["ppl"], 2),
        "test_loss": round(test_res["loss"], 4),
        "test_ppl": round(test_res["ppl"], 2),
        "hellaswag_acc": round(hs_res["accuracy"], 4),
        "hellaswag_baseline": hs_res["baseline"],
        "arc_easy_acc": round(arc_res["accuracy"], 4),
        "arc_easy_baseline": arc_res["baseline"],
        "winogrande_acc": round(wino_res["accuracy"], 4),
        "winogrande_baseline": wino_res["baseline"],
        "orion_probe_score": round(probe_res["accuracy"], 4),
        "infer_tok_per_s": round(infer_speed, 2),
        "peak_rss_mb": round(peak_rss_mb, 1),
        "wall_time_s": round(wall_time, 2),
    }
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", required=True, help="Path to checkpoint directory or multiple comma-separated")
    ap.add_argument("--hf-config", default="models/comp001/100m-real", help="HF config directory")
    ap.add_argument("--n", type=int, default=DEFAULT_N, help="Benchmark slice size")
    ap.add_argument("--threads", type=int, default=6, help="torch threads")
    args = ap.parse_args()

    torch.set_num_threads(args.threads)
    hf_dir = Path(args.hf_config)

    print("[EVAL] Initializing fast in-memory contamination index...")
    checker = FastContaminationChecker()
    print(f"[EVAL] Contamination index ready: {len(checker.ngram_set):,} n-grams indexed.")

    checkpoints = [Path(p.strip()) for p in args.checkpoint.split(",") if p.strip()]
    all_results = []
    for ckpt_path in checkpoints:
        print(f"\n{'='*70}\nEVALUATING: {ckpt_path}\n{'='*70}")
        res = evaluate_checkpoint(ckpt_path, hf_dir, checker, n=args.n)
        all_results.append(res)
        print(json.dumps(res, indent=2))

    print("\n" + "="*70)
    print("ALL EVALUATION RESULTS:")
    print(json.dumps(all_results, indent=2))
    print("="*70)


if __name__ == "__main__":
    main()
