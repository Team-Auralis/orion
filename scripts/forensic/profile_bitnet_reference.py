#!/usr/bin/env python3
"""F6 BitNet reference line (light) for COMP-001 profiling.

Reuses the T7-measured official reference already recorded in
logs/training_runs.jsonl (run bitnet-ref-31284d32, status VERIFIED,
2026-09-24 06:47Z, same box) — no re-measure: the 1132.8 MB i2_s GGUF would
need ~1.2 GB RSS to load and free RAM is well under that now, and the box was
just re-probed in this F6 (RAM ~0.9 GB class), so reuse is the honest, cheap
path. Label: reference model, NOT quality-comparable to 100m.

Output: logs/forensic/profiling/bitnet_reference.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "logs" / "forensic" / "profiling"
RUNS = REPO_ROOT / "logs" / "training_runs.jsonl"


def main() -> None:
    rows = []
    for line in RUNS.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    refs = [r for r in rows if r.get("experiment") == "bitnet-2b4t-reference"]
    if not refs:
        print(f"[ERROR] no bitnet-2b4t-reference run found in {RUNS}")
        sys.exit(2)
    r = refs[0]
    p = r.get("params", {})
    out = {
        "reference_line": {
            "model": "microsoft/BitNet-b1.58-2B-4T-gguf (bitnet.cpp i2_s, external official reference)",
            "file_mb": r.get("file_mb"),
            "tok_per_s": r.get("tok_per_s"),
            "peak_rss_mb": r.get("peak_rss_mb"),
            "threads": p.get("threads") or r.get("threads"),
            "prompt": r.get("prompt"),
            "params_b": p.get("params_b"),
            "quantization": p.get("quantization"),
            "runtime": p.get("runtime"),
            "status": r.get("status"),
            "source": f"logs/training_runs.jsonl run {r.get('run_id')}",
        },
        "not_quality_comparable": (
            "BitNet-b1.58-2B-4T is a different size/arch/family than comp001-100m-real; "
            "the only valid 100m-vs-BitNet comparison is mechanical (speed / memory)."
        ),
        "reused_not_remeasured": (
            "T7-measured 2026-09-24 06:47Z on this same box; re-measure skipped because "
            "loading the 1132.8 MB GGUF wants ~1.2 GB peak RSS while free RAM is ~0.9 GB "
            "class (would risk OOM on the constrained box)."
        ),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "bitnet_reference.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )
    print("[BITNET REF]", json.dumps(out["reference_line"]))
    print(f"[DONE] wrote {OUT_DIR / 'bitnet_reference.json'}")


if __name__ == "__main__":
    main()
