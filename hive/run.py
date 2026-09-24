"""CLI entry: `python -m hive.run [--help]`.

Run one simulated or network fleet training session and record it in the ORION
experiment ledger (logs/training_runs.jsonl) via scripts/repro.py.

Examples:
    # 1. Local single-worker baseline (10M model):
    python -m hive.run --model 10m --workers 1 --rounds 6 --tokens 60000 --scope single-baseline

    # 2. Local 2-worker simulation baseline (10M model):
    python -m hive.run --model 10m --workers 2 --rounds 6 --tokens 60000 --scope simulated-baseline

    # 3. Real LAN Coordinator listening for 1 remote network worker (+ 1 local worker):
    python -m hive.run --model 10m --workers 2 --network-workers 1 --listen-host 0.0.0.0 --rounds 6 --tokens 60000 --scope lan-baseline
"""

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (
    str(REPO_ROOT),
    str(REPO_ROOT / "scripts"),
    str(REPO_ROOT / "scripts" / "training"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import psutil  # noqa: E402

from hive.coordinator import HiveCoordinator  # noqa: E402
from scripts.repro import record_experiment  # noqa: E402


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        prog="hive.run", description="ORION-HIVE simulated or network fleet training"
    )
    ap.add_argument("--model", choices=("phone", "tiny", "10m", "30m"), default="tiny")
    ap.add_argument(
        "--workers",
        type=int,
        default=2,
        help="fleet size (1, 2, 4 or custom count with network workers)",
    )
    ap.add_argument(
        "--network-workers",
        type=int,
        default=0,
        help="number of remote network workers connecting over TCP",
    )
    ap.add_argument(
        "--listen-host",
        type=str,
        default=None,
        help="IP address to bind coordinator for network workers (e.g. 0.0.0.0 or LAN IP)",
    )
    ap.add_argument(
        "--listen-port",
        type=int,
        default=8765,
        help="TCP port to bind coordinator for network workers (default: 8765)",
    )
    ap.add_argument(
        "--hf-dataset",
        type=str,
        default=None,
        help="Hugging Face dataset name/repo to train on (e.g. wikitext, imdb)",
    )
    ap.add_argument(
        "--sqlite-db",
        type=str,
        default=None,
        help="Path to custom SQLite database file for dataset extraction",
    )
    ap.add_argument("--rounds", type=int, default=6, help="aggregation rounds")
    ap.add_argument(
        "--tokens",
        type=int,
        default=120000,
        help="tokens trained per round across the whole fleet",
    )
    ap.add_argument(
        "--dropout-every",
        type=int,
        default=0,
        help="kill + rejoin one worker every M rounds (0 = off)",
    )
    ap.add_argument("--out", type=str, default="models/hive", help="artifact dir")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--resume",
        type=str,
        default=None,
        help="checkpoint file to resume the global model from",
    )
    ap.add_argument(
        "--server-momentum",
        type=float,
        default=0.0,
        help="server SGD momentum (0.0 = exact token-weighted FedAvg)",
    )
    ap.add_argument("--batch", type=int, default=4, help="blocks per worker mini-batch")
    ap.add_argument("--worker-lr", type=float, default=5e-3, help="worker local SGD lr")
    ap.add_argument("--keep-ckpts", type=int, default=1, help="keep N checkpoints")
    ap.add_argument(
        "--scope",
        type=str,
        default="measured-simulation",
        help="verified-mechanics | measured-simulation | single-baseline | lan-baseline",
    )
    return ap.parse_args(argv)


def _compat_hardware() -> dict:
    return {
        "cpu_cores": psutil.cpu_count(logical=False),
        "cpu_threads": psutil.cpu_count(logical=True),
        "available_ram_gb": round(psutil.virtual_memory().available / (1024**3), 2),
        "free_disk_d_gb": round(psutil.disk_usage(str(REPO_ROOT)).free / (1024**3), 2),
        "git_commit": _git_commit(),
    }


def _git_commit() -> str:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def main(argv=None) -> int:
    args = parse_args(argv)
    coord = HiveCoordinator(
        model_size=args.model,
        workers=args.workers,
        rounds=args.rounds,
        tokens=args.tokens,
        dropout_every=args.dropout_every,
        seed=args.seed,
        out_dir=Path(args.out),
        batch=args.batch,
        worker_lr=args.worker_lr,
        server_momentum=args.server_momentum,
        resume=args.resume,
        keep_ckpts=args.keep_ckpts,
        verbose=True,
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        network_workers=args.network_workers,
        hf_dataset=args.hf_dataset,
        sqlite_db=args.sqlite_db,
    )
    record = coord.run()
    record["hardware"] = _compat_hardware()
    record["scope"] = args.scope
    record["speedup_claim"] = "no-linear-speedup"
    record["experiment_name"] = f"hive-{args.workers}w-{args.model}"

    params = {
        "model": args.model,
        "workers": args.workers,
        "network_workers": args.network_workers,
        "rounds": args.rounds,
        "tokens_per_round": args.tokens,
        "dropout_every": args.dropout_every,
        "seed": args.seed,
        "batch": args.batch,
        "worker_lr": args.worker_lr,
        "server_momentum": args.server_momentum,
        "scope": args.scope,
    }
    row = record_experiment(f"hive-{args.workers}w-{args.model}", params, record)
    print(_summary(record))
    print(
        f"[LEDGER] experiment=hive-{args.workers}w-{args.model} run_id={record.get('run_id')} "
        f"status={record.get('status')} -> logs/training_runs.jsonl"
    )
    return 0


def _summary(r: dict) -> str:
    roles = json.dumps(r["topology"]["roles"])
    return (
        f"\n{'=' * 64}\n  HIVE RUN SUMMARY  {r['run_id']}\n{'=' * 64}\n"
        f"  model={r['model_size']} ({r['n_params']:,} params) fleet={r['topology']['n_workers']} "
        f"devices roles={roles}\n"
        f"  rounds={r['rounds']} tokens_trained={r['total_tokens_trained']:,} "
        f"comm_bytes={r['comm_bytes']:,} comm_overhead={r['comm_overhead_pct']}%\n"
        f"  wall={r['wall_clock_s']}s (incl fleet spawn) | training_loop={r['training_loop_s']}s "
        f"| tok/s={r['tokens_per_s']} (loop: {r['tokens_per_s_loop']})\n"
        f"  val_loss={r['val_loss']} start_loss={r['starting_loss']} end_loss={r['ending_loss']}\n"
        f"  failure_rate={r['failure_rate']} resume_verified={r['resume_verified']} "
        f"peak_rss={r['peak_rss_mb']}MB artifacts={r['artifacts_bytes']:,}B\n"
        f"  scope={r.get('scope')} speedup_claim={r.get('speedup_claim')}\n"
    )


if __name__ == "__main__":
    sys.exit(main())
