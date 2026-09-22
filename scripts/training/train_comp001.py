#!/usr/bin/env python3
"""COMP-001: from-scratch dense transformer, 10M and 100M variants (T3/T4).

Trains a plain dense Qwen2-for-CausalLM (no LoRA, no pretrained weights, no
sparsity) from random init, on CPU, over the resolved ORION corpus with the
real BPE tokenizer (models/tokenizer_bpe) trained in T2.

--model-size selects the architecture: `10m` (COMP-001 checkpoint budget,
8M-12M params) or `100m` (T4 custom run, 90M-115M params, GQA 12x4 heads).
Every run is recorded through scripts/repro.py::record_experiment as
experiment "comp-001-10m" or "comp-001-custom-100m".

  - Qwen2Config: vocab = actual BPE vocab from tokenizer, hidden 256 /
    mlp 1024 / 8 layers / 4 heads -> ~9.15M params (10m); hidden 768 /
    mlp 3072 / 12 layers / 12 heads / 4 KV heads -> ~106.1M params (100m)
  - Full-batch AdamW fp32, full-sequence blocks packed to max_len 512
  - Full checkpoints (state_dict + optimizer state + step + config) under
    models/comp001/<size>/checkpoint-<step>/
  - --resume <dir|auto> continues the loss trajectory from a checkpoint
  - Held-out eval split; HF export (config.json + model.safetensors +
    tokenizer files) for scripts/training/convert_hf_to_gguf.py
  - 3 GB peak RSS guard via psutil; tok/s + duration telemetry
  - COMP-001 metric collection (T4): params, peak RSS, train/eval loss,
    perplexity, train tok/s, greedy-decode inference tok/s, checkpoint size,
    and the offline quality probe (scripts/evaluation/comp001_quality.py).
  - Corpus-adequacy gate (T2): the run reads the last `corpus-adequacy-gate`
    verdict from logs/training_runs.jsonl; when the corpus is SMOKE_ONLY the
    100m run is recorded with status=SMOKE_RUN (a legitimately completed
    run, honestly labeled) - no quality claims beyond the measured numbers.

Usage:
    python scripts/training/train_comp001.py --epochs 10
    python scripts/training/train_comp001.py --epochs 15 --model-size 100m
    python scripts/training/train_comp001.py --epochs 5 \
        --resume models/comp001/10m/checkpoint-15
"""

import argparse
import json
import math
import os
import shutil
import subprocess
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
from orion_runner.loader import tokenize_samples, pack_sequences  # noqa: E402
from scripts.repro import record_experiment, gather_repro_ctx  # noqa: E402

OUT_DIR = REPO_ROOT / "models" / "comp001" / "10m"
OUT_DIR_100M = REPO_ROOT / "models" / "comp001" / "100m"
TOKENIZER_DIR = REPO_ROOT / "models" / "tokenizer_bpe"
RAM_GUARD_GB = 3.0  # hard ceiling: abort the run if peak RSS exceeds this
MAX_LEN = 512
PAD_ID, BOS_ID, EOS_ID = 0, 1, 2  # from bpe_tokenizer.py special-token order

# Tuned so the constructed model lands inside the 8M-12M budget (measured:
# 9,152,256 params with the real 1471-token BPE vocab, head untied).
MODEL_CFG = dict(
    vocab_size=None,  # replaced with the real tokenizer vocab at build time
    hidden_size=256,
    intermediate_size=1024,
    num_hidden_layers=8,
    num_attention_heads=4,
    num_key_value_heads=4,
    max_position_embeddings=MAX_LEN,
    pad_token_id=PAD_ID,
    bos_token_id=BOS_ID,
    eos_token_id=EOS_ID,
    tie_word_embeddings=False,
)

# T4: ~100M variant - GQA 12 heads x 4 KV heads to hold params/memory down.
# Measured 106,103,040 params with the real 1471-token BPE vocab (90M-115M).
MODEL_CFG_100M = dict(
    vocab_size=None,
    hidden_size=768,
    intermediate_size=3072,
    num_hidden_layers=12,
    num_attention_heads=12,
    num_key_value_heads=4,
    max_position_embeddings=MAX_LEN,
    pad_token_id=PAD_ID,
    bos_token_id=BOS_ID,
    eos_token_id=EOS_ID,
    tie_word_embeddings=False,
)

MODEL_SIZES = {"10m": MODEL_CFG, "100m": MODEL_CFG_100M}
PARAM_BUDGETS = {"10m": (8_000_000, 12_000_000), "100m": (90_000_000, 115_000_000)}
INFERENCE_PROMPT = (
    "INSTRUCTION: What is the capital of France?\nRESPONSE: The capital of France is"
)
INFERENCE_NEW_TOKENS = 32


def arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--epochs", type=int, default=10, help="training epochs")
    ap.add_argument(
        "--model-size",
        choices=sorted(MODEL_SIZES),
        default="10m",
        help="architecture: 10m (8M-12M params) or 100m (90M-115M params)",
    )
    ap.add_argument(
        "--max-steps",
        type=int,
        default=0,
        help="hard cap on total training steps (0 = epochs x blocks/epoch)",
    )
    ap.add_argument("--lr", type=float, default=1e-3, help="AdamW learning rate")
    ap.add_argument("--seed", type=int, default=42, help="torch/random seed")
    ap.add_argument(
        "--ckpt-every", type=int, default=5, help="checkpoint every N steps"
    )
    ap.add_argument(
        "--resume",
        default=None,
        help="checkpoint dir to resume from, or 'auto' for the highest step",
    )
    ap.add_argument("--threads", type=int, default=6, help="torch.set_num_threads")
    return ap


def build_model(vocab_size: int, seed: int, size: str = "10m"):
    cfg = dict(MODEL_SIZES[size], vocab_size=vocab_size)
    torch.manual_seed(seed)
    model = Qwen2ForCausalLM(Qwen2Config(**cfg))
    n_params = sum(p.numel() for p in model.parameters())
    lo, hi = PARAM_BUDGETS[size]
    print(
        f"[MODEL] Qwen2ForCausalLM dense from scratch | size={size} | params={n_params:,}"
    )
    assert lo <= n_params <= hi, (
        f"param count {n_params} outside the {size} budget [{lo:,}, {hi:,}]"
    )
    return model, cfg, n_params


def load_data():
    """Resolve corpus + real BPE tokenizer; fail loudly, never surrogate."""
    files, source, is_real = orion_corpus.resolve_corpus()
    if not is_real or not orion_corpus.bpe_tokenizer_available():
        raise SystemExit(
            "[DATA] need real corpus shards under data/training/corpus/ and a "
            "trained BPE tokenizer at models/tokenizer_bpe/tokenizer.json"
        )
    tokenizer = orion_corpus.load_bpe_compat()
    vocab = tokenizer.vocab_size
    samples = orion_corpus.load_samples(files)
    corpus_sha = orion_corpus.corpus_sha256(files)
    print(
        f"[DATA] source={source} shards={[p.name for p in files]} "
        f"corpus_sha256={corpus_sha[:16]}... samples={len(samples)} "
        f"vocab={vocab}"
    )
    if len(samples) < 2:
        raise SystemExit("[DATA] corpus too small for a train/eval split")
    split = max(1, int(len(samples) * 0.75))
    return tokenizer, vocab, samples, split, files, corpus_sha


def make_blocks(rows, tokenizer, fmt):
    samples = tokenize_samples(rows, tokenizer, fmt, max_len=MAX_LEN, truncation=True)
    return pack_sequences(
        samples,
        max_len=MAX_LEN,
        pad_id=PAD_ID,
        seed=42,
        mask_boundaries=True,
        pad_to_max=True,
    )


def real_tokens(blocks) -> int:
    return sum(sum(b["attention_mask"]) for b in blocks)


def checkpoint_dir(step: int) -> Path:
    return OUT_DIR / f"checkpoint-{step}"


def save_checkpoint(step: int, model, optimizer, cfg, hparams, losses):
    ckpt_dir = checkpoint_dir(step)
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "step": step,
            "config": cfg,
            "hparams": hparams,
            "losses": losses,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        ckpt_dir / "checkpoint.pt",
    )
    (ckpt_dir / "checkpoint.json").write_text(
        json.dumps({"step": step, "config": cfg, "hparams": hparams}, indent=2),
        encoding="utf-8",
    )
    print(f"[CKPT] saved {ckpt_dir}/ (step {step})")


def load_checkpoint(ckpt: Path, model, optimizer):
    ck = torch.load(ckpt / "checkpoint.pt", map_location="cpu", weights_only=False)
    model.load_state_dict(ck["model"])
    optimizer.load_state_dict(ck["optimizer"])
    print(
        f"[RESUME] loaded {ckpt} at step {ck['step']} "
        f"(loss history: {ck['losses'][-3:]})"
    )
    return int(ck["step"]), ck.get("losses", [])


def find_latest_checkpoint() -> Path:
    if not OUT_DIR.is_dir():
        return None
    steps = []
    for d in OUT_DIR.glob("checkpoint-*"):
        try:
            steps.append((int(d.name.split("-")[1]), d))
        except (IndexError, ValueError):
            continue
    return max(steps, default=(None, None))[1]


def snapshot_weights(model):
    return [p.detach().clone() for p in model.parameters()]


def weight_delta(a, b) -> float:
    acc = 0.0
    for x, y in zip(a, b):
        acc += ((x - y).float() ** 2).sum().item()
    return acc**0.5


def export_hf(model, cfg):
    """Final HF-layout export for convert_hf_to_gguf.py: config.json +
    model.safetensors + tokenizer files copied from the BPE tokenizer dir."""
    out = OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(out), safe_serialization=True)
    for name in (
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "added_tokens.json",
    ):
        src = TOKENIZER_DIR / name
        if src.exists():
            shutil.copy2(src, out / name)
    assert (out / "config.json").exists() and (out / "model.safetensors").exists()
    n_ck = (out / "config.json").stat().st_size
    n_sf = (out / "model.safetensors").stat().st_size
    print(
        f"[EXPORT] HF model -> {out} (config.json {n_ck} B + "
        f"model.safetensors {n_sf} B + tokenizer files)"
    )


def dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def read_gate_verdict() -> dict:
    """Last corpus-adequacy-gate row from the ledger (T2); {} when absent."""
    ledger = REPO_ROOT / "logs" / "training_runs.jsonl"
    if not ledger.exists():
        return {}
    rows = [
        json.loads(line)
        for line in ledger.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for row in reversed(rows):
        if row.get("experiment") == "corpus-adequacy-gate" and "verdict" in row:
            return row
    return {}


def measure_inference(model, tokenizer):
    """Greedy-decode latency (tok/s) on a fixed 32-token generation."""
    input_ids = torch.tensor([tokenizer.encode(INFERENCE_PROMPT).ids], dtype=torch.long)
    model.eval()
    t0 = time.time()
    with torch.no_grad():
        out_ids = model.generate(
            input_ids=input_ids,
            max_new_tokens=INFERENCE_NEW_TOKENS,
            do_sample=False,
            pad_token_id=PAD_ID,
            eos_token_id=EOS_ID,
        )
    elapsed = time.time() - t0
    generated = int(out_ids.shape[1] - input_ids.shape[1])
    tok_per_s = generated / elapsed if elapsed > 0 else 0.0
    completion = tokenizer.decode(out_ids[0, input_ids.shape[1] :].tolist())
    print(
        f"[INFER] greedy {generated} new tokens on fixed prompt: "
        f"{tok_per_s:.1f} tok/s ({elapsed:.2f}s) | completion: {completion!r}"
    )
    return tok_per_s, completion


def run_quality_probe(model_dir: Path, tokenizer_dir: Path):
    """Offline COMP-001 quality probe (scripts/evaluation/comp001_quality.py).

    Returns the completion-accuracy fraction (0-1) the probe prints, or None
    on failure (the run itself must not fail because a probe did)."""
    probe_script = REPO_ROOT / "scripts" / "evaluation" / "comp001_quality.py"
    if not probe_script.exists():
        print("[PROBE] comp001_quality.py missing - skipping")
        return None
    try:
        res = subprocess.run(
            [
                sys.executable,
                str(probe_script),
                "--model",
                str(model_dir),
                "--tokenizer",
                str(tokenizer_dir),
            ],
            capture_output=True,
            text=True,
            timeout=900,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired:
        print("[PROBE] timed out - skipping")
        return None
    print(res.stdout)
    if res.returncode != 0:
        print(f"[PROBE] failed rc={res.returncode}: {res.stderr[-500:]}")
        return None
    for line in res.stdout.splitlines():
        if line.startswith("PROBE_SCORE="):
            try:
                return float(line.split("=", 1)[1])
            except ValueError:
                return None
    return None


def main() -> int:
    args = arg_parser().parse_args()
    torch.set_num_threads(args.threads)
    global OUT_DIR
    OUT_DIR = OUT_DIR_100M if args.model_size == "100m" else OUT_DIR
    experiment_name = (
        "comp-001-custom-100m" if args.model_size == "100m" else "comp-001-10m"
    )

    start_time = time.time()
    run_id = f"{experiment_name}-{uuid.uuid4().hex[:8]}"
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(
        f"\n{'=' * 70}\n  COMP-001 {args.model_size.upper()} TRAINING: {run_id}"
        f"\n{'=' * 70}"
    )

    # --- data + tokenizer (BPE from T2; real corpus; never surrogate) -------
    tokenizer, vocab, samples, split, files, corpus_sha = load_data()
    train_rows, eval_rows = samples[:split], samples[split:]
    train_blocks = make_blocks(train_rows, tokenizer, orion_corpus.format_sample)
    eval_blocks = make_blocks(eval_rows, tokenizer, orion_corpus.format_sample)
    per_epoch = len(train_blocks)
    total_tokens = real_tokens(train_blocks) * args.epochs
    print(
        f"[DATA] train samples={len(train_rows)} eval samples={len(eval_rows)} "
        f"| train blocks={per_epoch} eval blocks={len(eval_blocks)} "
        f"| tokens/epoch={real_tokens(train_blocks)} total={total_tokens}"
    )

    # --- corpus-adequacy gate (T2 verdict from the ledger, read before run) --
    gate = read_gate_verdict()
    gate_verdict = gate.get("verdict", "UNKNOWN")
    corpus_tokens = gate.get("actual_tokens", real_tokens(train_blocks))
    required_tokens = gate.get(
        "required_tokens_for_100m", orion_corpus.REQUIRED_TOKENS_FOR_100M
    )
    run_status = (
        "SMOKE_RUN"
        if args.model_size == "100m" and gate_verdict != "ADEQUATE"
        else "COMPLETED"
    )
    print(
        f"[GATE] ledger verdict={gate_verdict} corpus_tokens={corpus_tokens:,} "
        f"required_tokens_for_100m={required_tokens:,} -> status={run_status}"
    )

    # --- model (dense from scratch) -----------------------------------------
    model, cfg, n_params = build_model(vocab, args.seed, args.model_size)
    # Expected peak RSS: fp32 weights + grads + 2x AdamW states (16 B/param)
    # + activations/overhead margin (~250 MB at seq 512, batch 1).
    expected_rss_mb = n_params * 16 / 1024**2 + 250
    print(
        f"[RSS-EST] expected peak ~{expected_rss_mb:.0f} MB "
        f"(w+grad+2xAdam={n_params * 16 / 1024**2:.0f} MB + ~250 MB overhead) "
        f"| guard: {RAM_GUARD_GB} GB"
    )
    hparams = {
        "epochs": args.epochs,
        "model_size": args.model_size,
        "max_steps": args.max_steps,
        "lr": args.lr,
        "seed": args.seed,
        "ckpt_every": args.ckpt_every,
        "threads": args.threads,
        "max_len": MAX_LEN,
        "batch_size": 1,
    }

    # --- optimizer + optional resume ----------------------------------------
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    losses = []
    start_step = 0
    resumed_from = None
    if args.resume:
        ckpt = find_latest_checkpoint() if args.resume == "auto" else Path(args.resume)
        if ckpt is None or not (ckpt / "checkpoint.pt").exists():
            raise SystemExit(f"[RESUME] checkpoint not found: {args.resume}")
        start_step, _ = load_checkpoint(ckpt, model, optimizer)
        resumed_from = str(ckpt)
    total_steps = (
        start_step + args.epochs * per_epoch
    )  # resumed runs continue, not restart
    if args.max_steps > 0:
        total_steps = min(total_steps, start_step + args.max_steps)
    init_weights = snapshot_weights(model)

    # --- training loop (full-batch AdamW fp32, batch=1 full block) -----------
    model.train()
    print(
        f"[TRAIN] steps={total_steps} start_step={start_step} "
        f"lr={args.lr} threads={args.threads} | RSS guard: {RAM_GUARD_GB} GB"
    )
    peak_rss = psutil.Process().memory_info().rss
    train_start = time.time()
    for gstep in range(start_step, total_steps):
        block = train_blocks[gstep % per_epoch]
        input_ids = torch.tensor(block["input_ids"], dtype=torch.long).unsqueeze(0)
        labels = torch.tensor(block["labels"], dtype=torch.long).unsqueeze(0)

        optimizer.zero_grad()
        out = model(input_ids=input_ids, labels=labels)
        out.loss.backward()
        optimizer.step()

        step = gstep + 1
        loss = float(out.loss.item())
        losses.append(loss)

        rss = psutil.Process().memory_info().rss
        peak_rss = max(peak_rss, rss)
        if rss > RAM_GUARD_GB * 1024**3:
            raise SystemExit(
                f"[RSS GUARD] peak RSS {rss / 1024**2:.1f} MB exceeded "
                f"{RAM_GUARD_GB} GB ceiling - aborting"
            )
        print(
            f"  step {step:3d}/{total_steps} loss {loss:.4f} rss {rss / 1024**2:.0f} MB"
        )
        if step % args.ckpt_every == 0 or step == total_steps:
            save_checkpoint(step, model, optimizer, cfg, hparams, losses)

    train_seconds = time.time() - train_start
    tokens_per_sec = total_tokens / train_seconds if train_seconds > 0 else 0.0
    starting_loss = losses[0]
    ending_loss = losses[-1]
    reduction_pct = (
        (starting_loss - ending_loss) / starting_loss * 100.0
        if starting_loss > 0
        else 0.0
    )
    print(
        f"[TRAIN] loss {starting_loss:.4f} -> {ending_loss:.4f} "
        f"({reduction_pct:+.2f}%) | {tokens_per_sec:.1f} tok/s "
        f"({train_seconds:.1f}s) | peak RSS {peak_rss / 1024**2:.1f} MB"
    )
    assert ending_loss < starting_loss, "training must demonstrate loss reduction"

    # --- held-out eval -------------------------------------------------------
    model.eval()
    with torch.no_grad():
        eval_losses = []
        for block in eval_blocks:
            input_ids = torch.tensor(block["input_ids"], dtype=torch.long).unsqueeze(0)
            labels = torch.tensor(block["labels"], dtype=torch.long).unsqueeze(0)
            eval_losses.append(
                float(model(input_ids=input_ids, labels=labels).loss.item())
            )
    eval_loss = sum(eval_losses) / len(eval_losses)
    print(f"[EVAL] held-out eval loss (n={len(eval_blocks)}): {eval_loss:.4f}")

    trained_delta = weight_delta(init_weights, snapshot_weights(model))
    output_differs = trained_delta > 1e-4
    print(
        f"[DELTA] |final - init|_F = {trained_delta:.4f} (weights moved: {output_differs})"
    )

    # --- checkpoint + HF export ---------------------------------------------
    export_hf(model, cfg)
    latest_ckpt = find_latest_checkpoint()
    ckpt_bytes = dir_size(latest_ckpt) if latest_ckpt else 0
    duration = time.time() - start_time

    # --- COMP-001 metrics: inference tok/s, perplexity, quality probe --------
    inference_tok_per_s, inference_completion = measure_inference(model, tokenizer)
    perplexity = math.exp(eval_loss)
    print(f"[EVAL] perplexity e^loss = {perplexity:.3f}")
    probe_score = run_quality_probe(OUT_DIR, TOKENIZER_DIR)
    print(f"[PROBE] quality probe score = {probe_score}")

    # --- audit ledger via the shared harness ---------------------------------
    vmem = psutil.virtual_memory()
    record = {
        "run_id": run_id,
        "timestamp": timestamp,
        "status": run_status,
        "base_model_name": f"qwen2-{n_params // 1_000_000}m-from-scratch-bpe",
        "model_type": "Qwen2ForCausalLM",
        "dataset_path": str(files[0]),
        "tokenizer_path": str(TOKENIZER_DIR / "tokenizer.json"),
        "dataset_hash": corpus_sha,
        "num_samples": len(samples),
        "seed": args.seed,
        "epochs": args.epochs,
        "learning_rate": args.lr,
        "starting_loss": round(starting_loss, 6),
        "ending_loss": round(ending_loss, 6),
        "loss_reduction_pct": round(reduction_pct, 2),
        "eval_loss": round(eval_loss, 6),
        "checkpoint_path": str(OUT_DIR),
        "output_differs": output_differs,
        "hardware": gather_repro_ctx(
            str(files[0]), str(TOKENIZER_DIR / "tokenizer.json"), hparams
        )["hardware"],
        "duration_seconds": round(duration, 2),
        "param_count": n_params,
        "peak_rss_mb": round(peak_rss / 1024**2, 1),
        "tokens_per_sec": round(tokens_per_sec, 1),
        "train_tokens": total_tokens,
        "perplexity": round(perplexity, 4),
        "inference_tok_per_s": round(inference_tok_per_s, 2),
        "inference_new_tokens": INFERENCE_NEW_TOKENS,
        "inference_prompt": INFERENCE_PROMPT,
        "inference_completion": inference_completion,
        "quality_probe_score": probe_score,
        "gate_verdict": gate_verdict,
        "corpus_tokens": corpus_tokens,
        "required_tokens_for_100m": required_tokens,
        "run_grade": run_status,
        "checkpoint_size_bytes": ckpt_bytes,
        "checkpoints": sorted(
            d.name for d in OUT_DIR.glob("checkpoint-*") if d.is_dir()
        ),
        "resumed": bool(resumed_from),
        "resume_from_step": start_step,
        "resume_checkpoint": resumed_from or "",
        "vocab_size": vocab,
        "config": cfg,
        "loss_history": [round(x, 4) for x in losses],
        "error_message": "",
    }
    record["hardware"]["available_ram_gb"] = round(vmem.available / 1024**3, 2)
    record["hardware"]["total_ram_gb"] = round(vmem.total / 1024**3, 2)

    params = {
        "epochs": args.epochs,
        "model_size": args.model_size,
        "max_steps": args.max_steps,
        "lr": args.lr,
        "seed": args.seed,
        "vocab_size": vocab,
        "hidden_size": cfg["hidden_size"],
        "intermediate_size": cfg["intermediate_size"],
        "num_hidden_layers": cfg["num_hidden_layers"],
        "num_attention_heads": cfg["num_attention_heads"],
        "num_key_value_heads": cfg["num_key_value_heads"],
        "max_position_embeddings": cfg["max_position_embeddings"],
        "max_len": MAX_LEN,
        "batch_size": 1,
        "ckpt_every": args.ckpt_every,
        "torch_threads": args.threads,
        "resumed": bool(resumed_from),
        "resume_from_step": start_step,
    }
    record_experiment(experiment_name, params, record)

    print(
        f"\n[RECORD] {experiment_name} run logged: {run_id} "
        f"| status={run_status} | params={n_params:,} "
        f"| peak RSS {record['peak_rss_mb']} MB | train {record['tokens_per_sec']} tok/s "
        f"| infer {record['inference_tok_per_s']} tok/s "
        f"| perplexity {record['perplexity']} | probe {probe_score} "
        f"| {duration:.1f}s"
    )
    print(f"{'=' * 70}\n[SUCCESS] COMP-001 training completed.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
