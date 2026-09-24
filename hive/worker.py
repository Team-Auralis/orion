"""A hive worker process: one simulated device.

Separate multiprocessing.Process per device - real IPC over an OS pipe (the
transport), which genuinely exercises serialization of model weights, not
shared-memory threads. Role decides what work the device accepts:
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

import time

import torch

from hive.data import eval_blocks, load_train_blocks, load_val_blocks
from hive.envelope import ROLE_EVAL, DeviceEnvelope
from hive.model import MODEL_CFG, MAX_LEN
from hive.transport import SimPipeTransport


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


def worker_main(
    conn,
    envelope: DeviceEnvelope,
    seed: int,
    model_size: str,
    budget: int,
    data_seed: int,
):
    """Entry point for every hive device process (spawned via multiprocessing)."""
    tx = SimPipeTransport(conn)
    cfg = MODEL_CFG[model_size]
    model = _build_shell(cfg, seed)

    # Capability probe: measure tok/s with THIS device's thread budget.
    if envelope.role != ROLE_EVAL:
        tps = _calibrate_tps(model, cfg["vocab_size"], envelope.cpu_threads_budget)
        envelope = envelope.with_tps(tps)

    # Local data: trainers build the train slice, eval builds held-out val.
    if envelope.role == ROLE_EVAL:
        blocks = load_val_blocks()
    else:
        blocks, _ = load_train_blocks(budget, data_seed)
    tx.send({"type": "hello", "envelope": envelope, "n_blocks": len(blocks)})

    while True:
        msg = tx.recv()
        mtype = msg["type"]
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
