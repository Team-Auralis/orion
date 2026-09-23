#!/usr/bin/env python3
"""BitNet b1.58-2B-4T readiness harness (Task 6, reference arm).

Honest "can we run the 2.4B reference model here, under 3 GB?" check for the
ORION three-track plan (Track C = BitNet 2.4B under 3 GB). This box is a
7.7 GB RAM CPU-only laptop; the reference model is `microsoft/BitNet-b1.58-2B-4T`
(2.4B params, native ternary +-1/0 1.58-bit weights, ~0.4 GB non-embedding at
1 bit), designed to run on CPU via the bitnet.cpp runtime (a llama.cpp fork
with ternarized I1_S kernels).

This script ONLY measures and estimates. It never downloads the ~2 GB model,
never installs binaries, never force-downloads anything. The concrete
download/run path lives in scripts/reference/bitnet_install.md.

Memory estimate (documented, from the research fleet brief):
    weights at ~1.58-bit ............ ~0.4 GB non-embedding
    embeddings/lm_head + activations/KV/overhead ~0.5-0.8 GB
    total resident estimate ......... ~0.9-1.2 GB  (midpoint 1.05 GB)
    headroom vs the 3 GB guard ...... 3.0 - 1.05   = ~1.95 GB

Verdicts:
    RUNNABLE       runtime present + free RAM >= estimate
    NEEDS_RUNTIME  bitnet.cpp binaries missing (the honest verdict here)
    NO_HEADROOM    runtime present but free RAM < estimate

CLI:
    python scripts/reference/bitnet_readiness.py             # measure + record
    python scripts/reference/bitnet_readiness.py --fetch     # + hub metadata HEAD (opt-in, offline-safe, no download)
    python scripts/reference/bitnet_readiness.py --no-record # measure only, no ledger row
"""

import argparse
import json
import shutil
import sys
import time
import uuid
from pathlib import Path

import psutil

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from scripts.repro import (
    REPO_ROOT as _REPRO_ROOT,
    _ledger_path,
    _read_rows,
    record_experiment,
)  # noqa: E402

BITNET_REPO_ID = "microsoft/BitNet-b1.58-2B-4T"
GGUF_REPO_ID = (
    "microsoft/BitNet-b1.58-2B-4T-gguf"  # community pre-converted I1_S GGUF host
)
EST_WEIGHTS_GB = 0.4  # non-embedding weight footprint at ~1.58 bit
EST_OVERHEAD_LOW_GB = 0.5  # embeddings/lm_head + activations / KV / runtime overhead
EST_OVERHEAD_HIGH_GB = 0.8
EST_LOW_GB = EST_WEIGHTS_GB + EST_OVERHEAD_LOW_GB  # 0.9
EST_HIGH_GB = EST_WEIGHTS_GB + EST_OVERHEAD_HIGH_GB  # 1.2
EST_MID_GB = round((EST_LOW_GB + EST_HIGH_GB) / 2, 2)  # 1.05
GB_GUARD = 3.0
HEADROOM_VS_GUARD_GB = round(GB_GUARD - EST_MID_GB, 2)  # 1.95

# Executables bitnet.cpp ships (build/bin/...); any one present means the
# runtime is (or could be) usable. Absence is the honest blocker on this box.
# NOTE: deliberately NOT checking plain "run"/"run.exe" -- on Windows those
# collide with unrelated PATH entries (e.g. nvm's run.CMD) and produced a
# false-positive verdict in the first draft.
RUNTIME_BIN_NAMES = ("bitnet", "bitnet.exe", "llama-b1.58-run", "llama-b1.58-run.exe")


def detect_runtime() -> tuple:
    """Return (present: bool, found: list[str], checked: list[str]).

    Scrubs PATH only - never installs anything, never builds anything.
    """
    checked = []
    found = []
    for name in RUNTIME_BIN_NAMES:
        located = shutil.which(name)
        checked.append(name)
        if located:
            found.append(f"{name} -> {located}")
    # Local source clone without a build also counts as "not ready".
    local_clone = REPO_ROOT / "third_party" / "bitnet.cpp"
    if local_clone.exists():
        checked.append("third_party/bitnet.cpp (source only)")
        if (local_clone / "build" / "bin").exists():
            found.append("third_party/bitnet.cpp/build/bin")
    return bool(found), found, checked


def hub_gguf_check() -> dict:
    """Opt-in metadata-only probe of the HF hub (no download).

    Returns {"ok": bool, "repos": {...}, "note": str}. Degrades gracefully:
    missing package, offline box, or any error -> {"ok": False, "note": ...}.
    """
    result = {"ok": False, "repos": {}, "note": ""}
    try:
        import huggingface_hub  # noqa: F401
    except Exception as exc:  # pragma: no cover
        result["note"] = f"huggingface_hub not importable ({exc}); rely on the doc"
        return result
    try:
        from huggingface_hub import HfApi

        api = HfApi()
        for repo in (BITNET_REPO_ID, GGUF_REPO_ID):
            info = api.model_info(
                repo_id=repo,
                files_metadata=True,
                timeout=8.0,
                token=None,
            )
            gguf_names = [
                s.rfilename
                for s in info.siblings
                if s.rfilename.lower().endswith(".gguf")
            ]
            sizes = {s.rfilename: s.size for s in info.siblings if s.size is not None}
            result["repos"][repo] = {
                "exists": True,
                "gguf_files": gguf_names,
                "total_hf_bytes": sum(sizes.get(f, 0) for f in gguf_names),
            }
        result["ok"] = True
        result["note"] = (
            "hub reachable; repo ids + gguf file names confirmed (metadata only, nothing downloaded)"
        )
    except Exception as exc:
        result["note"] = (
            f"hub unreachable or offline ({type(exc).__name__}: {exc}); no download attempted"
        )
    return result


def measure_box() -> dict:
    vmem = psutil.virtual_memory()
    try:
        disk = shutil.disk_usage(REPO_ROOT)
        disk_free_gb = round(disk.free / (1024**3), 2)
    except Exception:
        disk_free_gb = 0.0
    return {
        "available_ram_mb": round(vmem.available / (1024**2), 1),
        "available_ram_gb": round(vmem.available / (1024**3), 2),
        "total_ram_gb": round(vmem.total / (1024**3), 2),
        "cpu_cores": psutil.cpu_count(logical=False),
        "cpu_threads": psutil.cpu_count(logical=True),
        "free_disk_d_gb": disk_free_gb,
    }


def verdict(runtime_present: bool, headroom_mb: float, install_blocked_by: str) -> str:
    if not runtime_present:
        return "NEEDS_RUNTIME"  # honest: bitnet.cpp is the actual blocker
    if headroom_mb < 0:
        return "NO_HEADROOM"
    return "RUNNABLE"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--fetch",
        action="store_true",
        help="opt-in: HEAD-style hub metadata check (model_info, files_metadata) "
        "to confirm the repo ids + available .gguf files. No download. Offline-safe.",
    )
    ap.add_argument(
        "--no-record",
        action="store_true",
        help="do not append a bitnet-2b4t-readiness row to the ledger",
    )
    args = ap.parse_args()

    box = measure_box()
    runtime_present, runtime_found, runtime_checked = detect_runtime()

    est_mid_mb = round(EST_MID_GB * 1024, 1)
    headroom_mb = round(box["available_ram_mb"] - est_mid_mb, 1)
    guard_headroom_mb = round(HEADROOM_VS_GUARD_GB * 1024, 1)

    install_blocked_by = "missing bitnet.cpp binaries"
    if not runtime_present:
        install_blocked_by += (
            " (checked " + ", ".join(runtime_checked) + " on PATH + third_party)"
        )
    verdict_str = verdict(runtime_present, headroom_mb, install_blocked_by)

    hub = (
        hub_gguf_check()
        if args.fetch
        else {
            "ok": False,
            "note": "hub probe not requested (use --fetch)",
        }
    )

    # ---- print the table + verdict -----------------------------------------
    print("=" * 72)
    print("BitNet b1.58-2B-4T readiness harness (reference arm, Task 6)")
    print("=" * 72)
    print(f"\nmodel          : {BITNET_REPO_ID} (2.4B params, ternary 1.58-bit)")
    print(f"runtime        : bitnet.cpp (llama.cpp fork, I1_S gguf)")
    print(f"\n-- memory estimate (documented) --")
    print(f"  weights @ ~1.58 bit (non-embedding) : {EST_WEIGHTS_GB:.1f} GB")
    print(
        f"  embeddings/lm_head + activations/KV  : {EST_OVERHEAD_LOW_GB:.1f}-{EST_OVERHEAD_HIGH_GB:.1f} GB"
    )
    print(
        f"  resident estimate                   : {EST_LOW_GB:.1f}-{EST_HIGH_GB:.1f} GB  (mid {EST_MID_GB:.2f} GB = {est_mid_mb:.0f} MB)"
    )
    print(
        f"  headroom vs {GB_GUARD:.0f} GB guard                : {HEADROOM_VS_GUARD_GB:.2f} GB ({guard_headroom_mb:.0f} MB)"
    )
    print(f"\n-- measured box --")
    print(
        f"  RAM total / available: {box['total_ram_gb']:.2f} / {box['available_ram_gb']:.2f} GB  ({box['available_ram_mb']:.0f} MB free)"
    )
    print(f"  CPU cores / threads   : {box['cpu_cores']} / {box['cpu_threads']}")
    print(f"  disk free on D:       : {box['free_disk_d_gb']:.2f} GB")
    print(f"\n-- runtime check --")
    print(
        f"  bitnet.cpp binaries   : {'PRESENT: ' + ', '.join(runtime_found) if runtime_present else 'NOT FOUND (checked: ' + ', '.join(runtime_checked) + ')'}"
    )
    print(f"\n-- hub HEAD check (metadata only) --")
    print(f"  {hub['note']}")
    for repo, rep in hub.get("repos", {}).items():
        files = rep["gguf_files"] or ["(no .gguf siblings on this repo)"]
        print(f"  {repo}: {', '.join(files)}")

    print(f"\n-- hard numbers --")
    print(
        f"  headroom_mb           : {headroom_mb:,.0f} MB  (= available RAM {box['available_ram_mb']:,.0f} - estimate {est_mid_mb:,.0f})"
    )
    print(f"  install_blocked_by    : {install_blocked_by}")
    print(f"\n  VERDICT: {verdict_str}")

    # ---- record via the repro ledger ----------------------------------------
    if not args.no_record:
        params = {
            "estimate_gb": EST_MID_GB,
            "estimate_range_gb_low": EST_LOW_GB,
            "estimate_range_gb_high": EST_HIGH_GB,
            "headroom_vs_3gb_guard_gb": HEADROOM_VS_GUARD_GB,
            "verdict": verdict_str,
        }
        record = {
            "run_id": f"bitnet-readiness-{uuid.uuid4().hex[:8]}",
            "status": "COMPLETED",
            "base_model_name": BITNET_REPO_ID,
            "model_type": "bitnet-1.58-bit (reference arm; not run on this box)",
            "checkpoint_path": "",
            "num_samples": 0,
            "error_message": "",
            "bitnet_est_mb": est_mid_mb,
            "bitnet_est_range_mb": [
                round(EST_LOW_GB * 1024),
                round(EST_HIGH_GB * 1024),
            ],
            "headroom_mb": headroom_mb,
            "available_ram_mb": box["available_ram_mb"],
            "install_blocked_by": install_blocked_by,
            "hub_check": hub,
        }
        record_experiment("bitnet-2b4t-readiness", params, record)
        rows = _read_rows()
        last = rows[-1] if rows else {}
        print(
            f"\n[LEDGER] appended bitnet-2b4t-readiness row: status={last.get('status')} "
            f"experiment={last.get('experiment')} headroom_mb={last.get('headroom_mb')}"
        )
    else:
        print("\n[LEDGER] skipped (--no-record)")

    print("\nNext step: see scripts/reference/bitnet_install.md for the exact")
    print("Windows build + download + run path (NOT performed here by design).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
