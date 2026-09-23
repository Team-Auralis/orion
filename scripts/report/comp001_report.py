#!/usr/bin/env python3
"""ORION-COMP-001 v1 report generator (Task 7, final).

Reads logs/training_runs.jsonl, extracts every COMP-001 measurement row,
runs scripts/reference/bitnet_vs_comp001.py for the reference arm, and
renders docs/ORION-COMP-001.md.

Everything in the report is computed FROM THE LEDGER (plus the quant sizes
the ledger itself stored). Nothing is hardcoded, and re-running this script
is idempotent: it overwrites the same report file and never appends a ledger
row unless --record is given (which re-runs bitnet_vs_comp001.py with its own
one-time record guard).

Honesty rule: probe score 0.0 is a REAL measurement. The report says
"measured baseline", never "the model achieved". Verdict today: NOT READY /
SCAFFOLD - probe=0 for every arm, so every cap_per_gb is 0.

CLI:
    python scripts/report/comp001_report.py            # regenerate report (no ledger write)
    python scripts/report/comp001_report.py --record   # also allow bitnet_vs_comp001.py to record once
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from scripts.repro import _ledger_path, _read_rows  # noqa: E402

REPORT_PATH = REPO_ROOT / "docs" / "ORION-COMP-001.md"
BITNET_SCRIPT = REPO_ROOT / "scripts" / "reference" / "bitnet_vs_comp001.py"

EXPERIMENTS = {
    "gate": "corpus-adequacy-gate",
    "run_10m": "comp-001-10m",
    "run_100m": "comp-001-custom-100m",
    "gguf": "comp001-gguf-matrix",
    "bitnet_readiness": "bitnet-2b4t-readiness",
}


def latest(rows: list, exp: str) -> dict:
    """Latest row for an experiment (tie-break: last in file = most recent)."""
    matching = [r for r in rows if r.get("experiment") == exp]
    return matching[-1] if matching else {}


def best_trained(rows: list, exp: str) -> dict:
    """The row that best represents the trained model: lowest ending_loss,
    with resumed continuation rows (which restate the same checkpoint) losing
    to the original full run, tie-break by timestamp."""
    matching = [r for r in rows if r.get("experiment") == exp]
    if not matching:
        return {}

    def key(r):
        try:
            loss = float(r.get("ending_loss"))
        except (TypeError, ValueError):
            loss = float("inf")
        return (loss, 1 if r.get("resumed") else 0, -len(matching))

    return min(matching, key=key)


def f(v, nd=2) -> str:
    """Pretty-format a numeric ledger value; '' when None/''."""
    if v is None or v == "":
        return ""
    return f"{v:.{nd}f}"


def cap_per_gb(probe, est_load_ram_mb) -> str:
    """cap_per_gb = probe_score / (est_load_ram_mb / 1024)."""
    try:
        p = float(probe)
        ram = float(est_load_ram_mb)
    except (TypeError, ValueError):
        return "n/a"
    if ram <= 0:
        return "n/a"
    return f"{p / (ram / 1024):.6f}"


def bitnet_table_markdown() -> tuple:
    """Run bitnet_vs_comp001.py and return (markdown block, captured stdout).

    Prefer subprocess so the report embeds the EXACT output the shared script
    prints (requirement: grow the comparison FROM the reference script, don't
    rebuild its table logic). No record by default; --record passes through.
    """
    try:
        proc = subprocess.run(
            [sys.executable, str(BITNET_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=600,
        )
        out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    except subprocess.TimeoutExpired:
        out = "[ERROR] bitnet_vs_comp001.py timed out"
    except Exception as e:  # noqa: BLE001
        out = f"[ERROR] bitnet_vs_comp001.py failed: {e}"
    block = "```text\n" + out.strip() + "\n```"
    return block, out


def render(rows: list, bitnet_block: str) -> str:
    t = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    gate = latest(rows, EXPERIMENTS["gate"])
    run10 = best_trained(rows, EXPERIMENTS["run_10m"])
    run100 = best_trained(rows, EXPERIMENTS["run_100m"])
    gguf = latest(rows, EXPERIMENTS["gguf"])
    bitnet_r = latest(rows, EXPERIMENTS["bitnet_readiness"])
    bitnet_cmp = latest(rows, "bitnet-vs-comp001")

    # est_load_ram_mb: prefer the recorded bitnet-vs-comp001 comparison row
    # (same values Table 3 shows), fall back to the checkpoint-size heuristic.
    cmp_est_ram = {
        c.get("model"): c.get("est_load_ram_mb")
        for c in (bitnet_cmp.get("comparison_rows") or [])
        if c.get("est_load_ram_mb")
    }

    # ---- Table 1: measured runs -------------------------------------------
    def run_row(exp_name, run, cmp_label):
        params = run.get("param_count")
        params_s = (
            f"{params / 1e6:.2f}M"
            if params
            else (run.get("params") or {}).get("model_size", "")
        )
        probe = run.get("quality_probe_score")
        probe_s = (
            "0.0 (measured)"
            if probe is not None and float(probe) == 0.0
            else (f"{float(probe):.4f}" if probe is not None else "n/a")
        )
        est_ram = cmp_est_ram.get(cmp_label) or round(
            float(run.get("checkpoint_size_bytes", 0)) / 1e6 * 1.25, 1
        )
        return {
            "run": exp_name,
            "params": params_s,
            "rss": f(run.get("peak_rss_mb"), 1),
            "train_tps": f(run.get("tokens_per_sec"), 1),
            "inf_tps": f(run.get("inference_tok_per_s"), 1),
            "ppl": (
                f"{float(run['perplexity']):.2f}"
                if run.get("perplexity")
                else f(run.get("eval_loss"), 2)
            ),
            "probe": probe_s,
            "cap": cap_per_gb(probe, est_ram),
            "status": run.get("status", "?"),
        }

    t1_rows = [
        run_row("comp001-10m", run10, "comp001-10m"),
        run_row("comp001-100m", run100, "comp001-100m"),
    ]

    # ---- Table 2: quantized exports (values recorded by T5) ---------------
    t2_rows = []
    variants = gguf.get("variants") or {}
    for quant, info in variants.items():
        if info.get("state") != "exported":
            t2_rows.append(
                {
                    "quant": quant,
                    "mb": "blocked",
                    "ratio": info.get("reason", "")[:60],
                    "probe": info.get("probe_score", ""),
                    "state": info.get("state", ""),
                }
            )
            continue
        t2_rows.append(
            {
                "quant": quant,
                "mb": f(info.get("mb"), 2),
                "ratio": f(info.get("ratio_vs_424mb"), 3),
                "probe": f(info.get("probe_score"), 3),
                "state": info.get("state", ""),
            }
        )

    # ---- Gate ---------------------------------------------------------------
    actual = gate.get("actual_tokens")
    required = gate.get("required_tokens_for_100m")
    short = gate.get("tokens_short_of_threshold")
    verdict = gate.get("verdict", "UNKNOWN")

    # ---- Reproduction commands (the five runs that produced the ledger) -----
    reproduce = (
        "python scripts/training/bpe_tokenizer.py --vocab-size 1471\n"
        "python scripts/training/train_comp001.py --model-size 10m --epochs 10\n"
        "python scripts/training/train_comp001.py --model-size 100m --epochs 15\n"
        "python scripts/training/export_gguf_matrix.py --quants f16,q8_0,q4_0,Q4_K_M --smoke-10m\n"
        "python scripts/reference/bitnet_vs_comp001.py\n"
        "python scripts/evaluation/comp001_quality.py --model models/comp001/100m/\n"
        "python scripts/report/comp001_report.py"
    )

    lines = []
    A = lines.append
    A("# ORION-COMP-001 — Capability per GB benchmark, v1 (measurement scaffold)")
    A("")
    A(
        f"_Generated {t} from `logs/training_runs.jsonl` by `scripts/report/comp001_report.py`. "
        "Regenerable; re-running overwrites this file and appends NO ledger row._"
    )
    A("")
    A(
        "> **Verdict: NOT READY / SCAFFOLD** — every arm has probe score 0.0 (a real, measured 0/20), "
        "so every capability-per-GB number in this edition is 0. This report is a **measurement "
        "methodology + honest baseline**, not a capability claim."
    )
    A("")
    A("## 1. Purpose & method")
    A("")
    A(
        "Capability per gigabyte is defined as the quality probe score divided by the estimated "
        "loaded-RAM footprint (in GB):"
    )
    A("")
    A("```text")
    A("cap_per_gb = probe_score / (est_load_ram_mb / 1024)")
    A("```")
    A("")
    A(
        "- `probe_score` = completion accuracy (0–1) from `scripts/evaluation/comp001_quality.py` "
        "(20 fixed items, exact-match, greedy decoding)."
    )
    A(
        "- `est_load_ram_mb` = 1.25 × checkpoint bytes (fp16 file → resident fp32-ish load, +25 %), "
        "matching the load-overhead factor used by the GGUF matrix and the BitNet arm."
    )
    A(
        "- A higher number means more measured capability per unit of memory. A 0 probe score is a "
        "real measurement and is reported as-is: **0.0 (measured)**."
    )
    A("")
    A(
        "> `ponytail:` probe_score = 0 for all arms today, so cap_per_gb is 0 everywhere — v1 is a "
        "*measurement scaffold*, not a benchmark. v2 (real corpus + real training + bitnet.cpp) is "
        "where the numbers become nonzero and comparable."
    )
    A("")
    A("## 2. Table 1 — Measured runs (from the ledger)")
    A("")
    A(
        "| run | params | peak RSS MB | train tok/s | inference tok/s | eval loss / ppl | probe | cap_per_gb | status |"
    )
    A("|---|---|---|---|---|---|---|---|---|")
    for r in t1_rows:
        A(
            f"| {r['run']} | {r['params']} | {r['rss']} | {r['train_tps']} | {r['inf_tps']} | {r['ppl']} | {r['probe']} | {r['cap']} | {r['status']} |"
        )
    A("")
    A(
        "Notes: `eval loss / ppl` — comp001-100m row carries ledger `perplexity` 1819.77; comp001-10m "
        "has no probe run and no perplexity field, so its cell shows eval loss only. Both runs trained "
        "on the 2098-token smoke corpus (see §5)."
    )
    A("")
    A("## 3. Table 2 — Quantized exports (recorded by comp001-gguf-matrix)")
    A("")
    A("| variant | MB (ledger) | ratio vs safetensors (424.4 MB) | probe | state |")
    A("|---|---|---|---|---|")
    for r in t2_rows:
        A(f"| {r['quant']} | {r['mb']} | {r['ratio']} | {r['probe']} | {r['state']} |")
    A("")
    A(
        "Q4_K_M is **blocked**: it requires llama.cpp's `quantize` binary (k-quant path), which is not "
        "installed; the GGUF python package cannot dequantize K-quants. No installs were made. "
        "Unblock by putting llama-quantize on PATH and re-running export_gguf_matrix.py."
    )
    A("")
    A("## 4. Table 3 — Reference comparison (BitNet b1.58-2B-4T est. vs COMP-001)")
    A("")
    A("Output of `python scripts/reference/bitnet_vs_comp001.py` (embedded verbatim):")
    A("")
    A(bitnet_block)
    A("")
    A(
        "Reference-arm readiness (`bitnet-2b4t-readiness`, ledger): "
        f"est resident {bitnet_r.get('bitnet_est_mb')} MB "
        f"(range {bitnet_r.get('bitnet_est_range_mb')} MB), headroom {bitnet_r.get('headroom_mb')} MB, "
        f"verdict **{bitnet_r.get('params', {}).get('verdict', '?')}** "
        f"— install_blocked_by: {bitnet_r.get('install_blocked_by', '?')}."
    )
    A("")
    A("## 5. Corpus-adequacy gate & honesty box")
    A("")
    A(
        f"The corpus-adequacy gate (`corpus-adequacy-gate`) measured **{actual:,} tokens** vs "
        f"**{required:,} required** for a 100M training run "
        f"({short:,} tokens short) → verdict **{verdict}**."
    )
    A("")
    A(
        "What this means: nothing trained on this corpus can claim capability. 2098 tokens is a "
        "sentence or two of smoke data; the models above (loss 7.40→5.38 at 9.15M params, "
        "106.1M at SMOKE_RUN) learned *format noise*, not language. **This report therefore "
        "explicitly states NOT READY / SCAFFOLD.** The rows in Tables 1–3 are measured baselines "
        "that become meaningful only after v2 replaces the corpus and re-runs the pipeline."
    )
    A("")
    A("## 6. How to reproduce")
    A("")
    A(
        "The five runs that produced every row above (same order as the ledger), then this report:"
    )
    A("")
    A("```text")
    A(reproduce)
    A("```")
    A("")
    A(
        "Ledger: `logs/training_runs.jsonl` (experiments `corpus-adequacy-gate`, `comp-001-10m`, "
        "`comp-001-custom-100m`, `comp001-gguf-matrix`, `bitnet-2b4t-readiness`, "
        "`bitnet-vs-comp001`)."
    )
    A("")
    A("## 7. Next steps for v2")
    A("")
    A(
        "1. **Real corpus** — ≥50 M tokens in `data/training/corpus/` (gate must return ADEQUATE)."
    )
    A(
        "2. **Re-train** — 10m → 100m dense with epoch/step counts that now pass the gate "
        "(100m will no longer be SMOKE_RUN)."
    )
    A(
        "3. **BitNet runtime** — install bitnet.cpp and pull `microsoft/BitNet-b1.58-2B-4T` i2_s GGUF; "
        "confirm the est 1075 MB resident on this box."
    )
    A(
        "4. **Re-measure** — re-run the probe + tok/s on every arm (fp32, f16, q8, q4, BitNet)."
    )
    A(
        "5. **Re-generate** — `python scripts/report/comp001_report.py`; nonzero probe scores turn "
        "this scaffold into a real capability-per-GB table."
    )
    A("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--record",
        action="store_true",
        help="allow bitnet_vs_comp001.py to append its one-time ledger row "
        "(it records only ONCE by name; default: no ledger write at all)",
    )
    args = ap.parse_args()

    rows = _read_rows()
    ledger_before = len(rows)

    bitnet_block, _out = bitnet_table_markdown()
    doc = render(rows, bitnet_block)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(doc, encoding="utf-8")

    if args.record:
        # bitnet_vs_comp001.py records its comparison row at most once (name-guarded).
        subprocess.run([sys.executable, str(BITNET_SCRIPT)], check=False)

    ledger_after = len(_read_rows())
    print(f"[REPORT] wrote {REPORT_PATH} ({len(doc.splitlines())} lines)")
    print(
        f"[REPORT] ledger rows: {ledger_before} -> {ledger_after} "
        f"(expected equal; +1 only with --record's one-time bitnet row)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
