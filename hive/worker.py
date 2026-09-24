"""A hive worker process: one simulated or network device.

Supports:
- Local multiprocessing pipe transport (SimPipeTransport)
- Remote LAN TCP transport (TcpSocketTransport)

Role decides what work the device accepts:
  primary_trainer / lightweight -> train tasks (disjoint token shards)
  eval                         -> held-out eval tasks only

Protocol (all payloads over the transport):
  worker -> "hello"            {envelope (with measured tok/s), n_blocks}
  coord  -> "sync"             {weights}             load global weights
  coord  -> "train"            {weights, block_idxs, lr, batch, round_seed}
  worker -> "update"           {weights, tokens, loss}
  coord  -> "eval"             {weights}
  worker -> "eval_result"      {val_loss, eval_tokens}
  coord  -> "probe"            re-report capability
  coord  -> "stop"
"""

import argparse
import socket
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

import torch

from hive.data import eval_blocks, load_train_blocks, load_val_blocks
from hive.envelope import ROLE_EVAL, ROLE_PRIMARY, DeviceEnvelope, declare_device
from hive.model import MODEL_CFG, MAX_LEN
from hive.transport import SimPipeTransport, TcpSocketTransport, Transport


def _build_shell(cfg, seed: int):
    from transformers import Qwen2Config, Qwen2ForCausalLM

    torch.manual_seed(seed)
    return Qwen2ForCausalLM(Qwen2Config(**dict(cfg)))


def _calibrate_tps(model, vocab_size: int, threads: int) -> float:
    """One quick fwd+bwd calibration so the envelope carries a measured rate."""
    if threads <= 0:
        return 0.0
    torch.set_num_threads(threads)
    ids = torch.randint(0, vocab_size, (2, MAX_LEN))
    attn = torch.ones_like(ids)
    labels = ids.clone()
    opt = torch.optim.SGD(model.parameters(), lr=1e-3)
    model.train()
    for _ in range(1):
        out = model(input_ids=ids, attention_mask=attn, labels=labels)
        out.loss.backward()
        opt.step()
        opt.zero_grad()
    torch.cuda.synchronize() if torch.cuda.is_available() else None
    t0 = time.time()
    n = 3
    for _ in range(n):
        out = model(input_ids=ids, attention_mask=attn, labels=labels)
        out.loss.backward()
        opt.step()
        opt.zero_grad()
    dt = (time.time() - t0) / n
    return (2 * MAX_LEN) / dt if dt > 0 else 0.0


def _local_train(model, blocks, idxs, lr, batch, round_seed):
    """Local SGD over the assigned blocks; returns (tokens, mean_loss)."""
    model.train()
    rng = __import__("random").Random(round_seed)
    order = list(idxs)
    rng.shuffle(order)
    opt = torch.optim.SGD(model.parameters(), lr=lr)
    total_tok, losses = 0, []
    for s in range(0, len(order), batch):
        bs = [blocks[i] for i in order[s : s + batch]]
        ids = torch.stack([x["input_ids"] for x in bs])
        attn = torch.stack([x["attention_mask"] for x in bs])
        labels = torch.stack([x["labels"] for x in bs])
        out = model(input_ids=ids, attention_mask=attn, labels=labels)
        loss = out.loss
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
        total_tok += int(attn.sum().item())
        losses.append(loss.item())
    mean_loss = sum(losses) / len(losses) if losses else 0.0
    return total_tok, mean_loss


def run_worker_loop(
    tx: Transport,
    envelope: DeviceEnvelope,
    seed: int,
    model_size: str,
    budget: int,
    data_seed: int,
    hf_dataset: str = None,
    sqlite_db: str = None,
):
    """Core worker loop given an active Transport (Pipe or TCP Socket)."""
    cfg = MODEL_CFG[model_size]
    model = _build_shell(cfg, seed)

    # Capability probe: measure tok/s with THIS device's thread budget.
    if envelope.role != ROLE_EVAL:
        tps = _calibrate_tps(model, cfg["vocab_size"], envelope.cpu_threads_budget)
        envelope = envelope.with_tps(tps)

    # Local data: trainers build the train slice, eval builds held-out val.
    if envelope.role == ROLE_EVAL:
        blocks = load_val_blocks(max_seq_len=cfg["max_position_embeddings"])
    else:
        blocks, _ = load_train_blocks(
            budget,
            data_seed,
            hf_dataset=hf_dataset,
            sqlite_db=sqlite_db,
            max_seq_len=cfg["max_position_embeddings"],
        )
    tx.send({"type": "hello", "envelope": envelope, "n_blocks": len(blocks)})

    while True:
        try:
            msg = tx.recv()
        except EOFError:
            break
        mtype = msg.get("type")
        if mtype == "probe":
            tx.send({"type": "hello", "envelope": envelope, "n_blocks": len(blocks)})
        elif mtype == "train":
            model.load_state_dict(msg["weights"])
            t0 = time.time()
            tok, loss = _local_train(
                model,
                blocks,
                msg["block_idxs"],
                msg["lr"],
                msg["batch"],
                msg["round_seed"],
            )
            train_s = time.time() - t0
            tx.send(
                {
                    "type": "update",
                    "weights": model.state_dict(),
                    "tokens": tok,
                    "loss": loss,
                    "train_s": train_s,
                }
            )
        elif mtype == "eval":
            model.load_state_dict(msg["weights"])
            vl, vt = eval_blocks(model, blocks)
            tx.send({"type": "eval_result", "val_loss": vl, "eval_tokens": vt})
        elif mtype == "drop":
            # Injected failure: die mid-run with no reply (simulates a crash).
            import os

            os._exit(7)
        elif mtype == "stop":
            break
        else:
            tx.send({"type": "error", "message": f"unknown message {mtype!r}"})


def worker_main(
    conn,
    envelope: DeviceEnvelope,
    seed: int,
    model_size: str,
    budget: int,
    data_seed: int,
    hf_dataset: str = None,
    sqlite_db: str = None,
):
    """Entry point for simulated device process (spawned via multiprocessing)."""
    tx = SimPipeTransport(conn)
    try:
        run_worker_loop(
            tx,
            envelope,
            seed,
            model_size,
            budget,
            data_seed,
            hf_dataset=hf_dataset,
            sqlite_db=sqlite_db,
        )
    finally:
        tx.close()


def main(argv=None):
    """CLI entry point for running a worker on a remote laptop / node over TCP."""
    parser = argparse.ArgumentParser(description="ORION-HIVE LAN Worker")
    parser.add_argument(
        "--host", type=str, required=True, help="Coordinator host / IP"
    )
    parser.add_argument(
        "--port", type=int, default=8765, help="Coordinator port (default 8765)"
    )
    parser.add_argument(
        "--device-id",
        type=str,
        default=f"laptop-{socket.gethostname()}",
        help="Device ID",
    )
    parser.add_argument(
        "--role",
        type=str,
        default=ROLE_PRIMARY,
        choices=(ROLE_PRIMARY, ROLE_EVAL, "lightweight"),
    )
    parser.add_argument(
        "--threads", type=int, default=3, help="CPU threads budget for worker"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="10m",
        choices=("phone", "tiny", "10m", "30m"),
        help="Model architecture tier",
    )
    parser.add_argument(
        "--budget", type=int, default=120000, help="Token budget for data slice"
    )
    parser.add_argument(
        "--hf-dataset",
        type=str,
        default=None,
        help="Optional Hugging Face dataset name",
    )
    parser.add_argument(
        "--sqlite-db",
        type=str,
        default=None,
        help="Optional SQLite DB path",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--data-seed", type=int, default=42)

    args = parser.parse_args(argv)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    print(f"[WORKER] Connecting to coordinator at {args.host}:{args.port}...")
    sock.connect((args.host, args.port))
    print(f"[WORKER] Connected! Initializing transport and envelope...")

    tx = TcpSocketTransport(sock)
    env = declare_device(
        device_id=args.device_id,
        role=args.role,
        cpu_threads_budget=args.threads,
        transport="tcp-socket",
    )
    try:
        run_worker_loop(
            tx,
            env,
            seed=args.seed,
            model_size=args.model,
            budget=args.budget,
            data_seed=args.data_seed,
            hf_dataset=args.hf_dataset,
            sqlite_db=args.sqlite_db,
        )
    finally:
        tx.close()
    print("[WORKER] Worker loop terminated gracefully.")


if __name__ == "__main__":
    main()
