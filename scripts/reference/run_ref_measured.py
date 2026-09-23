#!/usr/bin/env python3
"""Measure the official BitNet b1.58-2B-4T reference (bitnet.cpp llama-cli) on this box.

Spawns the built llama-cli binary (the bitnet.cpp reference path), samples its
resident set with psutil, and parses the generation stats llama-cli prints
(`[ Prompt: X t/s | Generation: Y t/s ]`). One process per run, peak RSS,
wall time, tokens/s. Non-interactive via `-no-cnv`.

Usage:
    python scripts/reference/run_ref_measured.py              # defaults, prints JSON
    python scripts/reference/run_ref_measured.py --repeat 2   # more runs -> median tok/s

Ledger row is recorded separately (scripts/repro.record_experiment) by the caller.
"""

import argparse
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BIN = REPO_ROOT / "third_party" / "BitNet" / "build" / "bin" / "llama-cli.exe"
DEFAULT_MODEL = REPO_ROOT / "models" / "BitNet-b1.58-2B-4T" / "ggml-model-i2_s.gguf"
PROMPT = "Daniel is a"
N_PREDICT = 16
THREADS = 6


def measure(
    bin_path: Path, model_path: Path, prompt: str, n: int, threads: int
) -> dict:
    cmd = [
        str(bin_path),
        "-m",
        str(model_path),
        "-p",
        prompt,
        "-n",
        str(n),
        "-t",
        str(threads),
        "-no-cnv",
    ]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=False
    )
    started = time.perf_counter()
    peak_rss = 0.0
    try:
        p = psutil.Process(proc.pid)
    except psutil.Error:
        p = None

    out_chunks = []

    def _drain():
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                break
            out_chunks.append(chunk)

    reader = threading.Thread(target=_drain, daemon=True)
    reader.start()
    while proc.poll() is None:
        if p is not None:
            try:
                peak_rss = max(peak_rss, p.memory_info().rss / (1024**2))
            except (psutil.Error, ProcessLookupError):
                pass
        time.sleep(0.02)
    reader.join(timeout=30)
    wall = time.perf_counter() - started
    out = b"".join(out_chunks).decode("utf-8", "replace")

    gen_tps = prompt_tps = None
    m = re.search(r"Generation:\s*([\d.]+)\s*t/s", out)
    if m:
        gen_tps = float(m.group(1))
    m = re.search(r"Prompt:\s*([\d.]+)\s*t/s", out)
    if m:
        prompt_tps = float(m.group(1))
    # Non-interactive output: text after the prompt echo/blank lines; keep first ~80 chars.
    generation = ""
    lines = [ln for ln in out.splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        if ln.strip() == prompt:
            generation = " ".join(lines[i + 1 :]).strip()
            break
    return {
        "binary": str(bin_path),
        "model": str(model_path),
        "prompt": prompt,
        "n_predict": n,
        "threads": threads,
        "exit_code": proc.returncode,
        "wall_s": round(wall, 3),
        "peak_rss_mb": round(peak_rss, 1),
        "prompt_tok_per_s": prompt_tps,
        "generation_tok_per_s": gen_tps,
        "generation": generation[:120],
        "raw_tail": out[-500:],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bin", type=Path, default=DEFAULT_BIN)
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    ap.add_argument("--repeat", type=int, default=1)
    args = ap.parse_args()

    results = []
    for i in range(args.repeat):
        results.append(measure(args.bin, args.model, PROMPT, N_PREDICT, THREADS))
        time.sleep(1)
    if args.repeat > 1:
        tps = sorted(
            r["generation_tok_per_s"] for r in results if r.get("generation_tok_per_s")
        )
        med = tps[len(tps) // 2] if tps else None
        print(json.dumps({"runs": results, "median_tok_per_s": med}, indent=2))
    else:
        print(json.dumps(results[0], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
