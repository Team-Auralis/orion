#!/usr/bin/env python3
"""join_hive.py — One-command script for teammates and devices to join the ORION-HIVE fleet.

Usage:
    # 1. Standard teammate laptop:
    python join_hive.py --host <COORDINATOR_IP>

    # 2. Android / Termux / Low-resource phone:
    python join_hive.py --host <COORDINATOR_IP> --model phone --threads 2

    # 3. Dedicated evaluation worker:
    python join_hive.py --host <COORDINATOR_IP> --role eval

    # 4. Custom Hugging Face dataset stream:
    python join_hive.py --host <COORDINATOR_IP> --hf-dataset wikitext
"""

import argparse
import os
import platform
import socket
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
for _p in (
    str(REPO_ROOT),
    str(REPO_ROOT / "scripts"),
    str(REPO_ROOT / "scripts" / "training"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def parse_args():
    parser = argparse.ArgumentParser(
        description="ORION-HIVE Remote Node Join Client (Phone to Multi-Laptop Fleet)"
    )
    parser.add_argument(
        "--host",
        type=str,
        required=True,
        help="IP address of the coordinator laptop (shown on dashboard, e.g. 192.168.29.144)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="TCP port of the coordinator (default: 8765)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="10m",
        choices=("phone", "tiny", "10m", "30m"),
        help="Model architecture tier: 'phone' (~0.7M), 'tiny' (~1.4M), '10m' (~13.6M), '30m' (~31.8M)",
    )
    parser.add_argument(
        "--role",
        type=str,
        default="primary_trainer",
        choices=("primary_trainer", "eval", "lightweight"),
        help="Device role in the hive fleet",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=None,
        help="CPU threads budget (defaults to auto-detected cores - 1)",
    )
    parser.add_argument(
        "--device-id",
        type=str,
        default=None,
        help="Unique name for this device (defaults to hostname-os)",
    )
    parser.add_argument(
        "--hf-dataset",
        type=str,
        default=None,
        help="Optional Hugging Face dataset name (e.g. wikitext, imdb)",
    )
    parser.add_argument(
        "--sqlite-db",
        type=str,
        default=None,
        help="Optional path to custom SQLite database file (.db / .sqlite)",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=120000,
        help="Token budget for data slice loading",
    )
    return parser.parse_args()


def detect_threads():
    try:
        import psutil

        count = psutil.cpu_count(logical=True)
        return max(1, count - 1)
    except Exception:
        return 2


def main():
    args = parse_args()
    threads = args.threads if args.threads else detect_threads()
    device_name = (
        args.device_id
        if args.device_id
        else f"{platform.system().lower()}-{socket.gethostname()}"
    )

    print("\n" + "=" * 64)
    print(f"  ORION-HIVE WORKER CLIENT")
    print("=" * 64)
    print(f"  Device Name     : {device_name}")
    print(f"  Platform        : {platform.system()} {platform.machine()}")
    print(f"  Role            : {args.role}")
    print(f"  CPU Threads     : {threads}")
    print(f"  Target Model    : {args.model}")
    print(f"  Coordinator     : {args.host}:{args.port}")
    if args.hf_dataset:
        print(f"  Dataset (HF)    : {args.hf_dataset}")
    if args.sqlite_db:
        print(f"  Dataset (SQLite): {args.sqlite_db}")
    print("=" * 64 + "\n")

    from hive.envelope import declare_device
    from hive.transport import TcpSocketTransport
    from hive.worker import run_worker_loop

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    print(f"[HIVE] Connecting to coordinator at {args.host}:{args.port}...")
    try:
        sock.connect((args.host, args.port))
    except Exception as e:
        print(f"\n[ERROR] Could not connect to coordinator at {args.host}:{args.port}: {e}")
        print("  -> Please make sure:")
        print("     1. The coordinator has launched a federated session on the dashboard.")
        print(f"     2. Both machines are on the same Wi-Fi/LAN network.")
        print(f"     3. Port {args.port} is not blocked by a local firewall.\n")
        sys.exit(1)

    print(f"[HIVE] Successfully connected! Handshaking with coordinator...")
    tx = TcpSocketTransport(sock)
    env = declare_device(
        device_id=device_name,
        role=args.role,
        cpu_threads_budget=threads,
        transport="tcp-socket",
    )

    try:
        run_worker_loop(
            tx,
            env,
            seed=42,
            model_size=args.model,
            budget=args.budget,
            data_seed=42,
            hf_dataset=args.hf_dataset,
            sqlite_db=args.sqlite_db,
        )
    except KeyboardInterrupt:
        print("\n[HIVE] Worker interrupted by user. Exiting cleanly...")
    finally:
        tx.close()
    print("[HIVE] Session finished.")


if __name__ == "__main__":
    main()
