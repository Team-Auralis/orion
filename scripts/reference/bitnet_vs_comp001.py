#!/usr/bin/env python3
"""BitNet b1.58-2B-4T vs COMP-001 comparison scaffold (Task 6 -> feeds T7).

Builds the table the ORION-COMP-001 report (T7) needs: the reference arm
(bitnet-2b4t-est) next to the two custom COMP-001 arms. COMP-001 numbers are
REAL: read from logs/training_runs.jsonl (experiments comp-001-10m and
comp-001-custom-100m) plus the model.safetensors bytes at each run's
checkpoint_path. BitNet numbers are ESTIMATES (the model is not on this box),
so est_tok_per_s and quality are explicitly labeled.

est_tok_per_s heuristic (cited from memory, label ESTIMATE): a CPU model runs
roughly 1-20 tok/s per 1B parameters, so for P params the band is
(1 / (P/1e9)) .. (20 / (P/1e9)) tok/s. For 2.4B that is 0.4-8.3 tok/s.

CLI:
    python scripts/reference/bitnet_vs_comp001.py            # print + record
    python scripts/reference/bitnet_vs_comp001.py --no-record
"""

import argparse
import json
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from scripts.repro import _ledger_path, _read_rows, record_experiment  # noqa: E402

LEDGER_EXPERIMENTS = ("comp-001-10m", "comp-001-custom-100m")
BITNET_LEDGER_NAME = "bitnet-vs-comp001"

# Reference-arm facts (research fleet, NOT measured here - the model is absent):
BITNET_PARAMS = 2.4e9
BITNET_EST_WEIGHTS_MB = 400.0  # ~0.4 GB non-embedding at ~1.58 bit
BITNET_EST_LOAD_RAM_MB = 1075.0  # midpoint of 0.9-1.2 GB resident estimate
LOAD_OVERHEAD_FACTOR = (
    1.25  # fp16 file -> resident fp32-ish load (+25%), mirrors comp001 gguf rows
)


def tok_per_s_band(params: float) -> tuple:
    """(lo, hi) tok/s heuristic: 1-20 tok/s per 1B params on CPU (ESTIMATE)."""
    per_b = params / 1e9
    return round(1 / per_b, 2), round(20 / per_b, 2)


def real_params_from_safetensors(path: Path) -> float:
    """Count params from the safetensors header only (no tensor data load)."""
    try:
        import numpy as np
        from safetensors import safe_open

        with safe_open(str(path), framework="numpy") as f:
            keys = f.keys()
            return sum(int(np.prod(f.get_slice(k).get_shape())) for k in keys)
    except Exception:
        return 0.0


def weights_file_mb(path: Path) -> float:
    try:
        return round(path.stat().st_size / (1024**2), 2)
    except Exception:
        return 0.0


def ledger_rows() -> dict:
    """Return {experiment: latest COMPLETED-ish row} from logs/training_runs.jsonl."""
    best = {}
    for line in _ledger_path().read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("experiment") not in LEDGER_EXPERIMENTS:
            continue
        cur = best.get(row["experiment"])
        if cur is None or row.get("timestamp", "") >= cur.get("timestamp", ""):
            best[row["experiment"]] = row
    return best


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--no-record",
        action="store_true",
        help="do not append a bitnet-vs-comp001 ledger row",
    )
    args = ap.parse_args()

    experiment_rows = ledger_rows()
    headers = (
        "model",
        "params",
        "weights_file_mb",
        "est_load_ram_mb",
        "est_tok_per_s",
        "quality_probe_score",
        "status",
    )
    rows = []

    for exp in LEDGER_EXPERIMENTS:
        row = experiment_rows.get(exp)
        if row is None:
            print(f"[WARN] no ledger row for experiment {exp}; skipping")
            continue
        label = "comp001-10m" if exp == "comp-001-10m" else "comp001-100m"
        ckpt = Path(row.get("checkpoint_path") or "")
        st_file = (ckpt / "model.safetensors") if ckpt.is_dir() else ckpt
        weights_mb = weights_file_mb(st_file)

        params = real_params_from_safetensors(st_file)
        if params <= 0:
            # Fall back to the run's declared model_size, then the name suffix.
            declared = row.get("params", {}).get("model_size")
            params = (
                float(declared[:-1]) * 1e6 if declared and declared[-1] == "m" else 0.0
            )

        lo, hi = tok_per_s_band(params) if params else (0.0, 0.0)
        probe = row.get("quality_probe_score")
        quality = "not_recorded" if probe is None else round(probe, 4)
        rows.append(
            (
                label,
                f"{params / 1e6:.1f}M",
                weights_mb,
                round(weights_mb * LOAD_OVERHEAD_FACTOR, 1),
                f"{lo:.1f}-{hi:.1f} (ESTIMATE)",
                quality,
                row.get("status", "?"),
            )
        )

    lo, hi = tok_per_s_band(BITNET_PARAMS)
    rows.append(
        (
            "bitnet-2b4t-est",
            "2.4B",
            f"{BITNET_EST_WEIGHTS_MB:.0f} (ESTIMATE; no file on disk)",
            f"{BITNET_EST_LOAD_RAM_MB:.0f} (ESTIMATE)",
            f"{lo:.1f}-{hi:.1f} (ESTIMATE)",
            "NOT_MEASURED_NEEDS_RUNTIME",
            "NEEDS_RUNTIME",
        )
    )

    # ---- print the comparison table -----------------------------------------
    widths = [
        max(len(str(r[i])) for r in rows + [headers]) for i in range(len(headers))
    ]

    def fmt(values):
        return "  ".join(str(v).ljust(w) for v, w in zip(values, widths))

    print("=" * (sum(widths) + 4 * (len(widths) - 1)))
    print(
        "ORION-COMP-001 comparison scaffold (T7): custom COMP-001 arms vs BitNet 2.4B reference arm"
    )
    print("=" * (sum(widths) + 4 * (len(widths) - 1)))
    print(fmt(headers))
    print("-" * (sum(widths) + 4 * (len(widths) - 1)))
    for r in rows:
        print(fmt(r))
    print("-" * (sum(widths) + 4 * (len(widths) - 1)))
    print("COMP-001 params/weights are REAL (ledger + model.safetensors on disk).")
    print("BitNet row is ESTIMATE (model not downloaded; bitnet.cpp not installed).")
    print("est_tok_per_s heuristic cited from memory: 1-20 tok/s per 1B params on CPU.")

    # ---- record a bitnet-vs-comp001 row if the name isn't taken --------------
    if not args.no_record:
        existing = [
            r for r in _read_rows() if r.get("experiment") == BITNET_LEDGER_NAME
        ]
        if existing:
            print(
                f"\n[LEDGER] bitnet-vs-comp001 already recorded ({len(existing)} row(s)); skipping"
            )
        else:
            record = {
                "run_id": f"bitnet-vs-comp001-{uuid.uuid4().hex[:8]}",
                "status": "COMPLETED",
                "base_model_name": "microsoft/BitNet-b1.58-2B-4T",
                "model_type": "comparison-scaffold (T7 input; bitnet not run)",
                "checkpoint_path": "",
                "num_samples": 0,
                "error_message": "",
                "comparison_rows": [
                    {
                        "model": r[0],
                        "params": r[1],
                        "weights_file_mb": r[2],
                        "est_load_ram_mb": r[3],
                        "est_tok_per_s": r[4],
                        "quality_probe_score": r[5],
                        "status": r[6],
                    }
                    for r in rows
                ],
            }
            record_experiment(
                BITNET_LEDGER_NAME,
                {"rows": len(rows), "source": "ledger+local+estimate"},
                record,
            )
            print(
                f"\n[LEDGER] appended bitnet-vs-comp001 row ({len(rows)} comparison rows)"
            )
    else:
        print("\n[LEDGER] skipped (--no-record)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
