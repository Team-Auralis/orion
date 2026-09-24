#!/usr/bin/env python3
"""F7: repeated + concurrent inference stability on COMP-001 checkpoint-1919.

Loads the TRUE latest 100m-real weights ONCE (one model in RAM), then:
  1. 20 sequential greedy generations on the same prompt (torch CPU): record
     latency + RSS per call -> leak slope (MB/call) and p50 drift (first 5 vs
     last 5), and confirm outputs are identical every call (determinism under
     sustained load).
  2. 10 concurrent threads each doing a short greedy generation on the shared
     model: confirm no deadlock/crash and every output equals the sequential
     prefix (determinism under concurrency).

Output: logs/forensic/stress_inference.json (+ printed PASS/FAIL summary).
"""

from __future__ import annotations

import concurrent.futures
import gc
import json
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "training"))

import numpy as np  # noqa: E402
import torch  # noqa: E402

from scripts.forensic.eval_suite import (  # noqa: E402
    free_ram_mb,
    load_model_from_checkpoint,
    load_tokenizer,
    peak_rss_mb,
    ramp_guard,
)

CKPT_DIR = REPO_ROOT / "models" / "comp001" / "100m-real" / "checkpoint-1919"
OUT_FILE = REPO_ROOT / "logs" / "forensic" / "stress_inference.json"
PROMPT = (
    "INSTRUCTION: What is the capital of France?\nRESPONSE: The capital of France is"
)
SEQ_NEW_TOKENS = 32
CONCURRENT_NEW_TOKENS = 8
CONCURRENT_THREADS = 10
RAM_FLOOR_MB = 300.0
THREADS = 6

out: dict = {}


def greedy(model, tokenizer, max_new: int) -> tuple[float, list[int]]:
    """One greedy generation; returns (elapsed_s, output_ids)."""
    input_ids = torch.tensor([tokenizer.encode(PROMPT).ids[:32]], dtype=torch.long)
    t0 = time.perf_counter()
    with torch.no_grad():
        out_ids = model.generate(
            input_ids=input_ids,
            max_new_tokens=max_new,
            do_sample=False,
            pad_token_id=0,
            eos_token_id=2,
        )
    elapsed = time.perf_counter() - t0
    return elapsed, out_ids[0, input_ids.shape[1] :].tolist()


def main() -> None:
    ramp_guard("inference stress start")
    torch.set_num_threads(THREADS)
    out["meta"] = {
        "torch": torch.__version__,
        "checkpoint": str(CKPT_DIR),
        "prompt": PROMPT,
        "seq_new_tokens": SEQ_NEW_TOKENS,
        "concurrent_threads": CONCURRENT_THREADS,
        "free_ram_mb_start": round(free_ram_mb(), 1),
    }

    model, cfg, step, _, n_params, loaded_note = load_model_from_checkpoint(CKPT_DIR)
    out["model"] = {
        "param_count": int(n_params),
        "ckpt_step": int(step),
        "loaded_note": loaded_note,
    }
    tok = load_tokenizer()
    model.eval()
    rss_after_load = peak_rss_mb()
    print(f"[LOAD] params={n_params:,} step={step} rss={rss_after_load:.0f} MB")

    min_free = [float("inf")]
    stop = threading.Event()

    def monitor(evt: threading.Event) -> None:
        while not evt.is_set():
            a = free_ram_mb()
            min_free[0] = min(min_free[0], a)
            if a < RAM_FLOOR_MB:
                print(f"[RAM] free {a:.0f} MB < floor {RAM_FLOOR_MB:.0f} MB")
            evt.wait(0.5)

    stop = threading.Event()
    mon = threading.Thread(target=monitor, args=(stop,), daemon=True)
    mon.start()

    # ---- 1. sequential: 20 identical greedy generations ---------------------
    lats, rss_snap, outputs = [], [], []
    for i in range(20):
        t, ids = greedy(model, tok, SEQ_NEW_TOKENS)
        lats.append(t)
        rss_snap.append(peak_rss_mb())
        outputs.append(ids)
        print(
            f"  gen {i + 1:2d}/20 {t * 1e3:8.1f} ms rss {rss_snap[-1]:.0f} MB",
            flush=True,
        )
        if free_ram_mb() < RAM_FLOOR_MB:
            raise SystemExit(
                f"[RAM] free {free_ram_mb():.0f} MB below floor - aborting"
            )

    lt = np.array(lats)
    p50_first = float(np.percentile(lt[:5], 50)) * 1e3
    p50_last = float(np.percentile(lt[-5:], 50)) * 1e3
    identical = all(o == outputs[0] for o in outputs)
    xs = np.arange(1, 21, dtype=float)
    ys = np.array(rss_snap)
    slope = float(np.polyfit(xs[5:], ys[5:], 1)[0])  # steady state, skip warmup
    out["sequential"] = {
        "calls": 20,
        "latency_ms": [round(x * 1e3, 1) for x in lats],
        "latency_p50_first5_ms": round(p50_first, 1),
        "latency_p50_last5_ms": round(p50_last, 1),
        "latency_drift_pct": round((p50_last - p50_first) / p50_first * 100.0, 2)
        if p50_first
        else 0.0,
        "outputs_identical": identical,
        "output": outputs[0] if outputs else [],
        "rss_samples_mb": [round(r, 1) for r in rss_snap],
        "rss_start_mb": round(rss_snap[0], 1),
        "rss_end_mb": round(rss_snap[-1], 1),
        "steady_state_slope_mb_per_call": round(slope, 4),
        "slope_pass": slope < 1.0,
        "determinism_pass": identical,
    }
    print("[SEQ]", json.dumps(out["sequential"]))

    # ---- 2. concurrency: 10 threads, short generations on the shared model ---
    stop.set()
    mon.join()
    results: list[tuple[int, list[int]]] = []
    errs: list[tuple[int, str]] = []
    lock = threading.Lock()
    t0 = time.perf_counter()

    def worker(k: int) -> None:
        try:
            _, ids = greedy(model, tok, CONCURRENT_NEW_TOKENS)
            with lock:
                results.append((k, ids))
        except Exception as e:  # noqa: BLE001 - record exact failure
            with lock:
                errs.append((k, f"{type(e).__name__}: {e}"))

    stop2 = threading.Event()
    mon2 = threading.Thread(target=monitor, args=(stop2,), daemon=True)
    mon2.start()
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_THREADS) as ex:
        list(ex.map(worker, range(CONCURRENT_THREADS)))
    conc_wall = time.perf_counter() - t0
    stop2.set()
    mon2.join()
    stop.set()
    mon.join()

    seq_prefix = outputs[0][:CONCURRENT_NEW_TOKENS]
    equal = all(ids == seq_prefix for _, ids in results)
    out["concurrent"] = {
        "threads": CONCURRENT_THREADS,
        "wall_s": round(conc_wall, 2),
        "errors": errs,
        "outputs_equal_to_sequential_prefix": equal,
        "outputs": [ids for _, ids in sorted(results)],
        "no_deadlock_or_crash": len(errs) == 0 and len(results) == CONCURRENT_THREADS,
    }
    print("[CONC]", json.dumps(out["concurrent"]))

    del model
    gc.collect()
    out["ram"] = {
        "min_free_ram_mb": round(min_free[0], 1),
        "ram_floor_mb": RAM_FLOOR_MB,
        "rss_after_load_mb": round(rss_after_load, 1),
        "rss_after_del_gc_mb": round(peak_rss_mb(), 1),
        "free_ram_mb_end": round(free_ram_mb(), 1),
    }
    flags = {
        "seq_determinism_pass": out["sequential"]["determinism_pass"],
        "seq_slope_pass": out["sequential"]["slope_pass"],
        "concurrent_pass": out["concurrent"]["no_deadlock_or_crash"]
        and out["concurrent"]["outputs_equal_to_sequential_prefix"],
        "sustained_ram_pass": out["ram"]["min_free_ram_mb"] > RAM_FLOOR_MB,
    }
    out["flags"] = flags
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("\n[DONE] wrote", OUT_FILE)
    print("[FLAGS]", json.dumps(flags))


if __name__ == "__main__":
    main()
