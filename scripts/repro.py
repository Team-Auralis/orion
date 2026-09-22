#!/usr/bin/env python3
"""Reproducibility harness - merged experiment manifest (T1).

One canonical entry point for every training/export script to record a
reproducible run: a single merged JSON row in logs/training_runs.jsonl
carrying the legacy TrainingRunRecord fields plus `experiment` / `params`
and a nested `repro` block (hardware, pip-freeze environment,
dataset/tokenizer hashes, hyperparams).

Merged on purpose: this task explicitly avoids five separate manifest files.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psutil
import torch

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_LOG_PATH = REPO_ROOT / "logs" / "training_runs.jsonl"

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "training"))

from orion_runner import experiment, param, run_experiment  # noqa: E402

try:
    from e2e_training_smoke_test import (  # noqa: E402
        get_git_commit as _get_git_commit,
        compute_file_sha256 as _compute_sha256,
    )
except Exception:  # pragma: no cover - standalone fallbacks

    def _get_git_commit() -> str:
        try:
            res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=True,
            )
            return res.stdout.strip()
        except Exception:
            return "unknown"

    def _compute_sha256(path: Path) -> str:
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()


def _ledger_path() -> Path:
    """Audit-log location; honors the ORION_RUNS_LOG override like the runner."""
    override = os.environ.get("ORION_RUNS_LOG")
    return Path(override) if override else RUNS_LOG_PATH


def _read_rows() -> list:
    path = _ledger_path()
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _resolve(path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


def _file_sha256(path) -> str:
    """SHA-256 of a file path ("" when the file is missing, None when no path)."""
    if path is None:
        return None
    p = _resolve(path)
    if not p.exists():
        return ""
    return _compute_sha256(p)


def _pip_freeze() -> str:
    try:
        res = subprocess.run(
            [sys.executable, "-m", "pip", "freeze"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return ""


def gather_repro_ctx(dataset_path, tokenizer_path=None, hyperparams=None) -> dict:
    """One merged reproducible-run context dict: hardware, environment, hashes, hyperparams."""
    vmem = psutil.virtual_memory()
    try:
        free_disk_gb = shutil.disk_usage(REPO_ROOT).free / (1024**3)
    except Exception:
        free_disk_gb = 0.0
    hardware = {
        "cpu_cores": psutil.cpu_count(logical=False),
        "cpu_threads": psutil.cpu_count(logical=True),
        "total_ram_gb": round(vmem.total / (1024**3), 2),
        "available_ram_gb": round(vmem.available / (1024**3), 2),
        "free_disk_d_gb": round(free_disk_gb, 2),
        "git_commit": _get_git_commit(),
        "torch_version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return {
        "hardware": hardware,
        "environment": _pip_freeze(),
        "dataset_hash": _file_sha256(dataset_path),
        "tokenizer_hash": (
            _file_sha256(tokenizer_path) if tokenizer_path is not None else None
        ),
        "hyperparams": dict(hyperparams) if hyperparams else {},
    }


def _infer_param_type(value):
    if isinstance(value, bool):
        return bool
    if isinstance(value, int):
        return int
    if isinstance(value, float):
        return float
    if isinstance(value, str):
        return str
    return None


def record_experiment(name: str, params: dict, record: dict) -> dict:
    """Register `name` on the fly and run it through orion_runner's lifecycle, so
    exactly one COMPLETED row lands in the ledger: the record's legacy fields plus
    `experiment`/`params` and a nested `repro` block from gather_repro_ctx."""
    if not isinstance(record, dict):
        raise TypeError("record must be a dict of TrainingRunRecord-style fields")
    params = dict(params) if params else {}
    ctx = gather_repro_ctx(
        record.get("dataset_path"), record.get("tokenizer_path"), params
    )
    merged = dict(record)
    merged["repro"] = ctx

    def _fn(p):
        return merged

    # Declare every hyperparam so run_experiment's resolve accepts the values dict.
    for key, value in params.items():
        _fn = param(key, default=value, type=_infer_param_type(value))(_fn)
    exp = experiment(name)
    exp(_fn)
    try:
        return run_experiment(name, values=params if params else None)
    finally:
        # Registry lives on the experiment module; unregister so the same
        # name can be reused by a later call in this process.
        sys.modules["orion_runner.experiment"]._EXPERIMENTS.pop(name, None)


def _run_check() -> int:
    data_file = REPO_ROOT / "data" / "training" / "tiny_train.jsonl"
    data_file.parent.mkdir(parents=True, exist_ok=True)
    if not data_file.exists():
        data_file.write_text(
            json.dumps({"instruction": "PROBE", "response": "OK"}) + "\n",
            encoding="utf-8",
        )

    rows_before = len(_read_rows())
    hyperparams = {"epochs": 1, "lr": 1e-4, "seed": 42}
    ctx = gather_repro_ctx(data_file, hyperparams=hyperparams)

    record = {
        "run_id": f"repro-check-{uuid.uuid4().hex[:8]}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "COMPLETED",
        "base_model_name": "repro-check-dummy",
        "model_type": "TrainingRunRecord",
        "dataset_path": str(data_file),
        "dataset_hash": ctx["dataset_hash"],
        "num_samples": 1,
        "seed": hyperparams["seed"],
        "epochs": hyperparams["epochs"],
        "learning_rate": hyperparams["lr"],
        "starting_loss": 1.0,
        "ending_loss": 0.9,
        "loss_reduction_pct": 10.0,
        "eval_loss": 0.95,
        "checkpoint_path": "",
        "output_differs": True,
        "hardware": ctx["hardware"],
        "error_message": "",
    }
    record_experiment("repro-check", hyperparams, record)

    rows = _read_rows()
    added = len(rows) - rows_before
    row = rows[-1]
    repro = row.get("repro") or {}
    need_top = ("experiment", "params", "repro")
    need_repro = (
        "hardware",
        "environment",
        "dataset_hash",
        "tokenizer_hash",
        "hyperparams",
    )
    ok = (
        added == 1
        and row.get("status") == "COMPLETED"
        and all(k in row for k in need_top)
        and all(k in repro for k in need_repro)
    )
    print(
        f"[CHECK] appended {added} row(s) to {_ledger_path().name} "
        f"(run_id={row.get('run_id')}, status={row.get('status')})"
    )
    if ok:
        print(f"[CHECK] repro context present: {', '.join(sorted(repro.keys()))}")
        return 0
    print(f"[CHECK] FAILED - row keys: {sorted(row.keys())}")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="ORION reproducibility harness (merged experiment manifest)"
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="run one throwaway repro smoke experiment end-to-end",
    )
    args = ap.parse_args()
    if args.check:
        return _run_check()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
