#!/usr/bin/env python3
"""F6 inference profiling for COMP-001 100m-real (torch-CPU + GGUF runtime probe).

Profiles the TRUE LATEST weights (checkpoint-1919, built from checkpoint.json,
loaded fp32 in memory) on CPU-only torch: size, latency percentiles / tok/s at
1 vs 6 threads, TTFT, context-boundary behavior (512/768/1024), CPU
utilization, and load->del->gc->reload memory stability. Also records the
Phase-0 llama-cli runtime probe result for the standard (non-BitNet) GGUFs.

Output: logs/forensic/profiling/inference.json (+ printed table).
"""

from __future__ import annotations

import gc
import json
import math
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "training"))

import numpy as np  # noqa: E402
import psutil  # noqa: E402
import torch  # noqa: E402
from transformers import Qwen2Config, Qwen2ForCausalLM  # noqa: E402

from scripts.forensic.eval_suite import (  # noqa: E402
    free_ram_mb,
    load_model_from_checkpoint,
    load_tokenizer,
    peak_rss_mb,
    ramp_guard,
)

CKPT_DIR = REPO_ROOT / "models" / "comp001" / "100m-real" / "checkpoint-1919"
OUT_DIR = REPO_ROOT / "logs" / "forensic" / "profiling"
PROMPT_TEXT = (
    "The capital of France is a city in Europe and the seat of the nation. "
    "The sun rises in the east every morning and sets in the west. "
    "Water freezes at zero degrees Celsius under normal pressure on Earth."
)
SEED = 42
WARMUP, DECODE = 3, 50

out: dict = {}


def sample_peak(target: dict, key: str, stop_evt: threading.Event, interval=0.01):
    """Background RSS sampler recording the max (peak) into target[key]."""
    peak = 0.0
    while not stop_evt.is_set():
        try:
            rss = psutil.Process().memory_info().rss / 1024**2
            peak = max(peak, rss)
        except Exception:
            pass
        stop_evt.wait(interval)
    target[key] = round(peak, 1)


def greedy_decode(model, prompt_ids, n_steps: int) -> dict:
    """Greedy forward-only decode with KV cache; returns per-step seconds."""
    proc = psutil.Process()
    cur = prompt_ids.clone()
    past, mask = None, None
    times = []
    cpu0 = proc.cpu_times()
    wall0 = time.perf_counter()
    with torch.no_grad():
        for _ in range(n_steps):
            t0 = time.perf_counter()
            out = model(
                input_ids=cur,
                attention_mask=mask,
                past_key_values=past,
                use_cache=True,
            )
            times.append(time.perf_counter() - t0)
            past = out.past_key_values
            nxt = out.logits[0, -1].argmax().item()
            cur = torch.tensor([[nxt]], dtype=torch.long)
            mask = (
                torch.ones(1, mask.shape[1] + 1, dtype=torch.long)
                if mask is not None
                else torch.ones(1, prompt_ids.shape[1] + 1, dtype=torch.long)
            )
    wall = time.perf_counter() - wall0
    cpu1 = proc.cpu_times()
    cpu_pct = (cpu1.user - cpu0.user + cpu1.system - cpu0.system) / wall * 100.0
    return {"step_times": np.array(times), "wall_s": wall, "cpu_pct_1core": cpu_pct}


def ctx_forward(model, n: int) -> dict:
    """One forward at context length n; records exact success/error."""
    ids = torch.full((1, n), 1, dtype=torch.long)  # BOS repeated
    t0 = time.perf_counter()
    try:
        with torch.no_grad():
            model(input_ids=ids)
        return {"len": n, "ok": True, "elapsed_s": round(time.perf_counter() - t0, 3)}
    except Exception as e:  # noqa: BLE001 - record exact behavior
        return {
            "len": n,
            "ok": False,
            "error_type": type(e).__name__,
            "error": str(e)[:400],
        }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ramp_guard("inference profile start")
    out["meta"] = {
        "torch": torch.__version__,
        "psutil": psutil.__version__,
        "cpu_count": psutil.cpu_count(),
        "free_ram_mb_start": round(free_ram_mb(), 1),
        "seed": SEED,
        "prompt": PROMPT_TEXT,
    }

    # ---- Phase 0 result (runtime probe, recorded from the run in phase_order) ----
    out["phase_0_gguf_runtime_probe"] = {
        "method": "third_party/BitNet/build/bin/llama-cli.exe (b1-390c307) -m <gguf> -n 8 -t 6 -p 'The capital of France is' --no-display-prompt -st (single-turn; peak RSS sampled via psutil)",
        "classification": "RUNNABLE",
        "note": "BitNet llama.cpp fork loads STANDARD (non-BitNet) Qwen2 GGUFs fine: rc=0, no error, real tokens out. Two probe rounds: single-turn (-st) round recorded below; an earlier interactive-mode round observed f16 Prompt 1073.5 / Gen 65.3 t/s and q8_0 Prompt 1225.4 / Gen 87.7 t/s (same binary, different mode/warmup).",
        "f16": {
            "load": "ok",
            "rc": 0,
            "ftype": "F16",
            "prompt_tok_s": 574.4,
            "gen_tok_s": 51.3,
            "peak_rss_mb": 225.4,
            "generation": " the M\\nThe past-cre",
            "earlier_interactive_gen_tok_s": 65.3,
            "earlier_interactive_generation": [" the", " United", " States", " of", " the", " Bio", " of"],
        },
        "q8_0": {
            "load": "ok",
            "rc": 0,
            "ftype": "Q8_0",
            "prompt_tok_s": 1011.1,
            "gen_tok_s": 68.9,
            "peak_rss_mb": 132.8,
            "generation_prefix": " the lit PNM' (",
            "earlier_interactive_gen_tok_s": 87.7,
        },
    }

    # ---- 1. Size ----
    ckpt_file = CKPT_DIR / "checkpoint.pt"
    model, cfg, step, losses, n_params, loaded_note = load_model_from_checkpoint(
        CKPT_DIR
    )
    fp32_bytes = sum(p.numel() * 4 for p in model.parameters())
    out["size"] = {
        "param_count": int(n_params),
        "fp32_bytes_mb": round(fp32_bytes / 1024**2, 1),
        "checkpoint_pt_bytes_mb": round(ckpt_file.stat().st_size / 1024**2, 1),
        "loaded_from": str(ckpt_file),
        "loaded_note": loaded_note,
        "max_position_embeddings": cfg.get("max_position_embeddings"),
        "rss_after_load_mb": round(peak_rss_mb(), 1),
    }
    print("[SIZE]", json.dumps(out["size"]))

    tok = load_tokenizer()
    prompt_ids = torch.tensor([tok.encode(PROMPT_TEXT).ids[:32]], dtype=torch.long)
    out["prompt_ids"] = [int(x) for x in prompt_ids[0]]
    out["prompt_text"] = PROMPT_TEXT

    # ---- 2/4. Latency + CPU util @ 6 threads, then @ 1 thread ----
    stop = threading.Event()
    sam = threading.Thread(
        target=sample_peak,
        args=(out.setdefault("mem", {}), "peak_decode_6t", stop),
        daemon=True,
    )
    torch.manual_seed(SEED)
    torch.set_num_threads(6)
    out["latency_6t"] = {}
    p0 = time.perf_counter()
    with torch.no_grad():
        _ = model(input_ids=prompt_ids)  # first forward (prompt + TTFT)
    out["latency_6t"]["ttft_s"] = round(time.perf_counter() - p0, 4)
    for _ in range(WARMUP):
        greedy_decode(model, prompt_ids, 2)
    stop = threading.Event()
    sam = threading.Thread(
        target=sample_peak, args=(out["mem"], "peak_decode_6t", stop), daemon=True
    )
    sam.start()
    res = greedy_decode(model, prompt_ids, DECODE)
    stop.set()
    sam.join()
    t = res["step_times"]
    out["latency_6t"].update(
        {
            "decode_steps": DECODE,
            "mean_tok_s": round(DECODE / float(t.sum()), 2),
            "p50_ms": round(float(np.percentile(t, 50)) * 1e3, 2),
            "p95_ms": round(float(np.percentile(t, 95)) * 1e3, 2),
            "p99_ms": round(float(np.percentile(t, 99)) * 1e3, 2),
            "wall_s": round(res["wall_s"], 3),
            "cpu_pct_of_one_core": round(res["cpu_pct_1core"], 1),
            "cpu_cores_busy_equiv": round(res["cpu_pct_1core"] / 100.0, 2),
            "torch_num_threads": torch.get_num_threads(),
        }
    )
    print("[LAT@6T]", json.dumps(out["latency_6t"]))

    torch.set_num_threads(1)
    stop = threading.Event()
    sam = threading.Thread(
        target=sample_peak, args=(out["mem"], "peak_decode_1t", stop), daemon=True
    )
    sam.start()
    res1 = greedy_decode(model, prompt_ids, DECODE)
    stop.set()
    sam.join()
    t1 = res1["step_times"]
    out["latency_1t"] = {
        "decode_steps": DECODE,
        "mean_tok_s": round(DECODE / float(t1.sum()), 2),
        "p50_ms": round(float(np.percentile(t1, 50)) * 1e3, 2),
        "p95_ms": round(float(np.percentile(t1, 95)) * 1e3, 2),
        "p99_ms": round(float(np.percentile(t1, 99)) * 1e3, 2),
        "wall_s": round(res1["wall_s"], 3),
        "cpu_pct_of_one_core": round(res1["cpu_pct_1core"], 1),
        "torch_num_threads": torch.get_num_threads(),
    }
    print("[LAT@1T]", json.dumps(out["latency_1t"]))

    # ---- 3. Context handling: 512 (max_pos) / 768 / 1024 ----
    torch.set_num_threads(6)
    out["context_boundary"] = [ctx_forward(model, n) for n in (512, 768, 1024)]
    for c in out["context_boundary"]:
        print("[CTX]", json.dumps(c))

    # ---- 5. Reload behavior: load -> del -> gc -> load again ----
    out["reload"] = {
        "rss_before_del_mb": round(peak_rss_mb(), 1),
    }
    del model
    gc.collect()
    out["reload"]["rss_after_del_gc_mb"] = round(peak_rss_mb(), 1)
    model2, _, step2, _, _, _ = load_model_from_checkpoint(CKPT_DIR)
    out["reload"]["rss_after_reload_mb"] = round(peak_rss_mb(), 1)
    out["reload"]["step_reloaded"] = int(step2)
    print("[RELOAD]", json.dumps(out["reload"]))
    del model2
    gc.collect()

    out["meta"]["free_ram_mb_end"] = round(free_ram_mb(), 1)
    (OUT_DIR / "inference.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n[DONE] wrote {OUT_DIR / 'inference.json'}")


if __name__ == "__main__":
    main()
