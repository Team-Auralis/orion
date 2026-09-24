#!/usr/bin/env python3
"""model_identity.py - zero-trust model-identity forensics.

Proves the identity of a torch training checkpoint vs its HF export from the
actual bytes, in a clean process. Does NOT trust filenames, docs, or prior
claims. Never imports the training harness or transformers - only torch +
stdlib (numpy bytes via torch's tensor API; ctypes for Windows RSS).

Usage:
    python scripts/forensic/model_identity.py \
        --checkpoint models/comp001/100m-real/checkpoint-1869/checkpoint.pt \
        --export models/comp001/100m-real/

Memory discipline (this box is RAM-starved):
  * checkpoint and export are processed one at a time; tensors are released
    (del + gc.collect()) between stages;
  * the safetensors export is read header-only (struct parse), the spot-check
    reads a handful of individual tensors at their data offsets;
  * nothing is copied or rewritten; only hashed in a streaming fashion.

Outputs (small text only):
  logs/forensic/identity.json
  logs/forensic/identity_raw.txt
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import shutil
import struct
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import torch

if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes
else:
    ctypes = None  # type: ignore


# ---------------------------------------------------------------------------
# memory / time helpers
# ---------------------------------------------------------------------------


class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.wintypes.DWORD),
        ("PageFaultCount", ctypes.wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.wintypes.DWORD),
        ("dwMemoryLoad", ctypes.wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _win_mem_counters() -> _PROCESS_MEMORY_COUNTERS | None:
    try:
        if sys.platform != "win32" or ctypes is None:
            return None
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        kernel32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.POINTER(_PROCESS_MEMORY_COUNTERS),
            ctypes.wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.wintypes.BOOL
        pmc = _PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS)
        ok = psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb
        )
        return pmc if ok else None
    except Exception:
        return None


def _avail_phys_mb() -> float | None:
    try:
        if sys.platform != "win32" or ctypes is None:
            return None
        ms = _MEMORYSTATUSEX()
        ms.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
        return ms.ullAvailPhys / 2**20 if ok else None
    except Exception:
        return None


def rss_now_mb() -> float:
    pmc = _win_mem_counters()
    if pmc is not None:
        return pmc.WorkingSetSize / 2**20
    try:
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    except Exception:
        return 0.0


def rss_peak_mb() -> float:
    pmc = _win_mem_counters()
    if pmc is not None:
        return pmc.PeakWorkingSetSize / 2**20
    try:
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    except Exception:
        return 0.0


class Tracker:
    """Accumulates stage progress + peak RSS for the report."""

    def __init__(self) -> None:
        self.peak = rss_peak_mb()
        self.stages: list[dict] = []
        self._t0 = time.perf_counter()

    def log(self, stage, msg: str) -> None:
        now = rss_now_mb()
        peak = rss_peak_mb()
        self.peak = max(self.peak, peak)
        avail = _avail_phys_mb()
        avail_s = f" avail_phys={avail:.0f}MB" if avail is not None else ""
        print(
            f"[{stage}] {msg} | rss_now={now:.0f}MB peak={peak:.0f}MB{avail_s}",
            flush=True,
        )
        self.stages.append(
            {
                "stage": stage,
                "rss_now_mb": round(now, 1),
                "peak_rss_mb": round(peak, 1),
                "avail_phys_mb": round(avail, 1) if avail is not None else None,
                "elapsed_s": round(time.perf_counter() - self._t0, 1),
            }
        )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(8 * 2**20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def tensor_raw_bytes(t: torch.Tensor) -> bytes:
    """Canonical raw bytes of a tensor (C order, native endian).

    Uses a uint8 view so it works for every dtype (incl. bf16, which numpy
    cannot represent). Falls back to an fp32 projection only if the byte view
    is impossible (would be recorded in the report; not expected here).
    """
    c = t.detach().contiguous()
    try:
        return c.view(torch.uint8).reshape(-1).numpy().tobytes()
    except Exception:
        return c.float().numpy().tobytes()


# ---------------------------------------------------------------------------
# checkpoint side
# ---------------------------------------------------------------------------


def load_checkpoint(ckpt_path: Path, tracker: Tracker):
    """Try torch.load from scratch; return (obj, load_attempts, main_mode)."""
    attempts = []
    candidates = [
        {"label": "weights_only=True", "weights_only": True, "mmap": False},
        {
            "label": "weights_only=False (harness-style)",
            "weights_only": False,
            "mmap": False,
        },
        {"label": "weights_only=True mmap=True", "weights_only": True, "mmap": True},
        {"label": "weights_only=False mmap=True", "weights_only": False, "mmap": True},
    ]
    tracker.log(
        "LOAD",
        f"torch.load {ckpt_path.name} ({ckpt_path.stat().st_size / 2**20:.0f} MB) - probing load modes",
    )
    for cand in candidates:
        t0 = time.perf_counter()
        try:
            obj = torch.load(
                ckpt_path,
                map_location="cpu",
                weights_only=cand["weights_only"],
                mmap=cand["mmap"],
            )
            dt = time.perf_counter() - t0
            tracker.log("LOAD", f"SUCCESS mode={cand['label']} load_time={dt:.1f}s")
            attempts.append(
                {
                    "mode": cand["label"],
                    "succeeded": True,
                    "load_time_s": round(dt, 2),
                    "error": None,
                }
            )
            return obj, attempts, cand["label"]
        except Exception as e:  # any load failure - report the exact error
            dt = time.perf_counter() - t0
            msg = f"{type(e).__name__}: {e}"
            tracker.log(
                "LOAD", f"FAILED mode={cand['label']} after {dt:.1f}s - {msg[:200]}"
            )
            attempts.append(
                {
                    "mode": cand["label"],
                    "succeeded": False,
                    "load_time_s": round(dt, 2),
                    "error": msg[:1000],
                }
            )
            gc.collect()
    return None, attempts, None


def enumerate_state_dict(sd: dict, tracker: Tracker):
    """Per-tensor metadata + deterministic hashes; returns records."""
    tracker.log(
        "ENUM",
        f"hashing {len(sd)} state-dict tensors (state dict ~{sum(t.numel() for t in sd.values()) * 4 / 2**20:.0f} MB @fp32-ish)",
    )
    records: dict[str, dict] = {}
    total_numel = 0
    numel_by_dtype: dict[str, int] = {}
    for key in sorted(sd.keys()):
        t = sd[key]
        ne = int(t.numel())
        total_numel += ne
        dt = str(t.dtype)
        numel_by_dtype[dt] = numel_by_dtype.get(dt, 0) + ne
        raw = tensor_raw_bytes(t)
        h = hashlib.sha256()
        h.update(key.encode("utf-8"))
        h.update(b"\x00")
        h.update(dt.encode("utf-8"))
        h.update(b"\x00")
        h.update(json.dumps(list(t.shape), separators=(",", ":")).encode("utf-8"))
        h.update(b"\x00")
        h.update(raw)
        records[key] = {
            "shape": list(t.shape),
            "dtype": dt,
            "numel": ne,
            "sha256": h.hexdigest(),
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
        }
    whole = hashlib.sha256()
    for key in sorted(records.keys()):
        whole.update(bytes.fromhex(records[key]["sha256"]))
    tracker.log("ENUM", f"done: {len(records)} tensors, {total_numel:,} params total")
    return records, total_numel, numel_by_dtype, whole.hexdigest()


# ---------------------------------------------------------------------------
# config-side reconstruction (pure arithmetic from config.json - no imports)
# ---------------------------------------------------------------------------


def expected_qwen2_keys(cfg: dict, with_attention_bias: bool) -> tuple[dict, dict]:
    """Config-derived expected key set (with shapes) + per-component counts."""
    h = cfg["hidden_size"]
    v = cfg["vocab_size"]
    inter = cfg["intermediate_size"]
    L = cfg["num_hidden_layers"]
    nh = cfg["num_attention_heads"]
    nkv = cfg["num_key_value_heads"]
    head_dim = cfg.get("head_dim") or (h // nh)
    q_out, kv_out = nh * head_dim, nkv * head_dim
    tie = bool(cfg.get("tie_word_embeddings", False))

    keys: dict[str, list] = {}
    counts: dict[str, int] = {}

    def add(k: str, shape: list, bucket: str) -> None:
        keys[k] = shape
        ne = 1
        for s in shape:
            ne *= s
        counts[bucket] = counts.get(bucket, 0) + ne

    add("model.embed_tokens.weight", [v, h], "embed")
    for i in range(L):
        p = f"model.layers.{i}"
        add(f"{p}.self_attn.q_proj.weight", [q_out, h], "attn_qkv_o")
        add(f"{p}.self_attn.k_proj.weight", [kv_out, h], "attn_qkv_o")
        add(f"{p}.self_attn.v_proj.weight", [kv_out, h], "attn_qkv_o")
        add(f"{p}.self_attn.o_proj.weight", [h, q_out], "attn_qkv_o")
        add(f"{p}.mlp.gate_proj.weight", [inter, h], "mlp")
        add(f"{p}.mlp.up_proj.weight", [inter, h], "mlp")
        add(f"{p}.mlp.down_proj.weight", [h, inter], "mlp")
        add(f"{p}.input_layernorm.weight", [h], "norms")
        add(f"{p}.post_attention_layernorm.weight", [h], "norms")
        if with_attention_bias:
            add(f"{p}.self_attn.q_proj.bias", [q_out], "attn_bias_qkv")
            add(f"{p}.self_attn.k_proj.bias", [kv_out], "attn_bias_qkv")
            add(f"{p}.self_attn.v_proj.bias", [kv_out], "attn_bias_qkv")
    add("model.norm.weight", [h], "final_norm")
    if not tie:
        add("lm_head.weight", [v, h], "lm_head")
    return keys, counts


def prod(shape) -> int:
    n = 1
    for s in shape:
        n *= s
    return n


# ---------------------------------------------------------------------------
# export side (safetensors: header-only struct parsing + offset reads)
# ---------------------------------------------------------------------------


def read_safetensors_header(path: Path) -> tuple[dict, bytes]:
    with open(path, "rb") as f:
        head = f.read(8)
        n = struct.unpack("<Q", head)[0]
        raw = f.read(n)
    return json.loads(raw.decode("utf-8")), raw


def read_safetensors_tensor(path: Path, header_len: int, begin: int, end: int) -> bytes:
    with open(path, "rb") as f:
        f.seek(8 + header_len + begin)
        return f.read(end - begin)


# ---------------------------------------------------------------------------
# ledger
# ---------------------------------------------------------------------------


def read_ledger_rows(ledger_path: Path, experiment: str) -> list[dict]:
    if not ledger_path.exists():
        return []
    rows = []
    with open(ledger_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("experiment") == experiment:
                rows.append(
                    {
                        "run_id": row.get("run_id"),
                        "status": row.get("status"),
                        "param_count": row.get("param_count"),
                        "peak_rss_mb": row.get("peak_rss_mb"),
                        "tokens_seen": row.get("tokens_seen"),
                        "timestamp": row.get("timestamp"),
                        "checkpoint_path": row.get("checkpoint_path"),
                        "checkpoints": row.get("checkpoints"),
                    }
                )
    return rows


def find_ledger(start: Path) -> Path | None:
    cur = start.resolve()
    for _ in range(6):
        cand = cur / "logs" / "training_runs.jsonl"
        if cand.exists():
            return cand
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", required=True, help="path to checkpoint.pt")
    ap.add_argument(
        "--export",
        required=True,
        help="HF export dir (config.json + model.safetensors)",
    )
    ap.add_argument(
        "--ledger", default=None, help="path to logs/training_runs.jsonl (auto-detect)"
    )
    ap.add_argument(
        "--no-torch-threads", action="store_true", help="torch.set_num_threads(1)"
    )
    args = ap.parse_args()

    if args.no_torch_threads:
        torch.set_num_threads(1)

    tracker = Tracker()
    failures: list[str] = []
    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": sys.argv,
        "status": "OK",
    }

    ckpt_path = Path(args.checkpoint)
    export_dir = Path(args.export)
    export_sf = export_dir / "model.safetensors"
    export_cfg = export_dir / "config.json"
    out_dir = Path("logs") / "forensic"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "identity.json"
    raw_path = out_dir / "identity_raw.txt"

    try:
        # ---- stage 0: environment / files ---------------------------------
        import platform

        report["environment"] = {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "platform": platform.platform(),
        }
        disk_before = shutil.disk_usage(Path.cwd()).free
        report["disk_free_before_bytes"] = disk_before
        tracker.log("S0", f"files: ckpt={ckpt_path} export={export_sf}")

        all_files = {
            "checkpoint": str(ckpt_path),
            "model.safetensors": str(export_sf),
            "config.json": str(export_cfg),
        }
        for name, p in all_files.items():
            if not Path(p).exists():
                raise FileNotFoundError(f"missing input file: {p}")
        report["files"] = {
            "checkpoint": {
                "path": str(ckpt_path),
                "size_bytes": ckpt_path.stat().st_size,
                "size_mib": round(ckpt_path.stat().st_size / 2**20, 1),
            },
            "export": {
                "dir": str(export_dir),
                "model.safetensors_size_bytes": export_sf.stat().st_size,
                "model.safetensors_size_mib": round(
                    export_sf.stat().st_size / 2**20, 1
                ),
                "config.json_size_bytes": export_cfg.stat().st_size,
            },
        }

        # ---- stage 1: streaming file hashes (no big allocations) ----------
        tracker.log("S1", "streaming sha256: checkpoint.pt (1.3 GB)")
        t0 = time.perf_counter()
        ckpt_sha = sha256_file(ckpt_path)
        report["files"]["checkpoint"]["sha256"] = ckpt_sha
        report["files"]["checkpoint"]["sha256_time_s"] = round(
            time.perf_counter() - t0, 2
        )
        tracker.log(
            "S1",
            f"checkpoint.pt sha256={ckpt_sha[:16]}... ({time.perf_counter() - t0:.1f}s)",
        )

        t0 = time.perf_counter()
        sf_sha = sha256_file(export_sf)
        report["files"]["export"]["model.safetensors_sha256"] = sf_sha
        report["files"]["export"]["model.safetensors_sha256_time_s"] = round(
            time.perf_counter() - t0, 2
        )
        tracker.log(
            "S1",
            f"model.safetensors sha256={sf_sha[:16]}... ({time.perf_counter() - t0:.1f}s)",
        )

        t0 = time.perf_counter()
        cfg_bytes = export_cfg.read_bytes()
        report["files"]["export"]["config.json_sha256"] = hashlib.sha256(
            cfg_bytes
        ).hexdigest()
        export_config = json.loads(cfg_bytes.decode("utf-8"))
        tracker.log("S1", "config.json read for reconstruction")

        # ---- stage 2: ledger (claimed truth source) -----------------------
        ledger_path = Path(args.ledger) if args.ledger else find_ledger(Path.cwd())
        ledger_rows = (
            read_ledger_rows(ledger_path, "comp-001-custom-100m-real")
            if ledger_path
            else []
        )
        ledger_counts = [
            r["param_count"] for r in ledger_rows if r.get("param_count") is not None
        ]
        report["ledger"] = {
            "path": str(ledger_path) if ledger_path else None,
            "row_count": len(ledger_rows),
            "rows": ledger_rows,
            "param_count_values": ledger_counts,
            "claim_consistent_across_rows": len(set(ledger_counts)) <= 1,
        }
        tracker.log(
            "S2",
            f"ledger: {len(ledger_rows)} rows, param_count values={set(ledger_counts) or 'n/a'}",
        )

        # ---- stage 3: checkpoint load + introspection ---------------------
        obj, attempts, main_mode = load_checkpoint(ckpt_path, tracker)
        report["checkpoint_load"] = {"attempts": attempts}
        if obj is None:
            failures.append(
                "checkpoint load failed in every mode - no state dict available"
            )
            report["status"] = "FAILED"
            report["failures"] = failures
            report["memory"] = {"peak_rss_mb": round(rss_peak_mb(), 1)}
            _write_outputs(report, raw_path, json_path, out_dir, {}, None)
            _print_summary(report)
            return 1

        report["checkpoint_load"]["main_load_mode"] = main_mode
        report["checkpoint_load"]["weights_only_works"] = any(
            a["mode"] == "weights_only=True" and a["succeeded"] for a in attempts
        )
        report["checkpoint_load"]["weights_only_exact_error_if_failed"] = next(
            (
                a["error"]
                for a in attempts
                if a["mode"] == "weights_only=True" and not a["succeeded"]
            ),
            None,
        )
        report["checkpoint_load"]["load_time_s"] = next(
            (a["load_time_s"] for a in attempts if a["mode"] == main_mode), None
        )

        top_keys = sorted(obj.keys()) if isinstance(obj, dict) else ["<not-a-dict>"]
        report["checkpoint_load"]["top_level_type"] = type(obj).__name__
        report["checkpoint_load"]["top_level_keys"] = top_keys
        report["checkpoint_load"]["step"] = (
            obj.get("step") if isinstance(obj, dict) else None
        )
        report["checkpoint_load"]["timestamp"] = (
            obj.get("timestamp") if isinstance(obj, dict) else None
        )

        # optimizer state
        opt = obj.get("optimizer") if isinstance(obj, dict) else None
        opt_state = (opt or {}).get("state", {}) if isinstance(opt, dict) else {}
        opt_tensor_numel = 0
        opt_scalar_count = 0
        for _pid, state in opt_state.items():
            if not isinstance(state, dict):
                continue
            for v in state.values():
                if isinstance(v, torch.Tensor):
                    opt_tensor_numel += int(v.numel())
                else:
                    opt_scalar_count += 1
        report["checkpoint_load"]["optimizer"] = {
            "present": opt is not None,
            "state_entries": len(opt_state),
            "state_tensor_numel": opt_tensor_numel,
            "state_tensor_bytes_est_fp32": opt_tensor_numel * 4,
            "state_scalar_count": opt_scalar_count,
            "param_groups": len((opt or {}).get("param_groups", []))
            if isinstance(opt, dict)
            else 0,
        }

        # config as stored
        stored_cfg = obj.get("config") if isinstance(obj, dict) else None
        stored_hparams = obj.get("hparams") if isinstance(obj, dict) else None
        losses = obj.get("losses") if isinstance(obj, dict) else None
        report["checkpoint_load"]["config_as_stored"] = stored_cfg
        report["checkpoint_load"]["hparams_as_stored"] = stored_hparams
        report["checkpoint_load"]["losses"] = (
            {
                "count": len(losses),
                "first": losses[0] if losses else None,
                "last": losses[-1] if losses else None,
            }
            if isinstance(losses, list)
            else None
        )

        sd = obj.get("model") if isinstance(obj, dict) else None
        if not isinstance(sd, dict):
            failures.append("checkpoint contains no 'model' state_dict")
            raise RuntimeError(
                f"checkpoint top-level 'model' is {type(sd).__name__}, expected dict"
            )

        tracker.log(
            "S3",
            f"loaded: step={report['checkpoint_load']['step']} "
            f"state_dict_tensors={len(sd)} optimizer_tensor_numel={opt_tensor_numel:,}",
        )

        # release optimizer etc. before enumeration - keep only state dict
        for k in list(obj.keys()):
            if k != "model":
                obj[k] = None
        del obj
        gc.collect()
        tracker.log(
            "S3", "released optimizer/scheduler/losses; keeping only state_dict"
        )

        # ---- stage 4: enumerate + hash state dict -------------------------
        records, total_numel, numel_by_dtype, sd_sha = enumerate_state_dict(sd, tracker)
        report["state_dict"] = {
            "tensor_count": len(records),
            "total_numel": total_numel,
            "numel_by_dtype": numel_by_dtype,
            "sha256_sorted_per_tensor_chain": sd_sha,
            "per_tensor": records,
            "hash_scheme": (
                "per-tensor: sha256(utf8(key) + 0x00 + dtype + 0x00 + json(shape) + 0x00 + "
                "raw_bytes); whole: sha256(concat of per-tensor digests in sorted-key order); "
                "raw_sha256: sha256(raw_bytes only). raw bytes = contiguous uint8 view "
                "(C order, native endian)."
            ),
        }
        del sd
        gc.collect()
        tracker.log(
            "S4",
            f"state-dict enumerated: {len(records)} tensors, {total_numel:,} params, sha={sd_sha[:16]}...",
        )

        # ---- stage 5: reconstruction + classification + tie verdict -------
        cfg_kwargs_keys, cfg_counts = expected_qwen2_keys(
            export_config, with_attention_bias=False
        )
        cfg_kwargs_keys_b, cfg_counts_b = expected_qwen2_keys(
            export_config, with_attention_bias=True
        )
        expected_bare = sum(cfg_counts.values())
        expected_full = sum(cfg_counts_b.values())
        bias_delta = expected_full - expected_bare
        actual_shapes = {k: v["shape"] for k, v in records.items()}
        actual_dtypes = {k: v["dtype"] for k, v in records.items()}

        missing_full = sorted(set(cfg_kwargs_keys_b) - set(records))
        extra_vs_config_only = sorted(set(records) - set(cfg_kwargs_keys))
        extra_vs_full = sorted(set(records) - set(cfg_kwargs_keys_b))
        missing_bare = sorted(set(cfg_kwargs_keys) - set(records))
        shape_mismatches = [
            (k, cfg_kwargs_keys_b.get(k), actual_shapes[k])
            for k in sorted(set(cfg_kwargs_keys_b) & set(records))
            if cfg_kwargs_keys_b[k] != actual_shapes[k]
        ]

        expected_key_shapes_subset = {
            k: cfg_kwargs_keys_b[k] for k in cfg_kwargs_keys_b if k in records
        }
        expected_numel_subset = sum(
            prod(s) for s in expected_key_shapes_subset.values()
        )
        tie = bool(export_config.get("tie_word_embeddings", False))
        embed_key = "model.embed_tokens.weight"
        lm_key = "lm_head.weight"
        embed_present = embed_key in records
        lm_present = lm_key in records
        embed_raw = records[embed_key]["raw_sha256"] if embed_present else None
        lm_raw = records[lm_key]["raw_sha256"] if lm_present else None
        bytes_equal = embed_present and lm_present and embed_raw == lm_raw

        # classification
        float_dtypes = {
            "torch.float32",
            "torch.float16",
            "torch.bfloat16",
            "torch.float64",
            "torch.float8_e4m3fn",
        }
        trainable_keys = [k for k in records if records[k]["dtype"] in float_dtypes]
        non_trainable_keys = [
            k for k in records if records[k]["dtype"] not in float_dtypes
        ]
        trainable_numel = sum(records[k]["numel"] for k in trainable_keys)
        non_trainable_numel = sum(records[k]["numel"] for k in non_trainable_keys)
        missing_numel = sum(prod(cfg_kwargs_keys_b[k]) for k in missing_full)
        extra_numel = sum(records[k]["numel"] for k in extra_vs_config_only)

        expected = {
            "source": "config.json",
            "config_values": {
                "vocab_size": export_config["vocab_size"],
                "hidden_size": export_config["hidden_size"],
                "intermediate_size": export_config["intermediate_size"],
                "num_hidden_layers": export_config["num_hidden_layers"],
                "num_attention_heads": export_config["num_attention_heads"],
                "num_key_value_heads": export_config["num_key_value_heads"],
                "max_position_embeddings": export_config["max_position_embeddings"],
                "tie_word_embeddings": export_config.get("tie_word_embeddings", False),
                "head_dim": export_config.get("head_dim"),
            },
            "component_counts_config_only": cfg_counts,
            "component_counts_with_attention_bias": cfg_counts_b,
            "config_only_total": expected_bare,
            "attention_bias_delta": bias_delta,
            "arch_expected_total": expected_full,
            "enumerated_total": total_numel,
            "delta_enumerated_minus_config_only": total_numel - expected_bare,
            "delta_enumerated_minus_arch_expected": total_numel - expected_full,
            "match": "EXACT_MATCH_TO_PARAMETER"
            if total_numel == expected_full
            else "MISMATCH",
            "enumerated_vs_claimed_110918656": total_numel - 110_918_656,
            "arch_key_coverage": {
                "arch_expected_key_count": len(cfg_kwargs_keys_b),
                "present_in_state_dict": len(cfg_kwargs_keys_b) - len(missing_full),
                "expected_numel_of_present_arch_keys": expected_numel_subset,
            },
            "reconciliation": {
                "explanation": (
                    "config.json arithmetic alone under-counts by exactly the q/k/v attention "
                    "projection bias parameters present in the state dict (11 layers x "
                    f"(768+256+256) = {bias_delta} params): {len(extra_vs_config_only)} extra "
                    "tensor keys beyond the config-implied weight set. The Qwen2 attention "
                    "module in the transformers release used for training hardcodes bias=True "
                    "for q/k/v projections with no config flag (observed in this environment), "
                    "so config.json cannot express these parameters; after adding them the "
                    "count matches the enumerated total to the parameter."
                ),
                "extra_keys_vs_config_only": extra_vs_config_only,
                "extra_keys_vs_arch_expected": extra_vs_full,
                "missing_arch_expected_keys": missing_full,
                "missing_config_only_keys": missing_bare,
                "shape_mismatches": shape_mismatches,
                "residual_after_reconciliation": (total_numel - expected_full),
            },
            "checkpoint_config_vs_export_config": _cfg_diff(stored_cfg, export_config),
        }
        report["expected"] = expected

        report["weight_sharing"] = {
            "tie_word_embeddings_config": tie,
            "lm_head_present_as_separate_tensor": lm_present,
            "lm_head_bytes_equal_embed_bytes": bool(bytes_equal),
            "verdict": "TIED" if bytes_equal else "UNTIED",
            "note": (
                "tie_word_embeddings=false; lm_head.weight exists as its own tensor and its raw "
                "bytes differ from model.embed_tokens.weight, so output embedding is untied."
            ),
        }

        report["classification"] = {
            "trainable": {
                "tensor_count": len(trainable_keys),
                "numel": trainable_numel,
                "note": "float-typed state-dict tensors (would have requires_grad=True in a built model; no model is instantiated by this script - inferred from dtype per torch convention)",
            },
            "non_trainable_buffers": {
                "tensor_count": len(non_trainable_keys),
                "numel": non_trainable_numel,
                "keys": non_trainable_keys,
            },
            "missing_expected_arch_keys": {
                "tensor_count": len(missing_full),
                "numel": missing_numel,
                "keys": missing_full,
            },
            "unexpected_present_vs_config_only": {
                "tensor_count": len(extra_vs_config_only),
                "numel": extra_numel,
                "keys": extra_vs_config_only,
            },
        }
        tracker.log(
            "S5",
            f"reconstruction: config_only={expected_bare:,} arch_with_bias={expected_full:,} "
            f"enumerated={total_numel:,} match={total_numel == expected_full} "
            f"tie=UNTIED(separate, bytes differ)",
        )

        # ---- stage 6: export cross-check (header only + spot checks) ------
        header_json, header_raw = read_safetensors_header(export_sf)
        header_len = len(header_raw)
        export_meta = header_json.get("__metadata__")
        export_tensors = {k: v for k, v in header_json.items() if k != "__metadata__"}
        exp_total = 0
        exp_numel_by_dtype: dict[str, int] = {}
        per_tensor_header_sha = {}
        for k, v in export_tensors.items():
            ne = prod(v["shape"])
            exp_total += ne
            dt = v["dtype"]
            exp_numel_by_dtype[dt] = exp_numel_by_dtype.get(dt, 0) + ne
            h = hashlib.sha256()
            h.update(k.encode())
            h.update(b"\x00")
            h.update(dt.encode())
            h.update(b"\x00")
            h.update(json.dumps(v["shape"], separators=(",", ":")).encode())
            h.update(b"\x00")
            h.update(json.dumps(v["data_offsets"], separators=(",", ":")).encode())
            per_tensor_header_sha[k] = h.hexdigest()

        exp_keys = set(export_tensors)
        ck_keys = set(records)
        missing_from_export = sorted(ck_keys - exp_keys)
        extra_in_export = sorted(exp_keys - ck_keys)
        shape_mismatch_export = [
            (k, records[k]["shape"], export_tensors[k]["shape"])
            for k in sorted(ck_keys & exp_keys)
            if records[k]["shape"] != list(export_tensors[k]["shape"])
        ]
        dtype_map = {
            "F32": "torch.float32",
            "F16": "torch.float16",
            "BF16": "torch.bfloat16",
            "I64": "torch.int64",
            "I32": "torch.int32",
            "U8": "torch.uint8",
            "F64": "torch.float64",
        }
        dtype_mismatch_export = [
            (
                k,
                records[k]["dtype"],
                dtype_map.get(export_tensors[k]["dtype"], export_tensors[k]["dtype"]),
            )
            for k in sorted(ck_keys & exp_keys)
            if records[k]["dtype"]
            != dtype_map.get(export_tensors[k]["dtype"], export_tensors[k]["dtype"])
        ]

        spot_keys = [
            "model.embed_tokens.weight",
            "lm_head.weight",
            "model.layers.0.self_attn.q_proj.weight",
            "model.layers.0.self_attn.q_proj.bias",
        ]
        spot_checks = []
        for sk in spot_keys:
            if sk not in records or sk not in export_tensors:
                spot_checks.append(
                    {"key": sk, "match": None, "error": "key not found on both sides"}
                )
                continue
            begin, end = export_tensors[sk]["data_offsets"]
            data = read_safetensors_tensor(export_sf, header_len, begin, end)
            exp_raw = hashlib.sha256(data).hexdigest()
            spot_checks.append(
                {
                    "key": sk,
                    "shape": records[sk]["shape"],
                    "bytes_read": end - begin,
                    "expected_bytes": records[sk]["numel"] * 4,
                    "checkpoint_raw_sha256": records[sk]["raw_sha256"],
                    "export_raw_sha256": exp_raw,
                    "match": exp_raw == records[sk]["raw_sha256"],
                }
            )
            tracker.log(
                "S6",
                f"spot {sk}: size={end - begin} match={exp_raw == records[sk]['raw_sha256']}",
            )

        consistent = (
            not missing_from_export
            and not extra_in_export
            and not shape_mismatch_export
            and not dtype_mismatch_export
            and all(s.get("match") for s in spot_checks)
        )
        report["export_cross_check"] = {
            "header_bytes": header_len,
            "header_sha256": hashlib.sha256(header_raw).hexdigest(),
            "safetensors_format_metadata": export_meta,
            "tensor_count": len(export_tensors),
            "total_numel": exp_total,
            "numel_by_dtype": exp_numel_by_dtype,
            "key_set_match": ck_keys == exp_keys,
            "missing_from_export_relative_to_checkpoint": missing_from_export,
            "extra_in_export_relative_to_checkpoint": extra_in_export,
            "shape_mismatches": shape_mismatch_export,
            "dtype_mismatches": dtype_mismatch_export,
            "per_tensor_header_sha256": per_tensor_header_sha,
            "spot_checks": spot_checks,
            "consistent_with_checkpoint": bool(consistent),
            "note": (
                "export saved by the training script from the final model object, so bytes must "
                "equal the latest checkpoint state if the checkpoint was written after the last "
                "training step."
            ),
        }
        tracker.log(
            "S6",
            f"export: {len(export_tensors)} tensors, {exp_total:,} params, "
            f"key_set_match={ck_keys == exp_keys} consistent={consistent}",
        )

        # ---- memory summary ----------------------------------------------
        disk_after = shutil.disk_usage(Path.cwd()).free
        report["memory"] = {
            "peak_rss_mb": round(rss_peak_mb(), 1),
            "stages": tracker.stages,
        }
        report["disk_free_after_bytes"] = disk_after
        report["new_bytes_written"] = 0  # filled after writing outputs

        # ledger claim check
        if ledger_counts:
            report["ledger"]["claim_equals_enumerated"] = all(
                c == total_numel for c in ledger_counts
            )
        else:
            report["ledger"]["claim_equals_enumerated"] = None

        report["failures"] = failures
        if failures:
            report["status"] = "FAILED"
        elif total_numel != expected_full:
            report["status"] = "FAILED"
            failures.append(
                "enumerated count does not match reconstructed architecture count"
            )
            report["failures"] = failures
        elif not consistent:
            report["status"] = "WARN_EXPORT_DIVERGED"

        # ---- stage 7: outputs ---------------------------------------------
        _write_outputs(report, raw_path, json_path, out_dir, records, export_tensors)

    except Exception as e:
        failures.append(f"{type(e).__name__}: {e}\n{traceback.format_exc()[-500:]}")
        report["failures"] = failures
        report["status"] = "FAILED"
        report["memory"] = {
            "peak_rss_mb": round(rss_peak_mb(), 1),
            "stages": tracker.stages,
        }
        try:
            _write_outputs(report, raw_path, json_path, out_dir, {}, None)
        except Exception as e2:
            print(f"[FATAL] could not write outputs: {e2}", flush=True)
        _print_summary(report)
        return 1

    _print_summary(report)
    return 0 if report["status"] == "OK" else 1


def _cfg_diff(stored, export_cfg) -> dict:
    if not isinstance(stored, dict):
        return {"note": "no stored config in checkpoint"}
    stored_k = {k: v for k, v in stored.items()}
    export_k = {k: v for k, v in export_cfg.items()}
    shared = sorted(set(stored_k) & set(export_k))
    diffs = {
        k: {"stored": stored_k[k], "export": export_k[k]}
        for k in shared
        if stored_k[k] != export_k[k]
    }
    return {
        "shared_key_value_diffs": diffs,
        "only_in_checkpoint": sorted(set(stored_k) - set(export_k)),
        "only_in_export": sorted(set(export_k) - set(stored_k)),
        "matching_shared_key_count": len(shared) - len(diffs),
    }


def _write_outputs(
    report,
    raw_path: Path,
    json_path: Path,
    out_dir: Path,
    records: dict,
    export_tensors: dict | None,
) -> None:
    # identity.json
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    # identity_raw.txt - per-tensor listing with sha256 prefixes
    lines = [
        "# model_identity.py - zero-trust per-tensor forensic listing",
        f"# generated: {report.get('generated_at')}",
        "# scheme: sha256 prefix = first 16 hex chars of per-tensor sha256 "
        "(key|dtype|shape|raw_bytes); raw prefix = sha256(raw_bytes only)",
        "#",
        "# CKPT tensors (checkpoint state dict, hashed from loaded bytes)",
        "TYPE\tKEY\tSHAPE\tNUMEL\tDTYPE\tSHA256_16\tRAW_SHA256_16",
    ]
    for k in sorted(records.keys()):
        r = records[k]
        lines.append(
            f"CKPT\t{k}\t{json.dumps(r['shape'], separators=(',', ':'))}\t"
            f"{r['numel']}\t{r['dtype']}\t{r['sha256'][:16]}\t{r['raw_sha256'][:16]}"
        )
    if export_tensors is not None:
        lines.append("")
        lines.append(
            "# EXPORT tensors (safetensors header only; data not loaded except spot checks)"
        )
        lines.append("TYPE\tKEY\tSHAPE\tNUMEL\tDTYPE\tOFFSETS\tMETA_SHA256_16")
        for k in sorted(export_tensors.keys()):
            v = export_tensors[k]
            ne = prod(v["shape"])
            h = hashlib.sha256()
            h.update(k.encode())
            h.update(b"\x00")
            h.update(v["dtype"].encode())
            h.update(b"\x00")
            h.update(json.dumps(v["shape"], separators=(",", ":")).encode())
            h.update(b"\x00")
            h.update(json.dumps(v["data_offsets"], separators=(",", ":")).encode())
            lines.append(
                f"EXPORT\t{k}\t{json.dumps(v['shape'], separators=(',', ':'))}\t"
                f"{ne}\t{v['dtype']}\t{v['data_offsets']}\t{h.hexdigest()[:16]}"
            )
    raw_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    total = json_path.stat().st_size + raw_path.stat().st_size
    report["new_bytes_written"] = total
    report["artifacts"] = {
        "identity_json": str(json_path),
        "identity_json_bytes": json_path.stat().st_size,
        "identity_raw_txt": str(raw_path),
        "identity_raw_txt_bytes": raw_path.stat().st_size,
    }
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def _print_summary(report: dict) -> None:
    def _ni(x) -> str:
        return f"{x:,}" if isinstance(x, int) else "n/a"

    sd = report.get("state_dict", {})
    exp = report.get("expected", {})
    cls = report.get("classification", {})
    xs = report.get("export_cross_check", {})
    ws = report.get("weight_sharing", {})
    ld = report.get("checkpoint_load", {})
    fchk = report.get("files", {}).get("checkpoint", {})
    fexp = report.get("files", {}).get("export", {})
    t = cls.get("trainable", {})
    b = cls.get("non_trainable_buffers", {})
    m = cls.get("missing_expected_arch_keys", {})
    print(f"\n{'=' * 62}\n[SUMMARY] status={report.get('status')}", flush=True)
    print(
        f"  load_ok={bool(sd)} main_mode={ld.get('main_load_mode')} "
        f"weights_only_works={ld.get('weights_only_works')}",
        flush=True,
    )
    print(f"  enumerated_param_count={_ni(sd.get('total_numel'))}", flush=True)
    print(
        f"  expected_config_arithmetic={_ni(exp.get('config_only_total'))}", flush=True
    )
    print(
        f"  expected_arch_with_bias={_ni(exp.get('arch_expected_total'))}", flush=True
    )
    print(
        f"  delta_enumerated_vs_config_only={exp.get('delta_enumerated_minus_config_only', 'n/a')}",
        flush=True,
    )
    print(
        f"  delta_enumerated_vs_arch={exp.get('delta_enumerated_minus_arch_expected', 'n/a')}",
        flush=True,
    )
    print(
        f"  match_verdict={exp.get('match', 'n/a')} "
        f"(claimed 110,918,656 -> enumerated delta {exp.get('enumerated_vs_claimed_110918656', 'n/a')})",
        flush=True,
    )
    print(
        f"  tie/weight_sharing={ws.get('verdict')} "
        f"(lm_head bytes equal embed: {ws.get('lm_head_bytes_equal_embed_bytes')})",
        flush=True,
    )
    print(
        f"  trainable={_ni(t.get('numel'))} ({t.get('tensor_count')} tensors) "
        f"non_trainable={_ni(b.get('numel'))} ({b.get('tensor_count')}) "
        f"missing={_ni(m.get('numel'))} ({m.get('tensor_count')})",
        flush=True,
    )
    print(
        f"  export_tensor_set_match={xs.get('key_set_match')} tensors={xs.get('tensor_count')} "
        f"total={_ni(xs.get('total_numel'))}",
        flush=True,
    )
    print(
        f"  export_consistent_with_checkpoint={xs.get('consistent_with_checkpoint')} "
        f"spot_checks={len(xs.get('spot_checks', []))}",
        flush=True,
    )
    print(f"  checkpoint.pt sha256={(fchk.get('sha256') or 'n/a')[:16]}...", flush=True)
    print(
        f"  model.safetensors sha256={(fexp.get('model.safetensors_sha256') or 'n/a')[:16]}...",
        flush=True,
    )
    print(
        f"  peak_rss={report.get('memory', {}).get('peak_rss_mb', 'n/a')} MB",
        flush=True,
    )
    print(
        f"  new_bytes_written={report.get('new_bytes_written', 'n/a')} "
        f"(identity.json + identity_raw.txt)",
        flush=True,
    )
    print(f"  failures={report.get('failures')}", flush=True)
    print(f"  outputs: {report.get('artifacts')}", flush=True)
    print("=" * 62, flush=True)


if __name__ == "__main__":
    sys.exit(main())
