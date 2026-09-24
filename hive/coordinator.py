"""Hive coordinator: registration, capability probe, role dispatch, FedAvg
aggregation with a server-side optimizer, checkpointing, and metrics.

Runs the whole fleet lifecycle and returns one metrics record per run, which
`hive.run` records through scripts/repro.py::record_experiment.
Supports both local simulated multiprocessing workers and real network/TCP workers.
"""

import json
import os
import select
import shutil
import socket
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import hashlib
import psutil
import torch

import orion_corpus

from hive.aggregation import fedavg, loss_reduction_pct, mse
from hive.data import eval_blocks, load_train_blocks, load_val_blocks
from hive.envelope import (
    ROLE_EVAL,
    ROLE_LIGHTWEIGHT,
    ROLE_PRIMARY,
    DeviceEnvelope,
    declare_device,
)
from hive.model import MAX_LEN, build_model
from hive.transport import SimPipeTransport, TcpSocketTransport, Transport
from hive.worker import worker_main


def _sha256_file(path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


# Fleet thread budgets per role (declared in the envelope; total logical threads = 12).
THREADS = {ROLE_PRIMARY: 3, ROLE_EVAL: 1, ROLE_LIGHTWEIGHT: 1}


@dataclass
class WorkerHandle:
    device_id: str
    role: str
    proc: Optional[object]
    tx: Transport
    envelope: DeviceEnvelope
    alive: bool = True


def topology(workers: int):
    """Role mix for the simulated fleet. workers=4 is the heterogeneous fleet:
    the task's example topology (2x primary, 1x eval, 1x lightweight/phone-sim)."""
    if workers == 1:
        return [(ROLE_PRIMARY, THREADS[ROLE_PRIMARY])]
    if workers == 2:
        return [(ROLE_PRIMARY, THREADS[ROLE_PRIMARY])] * 2
    if workers == 4:
        return [
            (ROLE_PRIMARY, THREADS[ROLE_PRIMARY]),
            (ROLE_PRIMARY, THREADS[ROLE_PRIMARY]),
            (ROLE_EVAL, THREADS[ROLE_EVAL]),
            (ROLE_LIGHTWEIGHT, THREADS[ROLE_LIGHTWEIGHT]),
        ]
    raise ValueError("workers must be 1, 2 or 4")


class HiveCoordinator:
    def __init__(
        self,
        model_size,
        workers,
        rounds,
        tokens,
        dropout_every=0,
        seed=42,
        out_dir=Path("models/hive"),
        batch=4,
        worker_lr=5e-3,
        server_momentum=0.0,
        resume=None,
        keep_ckpts=1,
        verbose=True,
        listen_host: Optional[str] = None,
        listen_port: int = 8765,
        network_workers: int = 0,
        hf_dataset: Optional[str] = None,
        sqlite_db: Optional[str] = None,
    ):
        self.model_size = model_size
        self.workers = workers
        self.rounds = rounds
        self.tokens = tokens  # total tokens trained per round (fleet-wide)
        self.dropout_every = dropout_every
        self.seed = seed
        self.out_dir = Path(out_dir)
        self.batch = batch
        self.worker_lr = worker_lr
        self.server_momentum = server_momentum
        self.resume_path = Path(resume) if resume else None
        self.keep_ckpts = keep_ckpts
        self.verbose = verbose
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.network_workers = network_workers
        self.hf_dataset = hf_dataset
        self.sqlite_db = sqlite_db

        fleet_label = f"{workers}w" if not network_workers else f"{workers}w-net{network_workers}"
        self.run_id = f"hive-{fleet_label}-{model_size}-{uuid.uuid4().hex[:8]}"
        self.run_dir = self.out_dir / self.run_id
        self.log = print if verbose else lambda *a, **k: None

    # ---- lifecycle -----------------------------------------------------------

    def run(self) -> dict:
        t_start = time.time()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        disk0 = shutil.disk_usage(self.run_dir).free

        # Fleet-wide data slice: every process builds the identical block list.
        t0 = time.time()
        self.blocks, slice_tokens = load_train_blocks(
            self.tokens, self.seed, hf_dataset=self.hf_dataset, sqlite_db=self.sqlite_db
        )
        self.val_blocks = load_val_blocks()
        if self.hf_dataset:
            self.dataset_path = f"hf://{self.hf_dataset}"
            self.dataset_hash = hashlib.sha256(self.hf_dataset.encode()).hexdigest()
        elif self.sqlite_db:
            self.dataset_path = str(self.sqlite_db)
            self.dataset_hash = _sha256_file(self.sqlite_db)
        else:
            self.dataset_path = str(
                orion_corpus.train_shards(orion_corpus.resolve_corpus()[0])[0]
            )
            self.dataset_hash = _sha256_file(self.dataset_path)
        self.log(
            f"[DATA] {len(self.blocks)} train blocks ({self._toks():,} tok/round "
            f"fleet-wide, slice read {slice_tokens:,}) | {len(self.val_blocks)} val blocks "
            f"({sum(b['block_tokens'] for b in self.val_blocks):,} tok) "
            f"in {time.time() - t0:.1f}s"
        )

        # Global model + server optimizer (FedAvg + optional server momentum).
        t0 = time.time()
        self.model, self.cfg, self.n_params = build_model(self.model_size, self.seed)
        self.solver = torch.optim.SGD(
            self.model.parameters(), lr=1.0, momentum=self.server_momentum
        )
        self.log(
            f"[MODEL] {self.model_size} size={self.n_params:,} params in {time.time() - t0:.1f}s"
        )

        start_round = 1
        if self.resume_path:
            start_round = self._load_checkpoint(self.resume_path)

        self.handles: list[WorkerHandle] = []
        self.trainers: list[WorkerHandle] = []
        self.eval_handle = None
        self.losses, self.val_losses = [], []
        self.total_tokens = 0
        self.failures = 0
        self.attempts = 0
        self.comm_wall = 0.0
        self.compute_wall = 0.0
        self.loop_wall = 0.0
        self.peak_rss_mb = 0.0
        self.resume_verified = False
        self.comm_bytes = 0

        self._spawn_fleet()
        self.log(
            f"[FLEET] registered {len(self.handles)} devices | "
            f"trainers={[h.device_id for h in self.trainers]} "
            f"| eval={'yes' if self.eval_handle else 'in-process'}"
        )

        n_blocks = len(self.blocks)
        shares = self._shares()
        bounds = self._bounds(n_blocks, shares)
        step = max(1, n_blocks // max(1, self.rounds))

        for r in range(start_round, self.rounds + 1):
            self._poll_rss()
            t_round0 = time.time()
            round_wall, comm_wall, failed, round_compute = self._run_round(
                r, bounds, step
            )
            self.comm_wall += comm_wall
            self.compute_wall += round_compute
            self.loop_wall += round_wall
            self.failures += failed
            overhead = 100.0 * (round_wall - round_compute) / max(round_wall, 1e-9)
            self.log(
                f"[ROUND {r}] wall={round_wall:.1f}s compute={round_compute:.2f}s "
                f"overhead={overhead:.0f}% "
                f"loss={self.losses[-1]:.3f} val_loss={self.val_losses[-1]:.4f} "
                f"tokens={self.total_tokens:,} failures={self.failures}"
            )
            self._checkpoint(r)
            self._rejoin_dead(r)
            if r >= self.rounds:
                break

        wall = time.time() - t_start
        self._poll_rss()
        self._cleanup()
        disk1 = shutil.disk_usage(self.out_dir).free
        artifacts = self._dir_bytes(self.run_dir)

        return self._record(wall, disk0, disk1, artifacts)

    # ---- fleet ops ------------------------------------------------------------

    def _spawn_fleet(self):
        # 1. Spawn local simulated pipe workers if configured
        local_workers = self.workers - self.network_workers
        if local_workers > 0:
            import multiprocessing as mp

            for i, (role, threads) in enumerate(topology(local_workers)):
                parent, child = mp.Pipe(duplex=True)
                env = declare_device(
                    device_id=f"dev-{i}-{role[:3]}",
                    role=role,
                    cpu_threads_budget=threads,
                )
                proc = mp.Process(
                    target=worker_main,
                    args=(
                        child,
                        env,
                        self.seed,
                        self.model_size,
                        self.tokens,
                        self.seed,
                        self.hf_dataset,
                        self.sqlite_db,
                    ),
                    name=f"hive-{env.device_id}",
                )
                proc.start()
                tx = SimPipeTransport(parent)
                handle = WorkerHandle(
                    device_id=env.device_id, role=role, proc=proc, tx=tx, envelope=env
                )
                t0 = time.time()
                hello = tx.recv()  # capability probe (worker measures its own tok/s)
                assert hello["type"] == "hello", hello
                self.log(
                    f"[REGISTER] {hello['envelope'].device_id} "
                    f"role={hello['envelope'].role} threads={hello['envelope'].cpu_threads_budget} "
                    f"tps={hello['envelope'].tokens_per_sec_estimate:.0f} blocks={hello['n_blocks']} "
                    f"in {time.time() - t0:.1f}s"
                )
                handle.envelope = hello["envelope"]
                self.handles.append(handle)
                if handle.role == ROLE_EVAL:
                    self.eval_handle = handle
                else:
                    self.trainers.append(handle)

        # 2. Accept network TCP workers if configured
        if self.network_workers > 0 and self.listen_host:
            server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_sock.bind((self.listen_host, self.listen_port))
            server_sock.listen(self.network_workers)
            self.log(
                f"[NETWORK] Coordinator listening on {self.listen_host}:{self.listen_port} "
                f"for {self.network_workers} network workers..."
            )
            for _ in range(self.network_workers):
                client_sock, client_addr = server_sock.accept()
                tx = TcpSocketTransport(client_sock)
                t0 = time.time()
                hello = tx.recv()
                assert hello["type"] == "hello", hello
                env = hello["envelope"]
                handle = WorkerHandle(
                    device_id=env.device_id,
                    role=env.role,
                    proc=None,
                    tx=tx,
                    envelope=env,
                )
                self.log(
                    f"[REGISTER NET] {env.device_id} from {client_addr} "
                    f"role={env.role} threads={env.cpu_threads_budget} "
                    f"tps={env.tokens_per_sec_estimate:.0f} blocks={hello['n_blocks']} "
                    f"in {time.time() - t0:.1f}s"
                )
                self.handles.append(handle)
                if handle.role == ROLE_EVAL:
                    self.eval_handle = handle
                else:
                    self.trainers.append(handle)
            server_sock.close()

    def _shares(self):
        """Work shares proportional to each trainer's measured tok/s (role-based
        dispatch: the lightweight/phone-sim device receives a smaller shard)."""
        rates = [max(h.envelope.tokens_per_sec_estimate, 1.0) for h in self.trainers]
        return [r / sum(rates) for r in rates]

    @staticmethod
    def _bounds(n_blocks, shares):
        edges = [0.0]
        for s in shares:
            edges.append(edges[-1] + n_blocks * s)
        bounds = [int(round(e)) for e in edges]
        bounds[0], bounds[-1] = 0, n_blocks
        for i in range(1, len(bounds) - 1):
            bounds[i] = max(bounds[i - 1], min(bounds[i], n_blocks))
        return [(bounds[i], bounds[i + 1]) for i in range(len(shares))]

    @staticmethod
    def _slice_idxs(n_blocks, a, b, start):
        return [(start + i) % n_blocks for i in range(a, b)]

    # ---- one round ---------------------------------------------------------------

    def _run_round(self, r, bounds, step):
        attempts = len(self.trainers)
        self.attempts += attempts
        start = ((r - 1) * step) % len(self.blocks)
        payloads = {}
        dispatch_t0 = time.time()
        for h, (a, b) in zip(self.trainers, bounds):
            idxs = self._slice_idxs(len(self.blocks), a, b, start)
            payloads[h.device_id] = idxs
            h.tx.send(
                {
                    "type": "train",
                    "weights": self.model.state_dict(),
                    "block_idxs": idxs,
                    "lr": self.worker_lr,
                    "batch": self.batch,
                    "round_seed": self.seed + r * 1000 + len(idxs),
                }
            )
        dispatch_s = time.time() - dispatch_t0

        # Injected dropout: a worker is killed mid-round (real process terminate).
        if self.dropout_every > 0 and r % self.dropout_every == 0:
            victim = self.trainers[(r // self.dropout_every) % len(self.trainers)]
            time.sleep(0.2)
            self.log(f"[DROPOUT] terminating {victim.device_id} mid-round {r}")
            if victim.proc:
                victim.proc.terminate()
            victim.tx.close()
            victim.alive = False  # its update never arrives; counted as a failure below

        collect_t0 = time.time()
        updates, round_tokens, round_losses, failed = [], 0, [], 0
        round_compute = 0.0
        for h in self.trainers:
            if not h.alive:
                failed += 1
                continue
            if not h.tx.poll(self._update_timeout(h)):
                self.log(f"[FAIL] {h.device_id} did not return an update (round {r})")
                failed += 1
                continue
            try:
                msg = h.tx.recv()
            except (EOFError, ConnectionResetError, BrokenPipeError):
                self.log(f"[FAIL] {h.device_id} pipe/socket EOF (crashed) (round {r})")
                h.alive = False
                failed += 1
                continue
            if msg["type"] == "update":
                updates.append((msg["weights"], msg["tokens"]))
                round_tokens += msg["tokens"]
                round_losses.append(msg["loss"])
                round_compute = max(round_compute, msg.get("train_s", 0.0))
            else:
                self.log(f"[FAIL] {h.device_id} returned {msg.get('type')} (round {r})")
                failed += 1
        collect_s = time.time() - collect_t0

        agg_t0 = time.time()
        if updates:
            avg = fedavg(updates)
            self._server_step(avg)
            self.total_tokens += round_tokens
            self.losses.append(sum(round_losses) / len(round_losses))
        else:
            self.log(f"[ROUND {r}] NO updates survived - skipping aggregation")
            self.losses.append(float("nan"))
        agg_s = time.time() - agg_t0

        eval_t0 = time.time()
        self.val_losses.append(self._evaluate())
        eval_s = time.time() - eval_t0

        round_wall = time.time() - dispatch_t0
        return (
            round_wall,
            dispatch_s + collect_s + agg_s + eval_s,
            failed,
            round_compute,
        )

    def _update_timeout(self, h):
        # generous: local share at the device's own measured rate, x3, + 60s
        rate = max(h.envelope.tokens_per_sec_estimate, 1.0)
        return 60.0 + 3.0 * self.tokens / rate

    def _server_step(self, avg):
        """Server optimizer: global = prev - solver(moving avg of deltas).
        With momentum=0, lr=1.0 this is exact token-weighted FedAvg."""
        with torch.no_grad():
            for name, p in self.model.named_parameters():
                p.grad = p.data.detach() - avg[name]
        self.solver.step()
        self.solver.zero_grad(set_to_none=True)

    def _evaluate(self):
        if self.eval_handle and self.eval_handle.alive:
            try:
                self.eval_handle.tx.send(
                    {"type": "eval", "weights": self.model.state_dict()}
                )
                msg = self.eval_handle.tx.recv()
                return msg.get("val_loss", float("nan"))
            except Exception:
                pass
        vl, _ = eval_blocks(self.model, self.val_blocks, self.batch)
        return vl

    # ---- checkpoint + resume --------------------------------------------------------

    def _ckpt_path(self, r):
        return self.run_dir / f"global-r{r}.pt"

    def _checkpoint(self, r):
        path = self._ckpt_path(r)
        torch.save(
            {
                "model": self.model.state_dict(),
                "optimizer": self.solver.state_dict(),
                "round": r,
                "cfg": self.cfg,
                "model_size": self.model_size,
                "budget": self.tokens,
                "data_seed": self.seed,
                "server_momentum": self.server_momentum,
                "worker_lr": self.worker_lr,
                "batch": self.batch,
                "losses": self.losses,
                "val_losses": self.val_losses,
                "total_tokens": self.total_tokens,
                "envelopes": [h.envelope.asdict() for h in self.handles],
                "run_id": self.run_id,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            path,
        )
        # prove resume: fresh model + fresh solver load this file, weights match
        model2, _, _ = build_model(self.model_size, self.seed)
        solver2 = torch.optim.SGD(
            model2.parameters(), lr=1.0, momentum=self.server_momentum
        )
        ck = torch.load(path, map_location="cpu", weights_only=False)
        model2.load_state_dict(ck["model"])
        solver2.load_state_dict(ck["optimizer"])
        diff = mse(self.model.state_dict(), ck["model"])
        self.resume_verified = diff < 1e-6
        self.log(
            f"[CKPT] saved {path.name} ({path.stat().st_size / 1e6:.1f} MB) "
            f"resume-round-trip maxdiff={diff:.2e} {'OK' if self.resume_verified else 'MISMATCH'}"
        )
        # disk floor: drop old checkpoints (keep the last `keep_ckpts`)
        for old in sorted(self.run_dir.glob("global-r*.pt")):
            if (
                old != path
                and len(list(self.run_dir.glob("global-r*.pt"))) > self.keep_ckpts
            ):
                old.unlink()

    def _load_checkpoint(self, path):
        ck = torch.load(path, map_location="cpu", weights_only=False)
        self.model.load_state_dict(ck["model"])
        self.solver = torch.optim.SGD(
            self.model.parameters(), lr=1.0, momentum=ck.get("server_momentum", 0.0)
        )
        self.solver.load_state_dict(ck["optimizer"])
        self.log(
            f"[RESUME] {path} at round {ck['round']} (loss history {ck['losses'][-3:]})"
        )
        return int(ck["round"]) + 1

    def _rejoin_dead(self, r):
        import multiprocessing as mp

        for i, h in enumerate(self.trainers):
            if not h.alive and h.proc is not None:
                parent, child = mp.Pipe(duplex=True)
                env = h.envelope.with_tps(h.envelope.tokens_per_sec_estimate)
                proc = mp.Process(
                    target=worker_main,
                    args=(
                        child,
                        env,
                        self.seed,
                        self.model_size,
                        self.tokens,
                        self.seed,
                        self.hf_dataset,
                        self.sqlite_db,
                    ),
                    name=f"hive-{env.device_id}-rejoin",
                )
                proc.start()
                tx = SimPipeTransport(parent)
                hello = tx.recv()
                new = WorkerHandle(
                    device_id=h.device_id,
                    role=h.role,
                    proc=proc,
                    tx=tx,
                    envelope=hello["envelope"],
                )
                self.handles = [new if x is h else x for x in self.handles]
                self.trainers[i] = new
                self.log(f"[REJOIN] {new.device_id} registered again after round {r}")

    # ---- metrics / cleanup -------------------------------------------------------------

    def _poll_rss(self):
        rss = psutil.Process().memory_info().rss
        for h in self.handles:
            if h.proc:
                try:
                    rss = max(rss, psutil.Process(h.proc.pid).memory_info().rss)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        self.peak_rss_mb = max(self.peak_rss_mb, rss / 1024**2)

    def _cleanup(self):
        for h in self.handles:
            try:
                h.tx.send({"type": "stop"})
            except Exception:
                pass
            if h.proc:
                try:
                    h.proc.join(timeout=5)
                except Exception:
                    pass
                if h.proc.is_alive():
                    h.proc.terminate()
            h.tx.close()

    @staticmethod
    def _dir_bytes(path):
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())

    def _toks(self):
        return sum(b["block_tokens"] for b in self.blocks)

    def _record(self, wall, disk0, disk1, artifacts):
        roles = [h.envelope.role for h in self.handles]
        attempts = self.attempts
        final_loss = self.losses[-1] if self.losses else float("nan")
        first_loss = self.losses[0] if self.losses else float("nan")
        val_loss = self.val_losses[-1] if self.val_losses else float("nan")
        tok_s = (self.total_tokens / wall) if wall > 0 else 0.0
        # comm overhead = share of round-loop wall NOT spent training (transport +
        # serialization + aggregation + eval + idle waiting), honest per-worker
        # train seconds come back in every update message.
        overhead = (
            100.0 * (self.loop_wall - self.compute_wall) / max(self.loop_wall, 1e-9)
        )
        tok_s_loop = (self.total_tokens / self.loop_wall) if self.loop_wall > 0 else 0.0
        # per-worker payload bytes summed over every host transport
        total_comm = sum(h.tx.bytes for h in self.handles)
        return {
            "run_id": self.run_id,
            "status": "COMPLETED",
            "base_model_name": f"hive-{self.model_size}-from-scratch",
            "model_type": "hive-federated",
            "model_size": self.model_size,
            "n_params": self.n_params,
            "topology": {
                "n_workers": len(self.handles),
                "roles": roles,
                "transports": [h.envelope.transport for h in self.handles],
            },
            "n_trainers": len(self.trainers),
            "rounds": self.rounds,
            "rounds_attempted": self.rounds,
            "tokens_per_round": self.tokens,
            "total_tokens_trained": self.total_tokens,
            "wall_clock_s": round(wall, 2),
            "training_loop_s": round(self.loop_wall, 2),
            "tokens_per_s": round(tok_s, 1),
            "tokens_per_s_loop": round(tok_s_loop, 1),
            "comm_bytes": total_comm,
            "comm_overhead_pct": round(overhead, 1),
            "val_loss": round(val_loss, 4),
            "eval_tokens": sum(b["block_tokens"] for b in self.val_blocks),
            "starting_loss": round(first_loss, 4),
            "ending_loss": round(final_loss, 4),
            "loss_reduction_pct": round(loss_reduction_pct(first_loss, final_loss), 2),
            "failure_rate": round(self.failures / max(attempts, 1), 4),
            "failures": self.failures,
            "updates_attempted": attempts,
            "resume_verified": self.resume_verified,
            "peak_rss_mb": round(self.peak_rss_mb, 1),
            "disk_free_before": disk0,
            "disk_free_after": disk1,
            "artifacts_bytes": artifacts,
            "checkpoint_path": str(self._ckpt_path(self.rounds))
            if self.rounds >= 1
            else "",
            "dataset_path": self.dataset_path,
            "dataset_hash": self.dataset_hash,
            "tokenizer_path": str(Path("models/tokenizer_bpe/tokenizer.json")),
            "seed": self.seed,
            "worker_lr": self.worker_lr,
            "server_momentum": self.server_momentum,
            "batch": self.batch,
            "dropout_every": self.dropout_every,
            "speedup_claim": "no-linear-speedup-claim",  # set by run.py from the comparison
            "scope": "VERIFIED-mechanics or measured (set by caller)",
        }
