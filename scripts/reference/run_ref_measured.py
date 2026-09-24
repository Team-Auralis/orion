#!/usr/bin/env python3
"""Run the BitNet b1.58-2B-4T reference (bitnet.cpp / llama-cli fork) under
measurement: peak RSS (psutil sampling), eval tok/s + latency (parsed from the
binary's llama_print_timings output), generation snippet, model file size.

Task 7 reference arm. The binary is the OFFICIAL bitnet.cpp inference binary
(`llama-cli.exe` in build/bin), the model is the EXTERNAL pretrained reference
`microsoft/BitNet-b1.58-2B-4T-gguf/ggml-model-i2_s.gguf` (2.4B params, ternary
1.58-bit). All numbers are reported honestly as the external reference, not
ORION's own checkpoint.

CLI:
    python scripts/reference/run_ref_measured.py                  # defaults below
    python scripts/reference/run_ref_measured.py -p "Daniel is a" -n 16 -t 6
    python scripts/reference/run_ref_measured.py --no-record      # no ledger row
    python scripts/reference/run_ref_measured.py --self-test      # parser check only

Ledger row: experiment `bitnet-2b4t-reference`
    params      {"params_b": 2.4, "external_reference": true, ...}
    status      VERIFIED (ran+parsed) / FAILED (binary error) / BLOCKED (missing pieces)
"""

import argparse
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psutil

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from scripts.repro import record_experiment  # noqa: E402

DEFAULT_BIN = REPO_ROOT / "third_party" / "BitNet" / "build" / "bin" / "llama-cli.exe"
DEFAULT_MODEL = REPO_ROOT / "models" / "bitnet-b1.58-2B-4T" / "ggml-model-i2_s.gguf"
DEFAULT_PROMPT = "Daniel is a"
DEFAULT_N = 16
DEFAULT_T = 6

MB = 1024 * 1024

# llama_print_timings lines, e.g.
#   llama_print_timings: eval time =  1234.56 ms /    16 tokens (   77.16 ms per token,   12.96 tokens per second)
#   llama_print_timings: total time =  2345.67 ms
# This bitnet.cpp fork (b1-390c307) prints a compact banner in non-timings
# paths, e.g.:
#   [ Prompt: 85.2 t/s | Generation: 12.0 t/s ]
TIMINGS_RE = {
    # anchored on the literal prefix so "prompt eval time" is NOT matched
    "eval_ms": re.compile(
        r"llama_print_timings: eval time\s*=\s*([\d.]+) ms / +(\d+) tokens"
    ),
}
TOK_PER_S_RE = re.compile(r"([\d.]+) tokens per second")
BANNER_RE = re.compile(r"\[ Prompt:\s*([\d.]+) t/s \| Generation:\s*([\d.]+) t/s \]")


def parse_timings(text: str, n_predict: int | None = None) -> dict:
    """Pull eval ms, eval token count, tok/s and total ms from llama-cli output.

    Accepts the classic llama_print_timings block AND the bitnet.cpp fork's
    `[ Prompt: X t/s | Generation: Y t/s ]` banner (preferred when present).
    `n_predict` supplies the generated-token count when only the banner exists.
    """
    out = {}
    m = TIMINGS_RE["eval_ms"].search(text)
    if m:
        out["eval_ms"] = float(m.group(1))
        out["eval_tokens"] = int(m.group(2))
    m = TOK_PER_S_RE.search(text)
    if m:
        out["tok_per_s"] = float(m.group(1))
    m = re.search(r"total time\s*=\s*([\d.]+) ms", text)
    if m:
        out["total_ms"] = float(m.group(1))
    m = BANNER_RE.search(text)
    if m:
        out["prompt_tok_per_s"] = float(m.group(1))
        out["tok_per_s"] = float(m.group(2))
    # Latency from the fork banner: eval tokens / generation speed.
    if out.get("tok_per_s") and "eval_ms" not in out:
        n_tok = out.get("eval_tokens", 0) or (n_predict if n_predict else 0)
        out["eval_tokens"] = n_tok
        out["eval_ms"] = round(n_tok / out["tok_per_s"] * 1000, 1)
    return out


def _self_test() -> None:
    txt = (
        "llama_print_timings: prompt eval time =    42.00 ms /     3 tokens\n"
        "llama_print_timings: eval time =  1234.56 ms /    16 tokens (   77.16 ms per token,   12.96 tokens per second)\n"
        "llama_print_timings: total time =  2345.67 ms\n"
    )
    got = parse_timings(txt)
    assert got["eval_ms"] == 1234.56, got
    assert got["eval_tokens"] == 16, got
    assert got["tok_per_s"] == 12.96, got
    assert got["total_ms"] == 2345.67, got
    txt2 = "  [ Prompt: 85.2 t/s | Generation: 12.0 t/s ]\n"
    got2 = parse_timings(txt2, n_predict=16)
    assert got2["tok_per_s"] == 12.0, got2
    assert got2["prompt_tok_per_s"] == 85.2, got2
    assert abs(got2["eval_ms"] - round(16 / 12.0 * 1000, 1)) < 0.01, got2
    print("[SELF-TEST] timing parser OK (classic + fork banner):", got, got2)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-m", "--model", default=str(DEFAULT_MODEL))
    ap.add_argument("-p", "--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("-n", "--n-predict", type=int, default=DEFAULT_N)
    ap.add_argument("-t", "--threads", type=int, default=DEFAULT_T)
    ap.add_argument("--bin", default=str(DEFAULT_BIN))
    ap.add_argument("--no-record", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        _self_test()
        return 0

    model = Path(args.model)
    binary = Path(args.bin)

    # ---- preflight ---------------------------------------------------------
    missing = []
    if not binary.exists():
        missing.append(f"binary {binary}")
    if not model.exists():
        missing.append(f"model {model}")
    if missing:
        print(f"[BLOCKED] missing: {', '.join(missing)}")
        if not args.no_record:
            record_experiment(
                "bitnet-2b4t-reference",
                {"params_b": 2.4, "external_reference": True},
                {
                    "run_id": f"bitnet-ref-{uuid.uuid4().hex[:8]}",
                    "status": "BLOCKED",
                    "base_model_name": "microsoft/BitNet-b1.58-2B-4T-gguf",
                    "model_type": "bitnet-1.58-bit i2_s (external reference)",
                    "checkpoint_path": "",
                    "num_samples": 0,
                    "error_message": f"missing: {', '.join(missing)}",
                },
            )
        return 2

    file_mb = round(model.stat().st_size / MB, 1)

    # ---- spawn + measure ----------------------------------------------------
    cmd = [
        str(binary),
        "-m",
        str(model),
        "-p",
        args.prompt,
        "-n",
        str(args.n_predict),
        "-t",
        str(args.threads),
        "-ngl",
        "0",
        "-c",
        "512",
        "--temp",
        "0.8",
        "--no-display-prompt",
        "--single-turn",  # one-shot: exit after generation instead of dropping into the REPL
    ]
    t0 = time.monotonic()
    proc = psutil.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    peak_rss = 0
    chunks = []
    while proc.poll() is None:
        try:
            line = proc.stdout.readline()
        except Exception:
            line = ""
        if line:
            chunks.append(line)
        try:
            peak_rss = max(peak_rss, proc.memory_info().rss)
        except Exception:
            pass
        time.sleep(0.1)
    # drain remaining output
    for line in proc.stdout:
        chunks.append(line)
    wall_s = time.monotonic() - t0
    out_text = "".join(chunks)
    peak_rss_mb = round(peak_rss / MB, 1)

    timings = parse_timings(out_text, n_predict=args.n_predict)
    exit_code = proc.returncode

    # ---- report --------------------------------------------------------------
    status = (
        "FAILED"
        if exit_code != 0
        else ("VERIFIED" if timings.get("tok_per_s") else "FAILED")
    )
    print("=" * 72)
    print("BitNet b1.58-2B-4T reference run (bitnet.cpp llama-cli fork)")
    print("=" * 72)
    print(f"binary          : {binary}")
    print(f"model           : {model}  ({file_mb} MB)")
    print(f"cmd             : {' '.join(cmd)}")
    print(f"exit code       : {exit_code}")
    print(f"wall time       : {wall_s:.1f} s")
    print(f"peak RSS        : {peak_rss_mb} MB")
    print(f"timings         : {timings}")
    print(f"STATUS          : {status}")
    tail = [l for l in chunks if l.strip()][-8:]
    print("-- last output lines --")
    for l in tail:
        print("  " + l.rstrip())
    if not timings:
        print("[!] no llama_print_timings parsed from output; full output above")

    # ---- ledger ---------------------------------------------------------------
    if not args.no_record:
        record = {
            "run_id": f"bitnet-ref-{uuid.uuid4().hex[:8]}",
            "status": status,
            "base_model_name": "microsoft/BitNet-b1.58-2B-4T-gguf",
            "model_type": "bitnet-1.58-bit i2_s (external reference)",
            "checkpoint_path": str(model),
            "num_samples": args.n_predict,
            "error_message": "" if status == "VERIFIED" else out_text[-500:],
            "file_mb": file_mb,
            "peak_rss_mb": peak_rss_mb,
            "tok_per_s": timings.get("tok_per_s"),
            "eval_ms": timings.get("eval_ms"),
            "eval_tokens": timings.get("eval_tokens"),
            "total_ms": timings.get("total_ms"),
            "wall_s": round(wall_s, 2),
            "threads": args.threads,
            "prompt": args.prompt,
        }
        record_experiment(
            "bitnet-2b4t-reference",
            {
                "params_b": 2.4,
                "external_reference": True,
                "quantization": "i2_s",
                "runtime": "bitnet.cpp llama-cli (official)",
                "threads": args.threads,
            },
            record,
        )
        print(
            f"\n[LEDGER] appended bitnet-2b4t-reference row: status={status} "
            f"tok_per_s={timings.get('tok_per_s')} peak_rss_mb={peak_rss_mb} file_mb={file_mb}"
        )

    return 0 if status == "VERIFIED" else 1


if __name__ == "__main__":
    sys.exit(main())
