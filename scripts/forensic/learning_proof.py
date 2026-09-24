#!/usr/bin/env python3
"""learning_proof.py - brutal, byte-level forensics: did the weights actually move?

Primary question, measured from the artifact, never assumed: after 1,669
optimizer steps (checkpoint-200 -> checkpoint-1869) did the model weights
change, by how much, where, and is there any sign optimization actually ran
(vs a no-op resume that merely re-saved the same weights)?

Evidence produced here:
  1. Per-tensor abs-delta stats earliest-vs-latest, exact zero detection, and
     fraction-of-parameters-changed at epsilon thresholds relative to tensor std.
  2. Dead/saturated-layer detection: tensors whose delta-max == 0 (completely
     unchanged), and tensors whose relative change (||delta||/||weights||) < 1e-3.
  3. NaN/Inf/overflow/underflow scan of every tensor in earliest, latest, delta,
     and of the optimizer state (exp_avg, exp_avg_sq, per-param step).
  4. Gradient-flow health from the optimizer state. The checkpoint stores NO raw
     gradients, so AdamW exp_avg / exp_avg_sq are used as smoothed gradient and
     variance proxies and the effective per-parameter update magnitude
     exp_avg/sqrt(exp_avg_sq+eps) is reported. Every such number is labeled PROXY.
  5. An inference-only activation scan (no backprop) on 8 real corpus rows through
     the HF export model.safetensors (byte-identical to checkpoint-1869 per F1).
  6. Per-tensor SHA-256 prefixes (earliest + latest) + file SHA-256 of both
     checkpoint.pt files.
  7. Optional theoretical reconstruction (--by-seed-42-init): instantiate the
     config with seed 42 (the training seed) and compare latest-vs-fresh-init.
     Labeled as a reconstruction; the empirically grounded comparison is
     earliest-vs-latest.

Memory discipline (this box is RAM-starved):
  * all checkpoint loads use torch.load(..., mmap=True): a 1.27 GB checkpoint is
    memory-mapped, not resident; tensors are analyzed one at a time and released;
  * "LOAD ONE CHECKPOINT AT A TIME" phases (S3, S4): only one checkpoint open;
  * the delta phase (S5/S6) holds both checkpoints memory-mapped simultaneously
    but never both resident - per-tensor working set only;
  * del + gc.collect() between every phase; peak RSS measured per phase.

Outputs (small text only):
  logs/forensic/learning.json
  logs/forensic/learning_raw.txt
  logs/forensic/learning_curve.csv
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import re
import shutil
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

REPO_ROOT = Path(__file__).resolve().parents[2]
PAD_ID, BOS_ID, EOS_ID = 0, 1, 2  # from bpe_tokenizer.py special-token order

# Same config dict the training harness uses for the 100m variant
# (scripts/training/train_comp001.py MODEL_CFG_100M), vocab filled by the real
# BPE tokenizer (10,240).
MODEL_CFG_100M = dict(
    vocab_size=10240,
    hidden_size=768,
    intermediate_size=3072,
    num_hidden_layers=11,
    num_attention_heads=12,
    num_key_value_heads=4,
    max_position_embeddings=512,
    pad_token_id=PAD_ID,
    bos_token_id=BOS_ID,
    eos_token_id=EOS_ID,
    tie_word_embeddings=False,
)

LAYER_REGEX = re.compile(r"^model\.layers\.(\d+)\.(.*)$")
COMPONENT_BUCKETS = [
    "embed",
    "attn_qkv",
    "attn_o",
    "mlp_gate",
    "mlp_up",
    "mlp_down",
    "layer_norms",
    "final_norm",
    "lm_head",
]


# ---------------------------------------------------------------------------
# memory / time helpers (same Win32 probes as model_identity.py)
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


def _win_mem_counters():
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

    def warn_avail(self, floor_mb: float = 200.0) -> None:
        avail = _avail_phys_mb()
        if avail is not None and avail < floor_mb:
            print(
                f"[GUARD] WARNING: only {avail:.0f} MB physical memory available "
                f"(floor {floor_mb:.0f} MB) - paging/swap expected",
                flush=True,
            )


# ---------------------------------------------------------------------------
# file / tensor helpers
# ---------------------------------------------------------------------------


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
    """Canonical raw bytes of a tensor (C order, native endian)."""
    c = t.detach().contiguous()
    try:
        return c.view(torch.uint8).reshape(-1).numpy().tobytes()
    except Exception:
        return c.float().numpy().tobytes()


def per_tensor_sha256(key: str, t: torch.Tensor) -> str:
    """Same composite scheme as model_identity.py so the two reports interlock."""
    raw = tensor_raw_bytes(t)
    h = hashlib.sha256()
    h.update(key.encode("utf-8"))
    h.update(b"\x00")
    h.update(str(t.dtype).encode("utf-8"))
    h.update(b"\x00")
    h.update(json.dumps(list(t.shape), separators=(",", ":")).encode("utf-8"))
    h.update(b"\x00")
    h.update(raw)
    return h.hexdigest()


def load_ckpt(path: Path):
    """torch.load with mmap=True (lazy tensor storage). Returns top-level dict."""
    last_err = None
    for weights_only in (True, False):
        try:
            return torch.load(
                path, map_location="cpu", weights_only=weights_only, mmap=True
            )
        except Exception as e:
            last_err = e
            gc.collect()
    raise RuntimeError(f"could not mmap-load {path}: {last_err}")


def free(obj) -> None:
    del obj
    gc.collect()


# ---------------------------------------------------------------------------
# tensor statistics
# ---------------------------------------------------------------------------


def single_tensor_stats(t: torch.Tensor) -> dict:
    """Scalar stats of one weight tensor (no big extra allocations)."""
    n = int(t.numel())
    nan = int(torch.isnan(t).sum())
    inf = int(torch.isinf(t).sum())
    zeros = int((t == 0).sum())
    mean = float(t.mean()) if n else 0.0
    std = float(t.std()) if n > 1 else 0.0
    amin = float(t.min()) if n else 0.0
    amax = float(t.max()) if n else 0.0
    ad = t.abs()
    abs_mean = float(ad.mean()) if n else 0.0
    l2 = float((t.detach().pow(2).sum()).sqrt())
    del ad
    return {
        "numel": n,
        "nan": nan,
        "inf": inf,
        "zeros": zeros,
        "zero_fraction": zeros / n if n else 0.0,
        "mean": mean,
        "std": std,
        "min": amin,
        "max": amax,
        "abs_mean": abs_mean,
        "l2_norm": l2,
    }


def row_zero_counts(t: torch.Tensor) -> dict:
    """For 2-D tensors (embedding/lm_head): how many rows are all-zero."""
    if t.dim() != 2:
        return {"rows": 0, "all_zero_rows": None}
    r = int((t.abs().sum(dim=1) == 0).sum())
    return {"rows": int(t.shape[0]), "all_zero_rows": r}


def delta_tensor_stats(
    d: torch.Tensor, std_scale: float, sample: list | None, sample_target: int
) -> dict:
    """Abs-delta stats of one tensor vs an 'earlier' state.

    std_scale is the std of the reference (earliest / init) weights; the
    epsilon-threshold fractions are computed as frac(|d| > eps * std_scale).
    A deterministic strided sample of abs-delta values is accumulated into
    `sample` (used later for an approximate global median).
    """
    n = int(d.numel())
    nan = int(torch.isnan(d).sum())
    inf = int(torch.isinf(d).sum())
    ad = d.abs()
    abs_mean = float(ad.mean()) if n else 0.0
    abs_median = float(ad.median()) if n else 0.0
    abs_std = float(ad.std()) if n > 1 else 0.0
    abs_max = float(ad.max()) if n else 0.0
    nz = int(torch.count_nonzero(d))
    tiny = int((ad < 1e-30).sum())
    l2 = float((d.detach().pow(2).sum()).sqrt())
    fracs = {}
    for eps in (1e-6, 1e-4, 1e-3, 1e-2):
        th = eps * std_scale if std_scale > 0 else float("inf")
        fracs[f"gt_{eps:g}_x_std"] = float((ad > th).sum()) / n if n else 0.0
    if sample is not None and n:
        remaining = sample_target - sum(len(s) for s in sample)
        if remaining > 0:
            stride = max(1, math.ceil(n / max(1, remaining)))
            sample.append(ad[::stride].detach())
    del ad
    return {
        "numel": n,
        "nan": nan,
        "inf": inf,
        "abs_mean": abs_mean,
        "abs_median": abs_median,
        "abs_std": abs_std,
        "abs_max": abs_max,
        "nonzero": nz,
        "frac_nonzero": nz / n if n else 0.0,
        "below_1e-30": tiny,
        "below_1e-30_fraction": tiny / n if n else 0.0,
        "l2_norm": l2,
        **fracs,
    }


def tensor_group(key: str) -> tuple[str, int | None]:
    """Bucket a state-dict key into one of COMPONENT_BUCKETS (and a layer id)."""
    if key == "model.embed_tokens.weight":
        return ("embed", None)
    if key == "lm_head.weight":
        return ("lm_head", None)
    if key == "model.norm.weight":
        return ("final_norm", None)
    m = LAYER_REGEX.match(key)
    if not m:
        return ("other", None)
    layer = int(m.group(1))
    sub = m.group(2)
    if "self_attn" in sub:
        if ".q_proj" in sub or ".k_proj" in sub or ".v_proj" in sub:
            return ("attn_qkv", layer)
        return ("attn_o", layer)
    if "gate_proj" in sub:
        return ("mlp_gate", layer)
    if "up_proj" in sub:
        return ("mlp_up", layer)
    if "down_proj" in sub:
        return ("mlp_down", layer)
    return ("layer_norms", layer)


def optimizer_param_names() -> list[str]:
    """Deterministic 135-name parameter order for the 100m Qwen2 config.

    Derived from the module registration order of Qwen2ForCausalLM (embed; per
    layer: q/k/v/o weight then bias, mlp gate/up/down weights, input_layernorm,
    post_attention_layernorm; final norm; lm_head) and validated against the
    actual state-dict key set at runtime.
    """
    names: list[str] = ["model.embed_tokens.weight"]
    for i in range(MODEL_CFG_100M["num_hidden_layers"]):
        p = f"model.layers.{i}"
        for proj, bias in (
            ("q_proj", True),
            ("k_proj", True),
            ("v_proj", True),
            ("o_proj", False),
        ):
            names.append(f"{p}.self_attn.{proj}.weight")
            if bias:
                names.append(f"{p}.self_attn.{proj}.bias")
        names.append(f"{p}.mlp.gate_proj.weight")
        names.append(f"{p}.mlp.up_proj.weight")
        names.append(f"{p}.mlp.down_proj.weight")
        names.append(f"{p}.input_layernorm.weight")
        names.append(f"{p}.post_attention_layernorm.weight")
    names.append("model.norm.weight")
    names.append("lm_head.weight")
    assert len(names) == 135, f"expected 135 params, got {len(names)}"
    return names


def validate_optimizer_names(names: list[str], state_keys: set[str]) -> None:
    mismatch = set(names) ^ state_keys
    if mismatch:
        raise RuntimeError(
            f"parameter-order reconstruction mismatch vs state dict "
            f"({len(mismatch)} keys): {sorted(mismatch)[:6]}"
        )


# ---------------------------------------------------------------------------
# optimizer-state proxy analysis
# ---------------------------------------------------------------------------


def analyze_optimizer_state(opt: dict, names: list[str]) -> dict:
    """AdamW state -> gradient-flow proxies. No raw gradients are stored, so
    every result here is a PROXY: exp_avg (1st moment ~ smoothed gradient),
    exp_avg_sq (2nd moment ~ gradient variance), effective update magnitude
    exp_avg / sqrt(exp_avg_sq + 1e-8) (AdamW numerator, pre-lr)."""
    state = opt.get("state", {})
    groups = opt.get("param_groups", [])
    lrs = sorted({g.get("lr") for g in groups if isinstance(g, dict)} - {None})
    rows: dict[str, dict] = {}
    group_acc = {
        b: {
            "sum_exp_avg_abs": 0.0,
            "sum_exp_avg_sq_abs": 0.0,
            "sum_eff_abs": 0.0,
            "sum_eff_sq": 0.0,
            "max_eff": 0.0,
            "numel": 0,
        }
        for b in COMPONENT_BUCKETS
    }
    starved: list[str] = []
    nan_inf: dict[str, list[str]] = {"nan": [], "inf": []}
    extreme = {"gt_1e30": [], "lt_1e-30": [], "all_zero": []}
    step_min, step_max, step_nan = None, None, []
    total = {
        "sum_exp_avg_abs": 0.0,
        "sum_exp_avg_sq_abs": 0.0,
        "sum_eff_abs": 0.0,
        "sum_eff_sq": 0.0,
        "max_eff": 0.0,
        "numel": 0,
    }
    for pid in sorted(state, key=int):
        s = state[pid]
        name = names[int(pid)]
        comp, _layer = tensor_group(name)
        ea = s["exp_avg"]
        es = s["exp_avg_sq"]
        stepv = s["step"]
        step_f = float(stepv) if torch.is_tensor(stepv) else float(stepv)
        step_min = step_f if step_min is None else min(step_min, step_f)
        step_max = step_f if step_max is None else max(step_max, step_f)
        if torch.is_tensor(stepv) and bool(torch.isnan(stepv).any()):
            step_nan.append(name)
        n = int(ea.numel())
        ea_abs = ea.abs()
        es_abs = es.abs()
        eff = ea_abs / (es.sqrt() + 1e-8)
        eff_abs = eff.abs()
        row = {
            "numel": n,
            "exp_avg_mean": float(ea.mean()),
            "exp_avg_abs_mean": float(ea_abs.mean()),
            "exp_avg_std": float(ea.std()),
            "exp_avg_max_abs": float(ea_abs.max()),
            "exp_avg_sq_mean": float(es.mean()),
            "exp_avg_sq_abs_mean": float(es_abs.mean()),
            "exp_avg_sq_std": float(es.std()),
            "exp_avg_sq_max": float(es.max()),
            "eff_update_mean": float(eff_abs.mean()),
            "eff_update_std": float(eff_abs.std()),
            "eff_update_max": float(eff_abs.max()),
            "exp_avg_nan": int(torch.isnan(ea).sum()) if n else 0,
            "exp_avg_inf": int(torch.isinf(ea).sum()) if n else 0,
            "exp_avg_gt_1e30": int((ea_abs > 1e30).sum()),
            "exp_avg_lt_1e-30": int((ea_abs < 1e-30).sum()),
            "exp_avg_zero_fraction": float((ea == 0).sum()) / n if n else 0.0,
            "exp_avg_sq_nan": int(torch.isnan(es).sum()) if n else 0,
            "exp_avg_sq_inf": int(torch.isinf(es).sum()) if n else 0,
            "exp_avg_sq_gt_1e30": int((es_abs > 1e30).sum()),
            "exp_avg_sq_lt_1e-30": int((es_abs < 1e-30).sum()),
            "exp_avg_sq_zero_fraction": float((es == 0).sum()) / n if n else 0.0,
            "step": step_f,
            "component": comp,
        }
        if row["exp_avg_nan"] or row["exp_avg_sq_nan"]:
            nan_inf["nan"].append(name)
        if row["exp_avg_inf"] or row["exp_avg_sq_inf"]:
            nan_inf["inf"].append(name)
        if row["exp_avg_gt_1e30"] or row["exp_avg_sq_gt_1e30"]:
            extreme["gt_1e30"].append(name)
        if row["exp_avg_lt_1e-30"] or row["exp_avg_sq_lt_1e-30"]:
            extreme["lt_1e-30"].append(name)
        if (
            row["exp_avg_zero_fraction"] > 0.999
            and row["exp_avg_sq_zero_fraction"] > 0.999
        ):
            extreme["all_zero"].append(name)
        # gradient starvation: never a meaningful update anywhere in the tensor
        if row["eff_update_max"] == 0.0:
            starved.append(name)
        rows[name] = row
        ga = group_acc[comp]
        ga["numel"] += n
        ga["sum_exp_avg_abs"] += row["exp_avg_abs_mean"] * n
        ga["sum_exp_avg_sq_abs"] += row["exp_avg_sq_abs_mean"] * n
        ga["sum_eff_abs"] += row["eff_update_mean"] * n
        ga["sum_eff_sq"] += (
            row["eff_update_mean"] ** 2 + row["eff_update_std"] ** 2
        ) * n
        ga["max_eff"] = max(ga["max_eff"], row["eff_update_max"])
        total["numel"] += n
        total["sum_exp_avg_abs"] += row["exp_avg_abs_mean"] * n
        total["sum_exp_avg_sq_abs"] += row["exp_avg_sq_abs_mean"] * n
        total["sum_eff_abs"] += row["eff_update_mean"] * n
        total["sum_eff_sq"] += (
            row["eff_update_mean"] ** 2 + row["eff_update_std"] ** 2
        ) * n
        total["max_eff"] = max(total["max_eff"], row["eff_update_max"])
        del ea_abs, es_abs, eff, eff_abs

    per_component = {}
    for comp, g in group_acc.items():
        if g["numel"] == 0:
            continue
        mean_eff = g["sum_eff_abs"] / g["numel"]
        var_eff = max(0.0, g["sum_eff_sq"] / g["numel"] - mean_eff**2)
        per_component[comp] = {
            "numel": g["numel"],
            "exp_avg_abs_mean": g["sum_exp_avg_abs"] / g["numel"],
            "exp_avg_sq_abs_mean": g["sum_exp_avg_sq_abs"] / g["numel"],
            "eff_update_abs_mean": mean_eff,
            "eff_update_std": var_eff**0.5,
            "eff_update_max": g["max_eff"],
        }
    mean_eff = total["sum_eff_abs"] / total["numel"] if total["numel"] else 0.0
    var_eff = max(0.0, total["sum_eff_sq"] / total["numel"] - mean_eff**2)
    return {
        "label": (
            "PROXY: checkpoint stores no raw gradients; AdamW optimizer moments "
            "exp_avg (smoothed gradient) and exp_avg_sq (variance) from "
            "checkpoint-1869 are used as proxies; effective update magnitude = "
            "|exp_avg| / (sqrt(exp_avg_sq) + 1e-8) (AdamW numerator, pre-learning-rate)."
        ),
        "param_count": len(rows),
        "param_groups_lr": lrs,
        "step_min": step_min,
        "step_max": step_max,
        "step_nan_tensors": step_nan,
        "nan_inf_tensors": nan_inf,
        "extreme_magnitude_tensors": extreme,
        "global": {
            "exp_avg_abs_mean": (
                total["sum_exp_avg_abs"] / total["numel"] if total["numel"] else 0.0
            ),
            "exp_avg_sq_abs_mean": (
                total["sum_exp_avg_sq_abs"] / total["numel"] if total["numel"] else 0.0
            ),
            "eff_update_abs_mean": mean_eff,
            "eff_update_std": var_eff**0.5,
            "eff_update_max": total["max_eff"],
            "numel": total["numel"],
        },
        "per_component": per_component,
        "per_tensor": rows,
        "starved_tensors": starved,
        "starvation_note": (
            "starved = tensors whose effective update magnitude is exactly 0 "
            "everywhere (max |exp_avg/(sqrt(exp_avg_sq)+eps)| == 0.0)"
        ),
    }


# ---------------------------------------------------------------------------
# delta comparison machinery
# ---------------------------------------------------------------------------


def compare_state_dicts(
    a: dict,
    b: dict,
    label_a: str,
    label_b: str,
    sample_target: int = 2_000_000,
) -> dict:
    """Per-tensor delta analysis of state dict `a` (earlier) vs `b` (later).

    Both dicts contain mmap'd or in-RAM tensors; analysis is per-tensor, so the
    working set never holds more than the pair of tensors being differenced.
    Returns per-tensor records, aggregates, and dead-layer flags.
    """
    keys = sorted(a.keys())
    kb = set(b.keys())
    missing_b = sorted(k for k in keys if k not in kb)
    extra_b = sorted(k for k in kb if k not in set(keys))

    per_tensor: dict[str, dict] = {}
    sample: list = []
    agg = {
        "numel": 0,
        "sum_abs": 0.0,
        "sum_sq": 0.0,
        "max_abs": 0.0,
        "nz": 0,
        "l2_delta_sq": 0.0,
        "l2_w_a_sq": 0.0,
        "nan": 0,
        "inf": 0,
        "frac_gt": {1e-6: 0, 1e-4: 0, 1e-3: 0, 1e-2: 0},
        "tensors_changed": 0,
        "tensor_count": 0,
    }
    comp_acc = {
        b: {
            "numel": 0,
            "sum_abs": 0.0,
            "sum_sq": 0.0,
            "max_abs": 0.0,
            "nz": 0,
            "l2_delta_sq": 0.0,
            "l2_w_a_sq": 0.0,
        }
        for b in COMPONENT_BUCKETS
    }
    layer_acc: dict[int, dict] = {}
    for key in keys:
        t_a = a[key]
        t_b = b[key]
        n = int(t_b.numel())
        comp, layer = tensor_group(key)
        # reference scale: std of the EARLIER weights
        std_a = float(t_a.std()) if n > 1 else 0.0
        l2_a = float((t_a.detach().pow(2).sum()).sqrt())
        d = t_b - t_a
        dstats = delta_tensor_stats(d, std_a, sample, sample_target)
        l2_d = dstats["l2_norm"]
        rel = (l2_d / l2_a) if l2_a > 0 else float("inf")
        rec = {
            "shape": list(t_b.shape),
            "dtype": str(t_b.dtype),
            "numel": n,
            "component": comp,
            "layer": layer,
            "delta": dstats,
            "weights_a_l2": l2_a,
            "weights_a_std": std_a,
            "rel_change_vs_a": rel,
        }
        per_tensor[key] = rec
        nz = dstats["nonzero"]
        agg["numel"] += n
        agg["sum_abs"] += dstats["abs_mean"] * n
        agg["sum_sq"] += (dstats["abs_mean"] ** 2 + dstats["abs_std"] ** 2) * n
        agg["max_abs"] = max(agg["max_abs"], dstats["abs_max"])
        agg["nz"] += nz
        agg["l2_delta_sq"] += l2_d**2
        agg["l2_w_a_sq"] += l2_a**2
        agg["nan"] += dstats["nan"]
        agg["inf"] += dstats["inf"]
        for eps in agg["frac_gt"]:
            agg["frac_gt"][eps] += dstats[f"gt_{eps:g}_x_std"] * n
        agg["tensor_count"] += 1
        if dstats["abs_max"] > 0:
            agg["tensors_changed"] += 1
        ca = comp_acc[comp]
        ca["numel"] += n
        ca["sum_abs"] += dstats["abs_mean"] * n
        ca["sum_sq"] += (dstats["abs_mean"] ** 2 + dstats["abs_std"] ** 2) * n
        ca["max_abs"] = max(ca["max_abs"], dstats["abs_max"])
        ca["nz"] += nz
        ca["l2_delta_sq"] += l2_d**2
        ca["l2_w_a_sq"] += l2_a**2
        if layer is not None:
            la = layer_acc.setdefault(
                layer,
                {
                    "numel": 0,
                    "sum_abs": 0.0,
                    "sum_sq": 0.0,
                    "max_abs": 0.0,
                    "nz": 0,
                    "l2_delta_sq": 0.0,
                    "l2_w_a_sq": 0.0,
                },
            )
            la["numel"] += n
            la["sum_abs"] += dstats["abs_mean"] * n
            la["sum_sq"] += (dstats["abs_mean"] ** 2 + dstats["abs_std"] ** 2) * n
            la["max_abs"] = max(la["max_abs"], dstats["abs_max"])
            la["nz"] += nz
            la["l2_delta_sq"] += l2_d**2
            la["l2_w_a_sq"] += l2_a**2
        del d

    total = agg["numel"]
    mean_abs = agg["sum_abs"] / total if total else 0.0
    var_abs = max(0.0, agg["sum_sq"] / total - mean_abs**2) if total else 0.0
    sample_cat = (
        torch.cat([s.reshape(-1) for s in sample]) if sample else torch.empty(0)
    )
    sampled_median = float(sample_cat.median()) if sample_cat.numel() else None
    dead = [k for k, r in per_tensor.items() if r["delta"]["abs_max"] == 0.0]
    below_eps = [
        k
        for k, r in per_tensor.items()
        if r["delta"]["abs_max"] > 0.0 and r["delta"]["abs_max"] < 1e-38
    ]
    dead_relative = sorted(
        [
            {"tensor": k, "rel_change": r["rel_change_vs_a"]}
            for k, r in per_tensor.items()
        ],
        key=lambda x: x["rel_change"],
    )
    low_rel = [x for x in dead_relative if x["rel_change"] < 1e-3]

    global_stats = {
        "num_tensors": agg["tensor_count"],
        "num_params": total,
        "mean_abs_delta": mean_abs,
        "std_abs_delta": var_abs**0.5,
        "max_abs_delta": agg["max_abs"],
        "median_abs_delta_sampled": sampled_median,
        "median_note": (
            "global median estimated from a deterministic strided sample "
            f"({sample_cat.numel():,} values across all tensors); per-tensor "
            "medians are exact"
        ),
        "relative_change_l2_vs_a": (
            (agg["l2_delta_sq"] / agg["l2_w_a_sq"]) ** 0.5
            if agg["l2_w_a_sq"] > 0
            else None
        ),
        "l2_delta": agg["l2_delta_sq"] ** 0.5,
        "l2_weights_a": agg["l2_w_a_sq"] ** 0.5,
        "frac_tensors_changed_delta_max_gt0": (
            agg["tensors_changed"] / agg["tensor_count"] if agg["tensor_count"] else 0.0
        ),
        "frac_params_changed_nz": agg["nz"] / total if total else 0.0,
        "frac_gt_eps_x_std": {
            f"{eps:g}": agg["frac_gt"][eps] / total if total else 0.0
            for eps in agg["frac_gt"]
        },
        "nan_total": agg["nan"],
        "inf_total": agg["inf"],
    }

    per_component = {}
    for comp, g in comp_acc.items():
        if g["numel"] == 0:
            continue
        m = g["sum_abs"] / g["numel"]
        v = max(0.0, g["sum_sq"] / g["numel"] - m**2)
        per_component[comp] = {
            "numel": g["numel"],
            "mean_abs_delta": m,
            "std_abs_delta": v**0.5,
            "max_abs_delta": g["max_abs"],
            "frac_params_changed_nz": g["nz"] / g["numel"],
            "relative_change_l2_vs_a": (
                (g["l2_delta_sq"] / g["l2_w_a_sq"]) ** 0.5
                if g["l2_w_a_sq"] > 0
                else None
            ),
        }
    per_layer = {}
    for layer in sorted(layer_acc):
        g = layer_acc[layer]
        m = g["sum_abs"] / g["numel"]
        v = max(0.0, g["sum_sq"] / g["numel"] - m**2)
        per_layer[str(layer)] = {
            "numel": g["numel"],
            "mean_abs_delta": m,
            "std_abs_delta": v**0.5,
            "max_abs_delta": g["max_abs"],
            "frac_params_changed_nz": g["nz"] / g["numel"],
            "relative_change_l2_vs_a": (
                (g["l2_delta_sq"] / g["l2_w_a_sq"]) ** 0.5
                if g["l2_w_a_sq"] > 0
                else None
            ),
        }

    return {
        "comparison": f"{label_a}_vs_{label_b}",
        "labels": {"earlier": label_a, "later": label_b},
        "key_set": {"missing_in_later": missing_b, "extra_in_later": extra_b},
        "global": global_stats,
        "per_component": per_component,
        "per_layer": per_layer,
        "per_tensor": per_tensor,
        "dead": {
            "completely_unchanged_delta_max_zero": dead,
            "changed_below_fp32_min_normal": below_eps,
            "low_relative_change_lt_1e-3": low_rel,
            "all_ranked_by_rel_change": dead_relative[:10],
        },
    }


# ---------------------------------------------------------------------------
# fresh-init reconstruction (--by-seed-42-init)
# ---------------------------------------------------------------------------

FRESH_INIT_MODEL = None  # held across phases when the flag is set


def build_fresh_init_model() -> object:
    """Instantiate the config with seed 42 exactly like the training harness
    (torch.manual_seed(seed) immediately before Qwen2ForCausalLM) and keep the
    model alive so its state_dict can be differenced against the latest
    checkpoint. Labeled a RECONSTRUCTION in every report."""
    from transformers import Qwen2Config, Qwen2ForCausalLM

    torch.manual_seed(42)
    model = Qwen2ForCausalLM(Qwen2Config(**MODEL_CFG_100M))
    n_params = sum(p.numel() for p in model.parameters())
    return model, n_params


# ---------------------------------------------------------------------------
# activation scan (inference-only, no backprop)
# ---------------------------------------------------------------------------


def activation_scan(
    export_dir: Path,
    tokenizer_dir: Path,
    corpus_path: Path,
    num_rows: int = 8,
    max_len: int = 512,
) -> dict:
    """Forward-pass activation stats through the LATEST model (HF export,
    byte-identical to checkpoint-1869 per model_identity.py, F1).

    Loads model.safetensors tensor-by-tensor via safetensors.safe_open (the
    file is mmap'd; only touched tensors enter RAM) and runs torch.no_grad()
    inference on the first `num_rows` real corpus rows. No backprop.
    """
    from safetensors import safe_open
    from transformers import PreTrainedTokenizerFast, Qwen2Config, Qwen2ForCausalLM

    cfg = Qwen2Config.from_pretrained(str(export_dir))
    model = Qwen2ForCausalLM(cfg)
    sf_path = export_dir / "model.safetensors"
    with safe_open(str(sf_path), framework="pt", device="cpu") as f:
        sd = model.state_dict()
        keys = list(f.keys())
        for k in keys:
            if k in sd:
                sd[k].copy_(f.get_tensor(k))
    del sd
    gc.collect()
    model.eval()

    tokenizer = PreTrainedTokenizerFast.from_pretrained(str(tokenizer_dir))
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.convert_ids_to_tokens(
            tokenizer.pad_token_id or 0
        )
    vocab = getattr(tokenizer, "vocab_size", None)
    if vocab != MODEL_CFG_100M["vocab_size"]:
        print(
            f"[S7][WARN] tokenizer vocab_size={vocab} != model vocab "
            f"{MODEL_CFG_100M['vocab_size']}",
            flush=True,
        )

    rows = []
    with open(corpus_path, "r", encoding="utf-8") as f:
        for _ in range(num_rows):
            line = f.readline()
            if not line.strip():
                break
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    texts = [r.get("text") or r.get("prompt") or str(r) for r in rows]
    enc = tokenizer(
        texts, truncation=True, max_length=max_len, padding=True, return_tensors="pt"
    )
    input_ids = enc["input_ids"]
    seq_lens = [int((x != 0).sum()) for x in input_ids]

    captures: dict[str, object] = {}

    def make_hook(name: str):
        def hook(_mod, _inp, out):
            captures[name] = out.detach()

        return hook

    handles = [
        model.model.embed_tokens.register_forward_hook(make_hook("embed_out")),
        model.model.layers[0].register_forward_hook(make_hook("layer0_out")),
        model.model.layers[10].register_forward_hook(make_hook("layer10_out")),
        model.model.norm.register_forward_hook(make_hook("final_norm_out")),
    ]
    with torch.no_grad():
        _out = model(input_ids=input_ids)
    for h in handles:
        h.remove()

    def act_stats(t: torch.Tensor) -> dict:
        f = t.float()
        n = int(f.numel())
        nan = int(torch.isnan(f).sum())
        return {
            "shape": list(t.shape),
            "numel": n,
            "mean": float(f.mean()) if n else 0.0,
            "std": float(f.std()) if n > 1 else 0.0,
            "max": float(f.max()) if n else 0.0,
            "min": float(f.min()) if n else 0.0,
            "nan_count": nan,
            "nan_fraction": nan / n if n else 0.0,
            "abs_mean": float(f.abs().mean()) if n else 0.0,
            "l2_norm": float((f.detach().pow(2).sum()).sqrt()) if n else 0.0,
        }

    result = {
        "label": (
            "INFERENCE-ONLY activation scan (torch.no_grad(), no backprop) on the "
            "HF export model.safetensors (byte-identical to checkpoint-1869 per "
            "model_identity.py F1) with the models/tokenizer_bpe tokenizer; "
            f"{len(texts)} real corpus rows from {corpus_path.name}"
        ),
        "inputs": {
            "n_rows": len(texts),
            "n_tokens_batch": int(input_ids.numel()),
            "seq_lengths": seq_lens,
            "max_len": max_len,
        },
        "vocab_size_tokenizer": vocab,
    }
    for name in ("embed_out", "layer0_out", "layer10_out", "final_norm_out"):
        if name in captures:
            result[name] = act_stats(captures[name])
    if "final_norm_out" in captures:
        h = captures["final_norm_out"].float()
        flat = h.reshape(-1, MODEL_CFG_100M["hidden_size"])
        token_norms = flat.norm(dim=1)
        result["last_hidden_state"] = {
            "fro_norm": float(h.pow(2).sum().sqrt()),
            "rms": float(h.pow(2).mean().sqrt()),
            "per_token_l2_mean": float(token_norms.mean()),
            "per_token_l2_std": float(token_norms.std()),
            "per_token_l2_max": float(token_norms.max()),
            "n_tokens": int(flat.shape[0]),
        }
    del model, enc, input_ids
    gc.collect()
    return result


# ---------------------------------------------------------------------------
# verdict
# ---------------------------------------------------------------------------


def decide_verdict(primary: dict, init_cmp: dict | None, starved: list[str]) -> dict:
    g = primary["global"]
    dead = primary["dead"]
    frac_params = g["frac_params_changed_nz"]
    rel = g["relative_change_l2_vs_a"]
    frac_tensors = g["frac_tensors_changed_delta_max_gt0"]
    n_dead = len(dead["completely_unchanged_delta_max_zero"])
    n_low_rel = len(dead["low_relative_change_lt_1e-3"])

    basis = {
        "frac_params_changed_nz": frac_params,
        "frac_tensors_changed": frac_tensors,
        "relative_change_l2": rel,
        "mean_abs_delta": g["mean_abs_delta"],
        "max_abs_delta": g["max_abs_delta"],
        "completely_unchanged_tensors": n_dead,
        "low_relative_change_tensors_lt_1e-3": n_low_rel,
        "optimizer_starved_tensors": len(starved),
        "nan_total": g["nan_total"],
        "inf_total": g["inf_total"],
    }
    if init_cmp is not None:
        ig = init_cmp["global"]
        basis["init_cmp"] = {
            "frac_params_changed_nz_vs_init": ig["frac_params_changed_nz"],
            "relative_change_l2_vs_init": ig["relative_change_l2_vs_a"],
            "mean_abs_delta_vs_init": ig["mean_abs_delta"],
            "max_abs_delta_vs_init": ig["max_abs_delta"],
        }
    verdict_rules = (
        f"LEARNING CONFIRMED if frac_params_changed >= 0.999 AND relative_change_l2 "
        f">= 1e-3 AND no completely-unchanged tensor; NO-EVIDENCE if "
        f"frac_params_changed < 0.5 AND relative_change_l2 < 1e-5; else PARTIAL."
    )
    confirmed = (
        frac_params >= 0.999 and (rel is not None and rel >= 1e-3) and n_dead == 0
    )
    none_ev = frac_params < 0.5 and (rel is None or rel < 1e-5)
    label = (
        "LEARNING CONFIRMED" if confirmed else ("NO-EVIDENCE" if none_ev else "PARTIAL")
    )
    return {
        "label": label,
        "rules": verdict_rules,
        "basis": basis,
    }


# ---------------------------------------------------------------------------
# ledger / learning-curve helpers
# ---------------------------------------------------------------------------


def read_ledger(ledger_path: Path) -> list[dict]:
    if not ledger_path.exists():
        return []
    rows = []
    with open(ledger_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def comp001_ledger_rows(ledger_path: Path) -> list[dict]:
    return [
        r
        for r in read_ledger(ledger_path)
        if r.get("experiment") == "comp-001-custom-100m-real"
    ]


def metadata_pass(ckpt_dirs: list[Path], tracker: Tracker) -> dict:
    """Load each checkpoint with mmap (metadata only; tensors never touched),
    collect step/config/hparams/losses/optimizer-presence per checkpoint dir."""
    meta: dict[str, dict] = {}
    for d in ckpt_dirs:
        pt = d / "checkpoint.pt"
        js = d / "checkpoint.json"
        entry: dict = {
            "dir": str(d),
            "size_bytes": pt.stat().st_size if pt.exists() else None,
        }
        if js.exists():
            entry["json"] = json.loads(js.read_text(encoding="utf-8"))
        if pt.exists():
            try:
                obj = load_ckpt(pt)
                entry["pt"] = {
                    "step": obj.get("step"),
                    "timestamp": obj.get("timestamp"),
                    "config": obj.get("config"),
                    "hparams": obj.get("hparams"),
                    "losses_len": len(obj.get("losses", [])),
                    "losses": obj.get("losses", []),
                    "has_optimizer": isinstance(obj.get("optimizer"), dict),
                    "model_tensor_count": len(obj.get("model", {})),
                }
                tracker.log(
                    "S2",
                    f"{d.name}: step={entry['pt']['step']} "
                    f"losses={entry['pt']['losses_len']} opt={entry['pt']['has_optimizer']}",
                )
                free(obj)
            except Exception as e:
                entry["pt"] = {"load_error": f"{type(e).__name__}: {e}"}
                print(f"[S2][WARN] {d.name} metadata load failed: {e}", flush=True)
        meta[d.name] = entry
    return meta


def build_learning_curve(meta: dict, ledger_rows: list[dict]) -> tuple[dict, str]:
    """Union of exact per-step train losses from checkpoint.pt `losses` lists;
    eval losses from ledger rows at each run's final step. Steps without a
    value are left blank (never invented)."""
    steps: dict[int, dict] = {}
    for name, e in meta.items():
        pt = e.get("pt") or {}
        losses = pt.get("losses") or []
        step = pt.get("step")
        if not step or not losses:
            continue
        start = int(step) - len(losses)
        for i, loss in enumerate(losses):
            s = start + i + 1
            steps.setdefault(s, {})["train_loss"] = loss
            steps[s]["source_ckpt"] = name
    if not steps:
        # ledger fallback: loss_history per run aligned by resume_from_step
        for row in ledger_rows:
            lh = row.get("loss_history") or []
            start = int(row.get("resume_from_step") or 0)
            for i, loss in enumerate(lh):
                s = start + i + 1
                steps.setdefault(s, {})["train_loss"] = loss
                steps[s]["source"] = "ledger"
    run_evals: dict[int, float] = {}
    for row in ledger_rows:
        lh = row.get("loss_history") or []
        if not lh:
            continue
        end_step = int(row.get("resume_from_step") or 0) + len(lh)
        if row.get("eval_loss") is not None:
            run_evals[end_step] = float(row["eval_loss"])
    for s, ev in run_evals.items():
        steps.setdefault(s, {})["eval_loss"] = ev

    header = "step,train_loss,eval_loss"
    lines = [header]
    for s in sorted(steps):
        tr = steps[s].get("train_loss", "")
        ev = steps[s].get("eval_loss", "")
        tr_s = f"{tr:.6f}" if isinstance(tr, float) else ""
        ev_s = f"{ev:.6f}" if isinstance(ev, float) else ""
        lines.append(f"{s},{tr_s},{ev_s}")
    return {
        "steps": {str(s): steps[s] for s in sorted(steps)},
        "n_steps": len(steps),
        "n_train_values": sum(1 for s in steps if "train_loss" in steps[s]),
        "n_eval_values": sum(1 for s in steps if "eval_loss" in steps[s]),
        "source_note": (
            "train_loss from checkpoint.pt `losses` (exact); eval_loss from "
            "ledger rows at each run's final step; blank = no value recorded"
        ),
    }, "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# single-checkpoint passes (one checkpoint at a time)
# ---------------------------------------------------------------------------


def checkpoint_tensor_pass(obj: dict, label: str, tracker: Tracker) -> dict:
    """Per-tensor weight stats + hashes + nan/zero scans for ONE checkpoint."""
    sd = obj.get("model")
    if not isinstance(sd, dict):
        raise RuntimeError(f"{label}: checkpoint has no 'model' state dict")
    records: dict[str, dict] = {}
    totals = {"numel": 0, "nan": 0, "inf": 0, "zeros": 0, "tensor_count": 0}
    for key in sorted(sd.keys()):
        t = sd[key]
        n = int(t.numel())
        st = single_tensor_stats(t)
        rows = row_zero_counts(t)
        h = per_tensor_sha256(key, t)
        records[key] = {
            "shape": list(t.shape),
            "dtype": str(t.dtype),
            "numel": n,
            "sha256": h,
            "stats": st,
            "row_zero_counts": rows,
        }
        totals["numel"] += n
        totals["nan"] += st["nan"]
        totals["inf"] += st["inf"]
        totals["zeros"] += st["zeros"]
        totals["tensor_count"] += 1
    tracker.log(
        f"SINGLE:{label}",
        f"{totals['tensor_count']} tensors, {totals['numel']:,} params, "
        f"nan={totals['nan']} inf={totals['inf']} zeros={totals['zeros']}",
    )
    return {
        "label": label,
        "totals": totals,
        "nan_inf_scan": {
            "tensors_with_nan": sorted(
                k for k, r in records.items() if r["stats"]["nan"] > 0
            ),
            "tensors_with_inf": sorted(
                k for k, r in records.items() if r["stats"]["inf"] > 0
            ),
            "total_nan": totals["nan"],
            "total_inf": totals["inf"],
            "total_zeros": totals["zeros"],
            "zero_fraction": totals["zeros"] / totals["numel"]
            if totals["numel"]
            else 0.0,
        },
        "embedding": {
            "embed_key": "model.embed_tokens.weight",
            "all_zero_rows_in_weights": records["model.embed_tokens.weight"][
                "row_zero_counts"
            ],
            "lm_head": records["lm_head.weight"]["row_zero_counts"],
        },
        "per_tensor": records,
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--earliest", required=True, help="path to earliest checkpoint.pt")
    ap.add_argument("--latest", required=True, help="path to latest checkpoint.pt")
    ap.add_argument(
        "--by-seed-42-init",
        action="store_true",
        help="also reconstruct the seed-42 init from config and compare latest-vs-init "
        "(theoretical init; earliest-vs-latest remains the empirical baseline)",
    )
    ap.add_argument(
        "--num-rows", type=int, default=8, help="corpus rows for activation scan"
    )
    ap.add_argument(
        "--export", default=str(REPO_ROOT / "models" / "comp001" / "100m-real")
    )
    ap.add_argument("--tokenizer", default=str(REPO_ROOT / "models" / "tokenizer_bpe"))
    ap.add_argument(
        "--corpus",
        default=str(
            REPO_ROOT / "data" / "training" / "corpus" / "train-fw-part-00000.jsonl"
        ),
    )
    ap.add_argument("--ledger", default=str(REPO_ROOT / "logs" / "training_runs.jsonl"))
    ap.add_argument(
        "--identity", default=str(REPO_ROOT / "logs" / "forensic" / "identity.json")
    )
    ap.add_argument("--threads", type=int, default=2)
    args = ap.parse_args()

    torch.set_num_threads(args.threads)
    tracker = Tracker()
    failures: list[str] = []
    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": sys.argv,
        "script": "scripts/forensic/learning_proof.py",
        "status": "OK",
    }

    earliest_path = Path(args.earliest)
    latest_path = Path(args.latest)
    export_dir = Path(args.export)
    tokenizer_dir = Path(args.tokenizer)
    corpus_path = Path(args.corpus)
    ledger_path = Path(args.ledger)
    identity_path = Path(args.identity)
    ckpt_root = latest_path.parents[1]
    out_dir = REPO_ROOT / "logs" / "forensic"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "learning.json"
    raw_path = out_dir / "learning_raw.txt"
    csv_path = out_dir / "learning_curve.csv"

    for name, p in (
        ("earliest", earliest_path),
        ("latest", latest_path),
        ("export model.safetensors", export_dir / "model.safetensors"),
        ("tokenizer", tokenizer_dir),
        ("corpus", corpus_path),
    ):
        if not Path(p).exists():
            print(f"[FATAL] missing input: {name} = {p}", flush=True)
            return 1

    import platform

    report["environment"] = {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "platform": platform.platform(),
    }
    disk_before = shutil.disk_usage(REPO_ROOT).free
    report["disk_free_before_bytes"] = disk_before
    report["files"] = {
        "earliest": {
            "path": str(earliest_path),
            "size_mib": round(earliest_path.stat().st_size / 2**20, 1),
        },
        "latest": {
            "path": str(latest_path),
            "size_mib": round(latest_path.stat().st_size / 2**20, 1),
        },
    }

    try:
        # ---- S1: streaming file hashes -----------------------------------
        tracker.log("S1", "sha256 earliest checkpoint.pt (streaming)")
        t0 = time.perf_counter()
        report["files"]["earliest"]["sha256"] = sha256_file(earliest_path)
        tracker.log(
            "S1",
            f"earliest sha256={report['files']['earliest']['sha256'][:16]}... ({time.perf_counter() - t0:.1f}s)",
        )
        t0 = time.perf_counter()
        report["files"]["latest"]["sha256"] = sha256_file(latest_path)
        tracker.log(
            "S1",
            f"latest sha256={report['files']['latest']['sha256'][:16]}... ({time.perf_counter() - t0:.1f}s)",
        )
        if identity_path.exists():
            try:
                idj = json.loads(identity_path.read_text(encoding="utf-8"))
                report["files"]["latest"]["F1_identity_filename_sha256"] = (
                    idj.get("files", {}).get("checkpoint", {}).get("sha256")
                )
            except Exception:
                pass

        # ---- S2: metadata + learning curve --------------------------------
        all_dirs = sorted(
            (p for p in ckpt_root.glob("checkpoint-*") if p.is_dir()),
            key=lambda p: int(p.name.split("-")[1]),
        )
        ledgers = comp001_ledger_rows(ledger_path)
        meta = metadata_pass(all_dirs, tracker)
        curve, curve_csv = build_learning_curve(meta, ledgers)
        report["checkpoint_meta"] = {
            step_name: {
                "step": e.get("pt", {}).get("step"),
                "losses_len": e.get("pt", {}).get("losses_len"),
                "timestamp": e.get("pt", {}).get("timestamp"),
                "has_optimizer": e.get("pt", {}).get("has_optimizer"),
                "model_tensor_count": e.get("pt", {}).get("model_tensor_count"),
                "config_matches_100m_cfg": (
                    (e.get("pt", {}).get("config") or {}).get("vocab_size")
                    == MODEL_CFG_100M["vocab_size"]
                ),
                "pt_load_error": e.get("pt", {}).get("load_error"),
            }
            for step_name, e in sorted(
                meta.items(),
                key=lambda kv: int(kv[0].split("-")[1]),
            )
        }
        report["learning_curve"] = curve
        csv_path.write_text(curve_csv, encoding="utf-8")
        tracker.log(
            "S2",
            f"learning curve: {curve['n_steps']} steps, "
            f"train={curve['n_train_values']} eval={curve['n_eval_values']}",
        )

        # ---- S3: earliest single-checkpoint pass --------------------------
        tracker.log("S3", f"loading earliest {earliest_path.name} (mmap)")
        tracker.warn_avail()
        obj_e = load_ckpt(earliest_path)
        report["checkpoint_meta"]["earliest_loaded"] = {
            "step": obj_e.get("step"),
            "losses_len": len(obj_e.get("losses", [])),
            "config": obj_e.get("config"),
            "hparams": obj_e.get("hparams"),
        }
        spec_e = checkpoint_tensor_pass(obj_e, "checkpoint-200", tracker)
        free(obj_e)
        tracker.log("S3", "earliest pass done; obj freed + gc")

        # ---- S4: latest single-checkpoint pass + optimizer ----------------
        tracker.log("S4", f"loading latest {latest_path.name} (mmap)")
        tracker.warn_avail()
        obj_l = load_ckpt(latest_path)
        report["checkpoint_meta"]["latest_loaded"] = {
            "step": obj_l.get("step"),
            "losses_len": len(obj_l.get("losses", [])),
            "config": obj_l.get("config"),
            "hparams": obj_l.get("hparams"),
        }
        spec_l = checkpoint_tensor_pass(obj_l, "checkpoint-1869", tracker)

        names = optimizer_param_names()
        key_set = set(obj_l.get("model", {}).keys())
        validate_optimizer_names(names, key_set)
        opt = obj_l.get("optimizer")
        if isinstance(opt, dict):
            opt_analysis = analyze_optimizer_state(opt, names)
            tracker.log(
                "S4",
                f"optimizer PROXY: {opt_analysis['param_count']} entries, "
                f"starved={len(opt_analysis['starved_tensors'])} step "
                f"{opt_analysis['step_min']}->{opt_analysis['step_max']}",
            )
        else:
            opt_analysis = {"label": "optimizer state ABSENT in latest checkpoint"}
            failures.append("latest checkpoint has no optimizer state dict")
        free(obj_l)
        tracker.log("S4", "latest pass done; obj freed + gc")

        # ---- S5: delta pass (both checkpoints mmap'd, per-tensor streaming)
        tracker.log("S5", "delta pass: loading earliest + latest (both mmap)")
        tracker.warn_avail()
        obj_e = load_ckpt(earliest_path)
        obj_l = load_ckpt(latest_path)
        sd_e = obj_e["model"]
        sd_l = obj_l["model"]
        cmp_e_l = compare_state_dicts(
            sd_e,
            sd_l,
            f"checkpoint-{obj_e.get('step', 200)}",
            f"checkpoint-{obj_l.get('step', 1869)}",
        )
        cmp_e_l["spans"] = {
            "earliest_step": obj_e.get("step"),
            "latest_step": obj_l.get("step"),
            "steps_between": (obj_l.get("step") or 0) - (obj_e.get("step") or 0),
        }
        # dead embedding rows in the DELTA itself
        de = sd_l["model.embed_tokens.weight"] - sd_e["model.embed_tokens.weight"]
        cmp_e_l["embedding_delta"] = row_zero_counts(de)
        del de
        free(obj_e)
        free(obj_l)
        g = cmp_e_l["global"]
        tracker.log(
            "S5",
            f"earliest-vs-latest delta: frac_params_nz={g['frac_params_changed_nz']:.6f} "
            f"rel_l2={g['relative_change_l2_vs_a']:.6g} max_abs={g['max_abs_delta']:.6g} "
            f"dead_tensors={len(cmp_e_l['dead']['completely_unchanged_delta_max_zero'])}",
        )

        # ---- S6: optional fresh-init reconstruction -----------------------
        init_cmp = None
        if args.by_seed_42_init:
            tracker.log(
                "S6", "building seed-42 init from config (theoretical reconstruction)"
            )
            tracker.warn_avail()
            fresh_model, n_params = build_fresh_init_model()
            init_names = [n for n, _ in fresh_model.named_parameters()]
            validate_optimizer_names(init_names, key_set)
            report["fresh_init"] = {
                "label": (
                    "RECONSTRUCTION: config instantiated with seed 42 (the training "
                    "seed), built exactly like build_model() in train_comp001.py "
                    "(torch.manual_seed(42) immediately before Qwen2ForCausalLM). "
                    "No step-0 checkpoint exists on disk; this is a same-seed "
                    "reconstruction, not an empirical artifact."
                ),
                "n_params": n_params,
                "param_order_matches_optimizer_state": init_names == names,
            }
            tracker.log("S6", f"init built: {n_params:,} params; comparing vs latest")
            obj_l = load_ckpt(latest_path)
            fresh_sd = fresh_model.state_dict()
            cmp_init_l = compare_state_dicts(
                fresh_sd,
                obj_l["model"],
                "fresh_init_seed42",
                "checkpoint-1869",
            )
            cmp_init_l["spans"] = {
                "earliest_step": 0,
                "latest_step": obj_l.get("step"),
                "steps_between": obj_l.get("step") or 0,
                "empirical": False,
                "note": "theoretical init reconstruction, not an empirical checkpoint",
            }
            init_cmp = cmp_init_l
            free(obj_l)
            free(fresh_model)
            tracker.log(
                "S6",
                f"fresh-init-vs-latest: frac_params_nz={cmp_init_l['global']['frac_params_changed_nz']:.6f} "
                f"rel_l2={cmp_init_l['global']['relative_change_l2_vs_a']:.6g}",
            )

        # ---- S7: activation scan on export (no backprop) ------------------
        tracker.log("S7", "activation scan on HF export (inference-only)")
        tracker.warn_avail()
        try:
            act = activation_scan(
                export_dir, tokenizer_dir, corpus_path, num_rows=args.num_rows
            )
            tracker.log(
                "S7",
                f"activation scan ok: layer0_nan={act.get('layer0_out', {}).get('nan_count')} "
                f"final_norm_nan={act.get('final_norm_out', {}).get('nan_count')}",
            )
        except Exception as e:
            act = {
                "label": "activation scan FAILED",
                "error": f"{type(e).__name__}: {e}",
            }
            failures.append(f"activation scan failed: {type(e).__name__}: {e}")
            tracker.log("S7", f"FAILED: {e}")

        # ---- S8: assemble + verdict + outputs -----------------------------
        opt_starved = opt_analysis.get("starved_tensors", [])
        verdict = decide_verdict(cmp_e_l, init_cmp, opt_starved)

        report["weight_deltas"] = {
            "earliest_vs_latest": cmp_e_l,
            "fresh_init_vs_latest": init_cmp,
        }
        report["single_tensor_stats"] = {
            "checkpoint-200": spec_e,
            "checkpoint-1869": spec_l,
        }
        report["optimizer_state"] = opt_analysis
        report["activation_scan"] = act
        report["verdict"] = verdict
        report["ledger"] = {
            "path": str(ledger_path),
            "comp001_runs": [
                {
                    "run_id": r.get("run_id"),
                    "status": r.get("status"),
                    "resumed": r.get("resumed"),
                    "resume_from_step": r.get("resume_from_step"),
                    "loss_history_len": len(r.get("loss_history") or []),
                    "starting_loss": r.get("starting_loss"),
                    "ending_loss": r.get("ending_loss"),
                    "eval_loss": r.get("eval_loss"),
                    "tokens_seen": r.get("tokens_seen"),
                    "param_count": r.get("param_count"),
                }
                for r in ledgers
            ],
            "output_differs_claim": [
                {"run_id": r.get("run_id"), "output_differs": r.get("output_differs")}
                for r in ledgers
            ],
        }
        report["hashes"] = {
            "checkpoint_files": {
                "earliest": report["files"]["earliest"].get("sha256"),
                "latest": report["files"]["latest"].get("sha256"),
            },
            "per_tensor": {
                "checkpoint-200": {
                    k: v["sha256"] for k, v in spec_e["per_tensor"].items()
                },
                "checkpoint-1869": {
                    k: v["sha256"] for k, v in spec_l["per_tensor"].items()
                },
            },
        }

        disk_after = shutil.disk_usage(REPO_ROOT).free
        report["disk_free_after_bytes"] = disk_after
        report["memory"] = {
            "peak_rss_mb": round(tracker.peak, 1),
            "phases": tracker.stages,
        }
        report["failures"] = failures
        if failures:
            report["status"] = "OK_WITH_FAILURES"

        # ---- write outputs -------------------------------------------------
        _write_outputs(report, json_path, raw_path, csv_path)
        tracker.log(
            "S8",
            f"outputs written; peak_rss={report['memory']['peak_rss_mb']}MB "
            f"new_bytes={report['artifacts']['total_bytes']}",
        )
        _print_summary(report)
        return 0 if report["status"] == "OK" else 1

    except Exception as e:
        failures.append(f"{type(e).__name__}: {e}\n{traceback.format_exc()[-500:]}")
        report["failures"] = failures
        report["status"] = "FAILED"
        report["memory"] = {
            "peak_rss_mb": round(rss_peak_mb(), 1),
            "stages": tracker.stages,
        }
        try:
            json_path.write_text(
                json.dumps(report, indent=2, sort_keys=True, default=str),
                encoding="utf-8",
            )
        except Exception as e2:
            print(f"[FATAL] could not write outputs: {e2}", flush=True)
        _print_summary(report)
        return 1


# ---------------------------------------------------------------------------
# outputs
# ---------------------------------------------------------------------------


def _fmt(x, digits=6) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:.{digits}g}"
    return str(x)


def _write_outputs(
    report: dict, json_path: Path, raw_path: Path, csv_path: Path
) -> None:
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )

    wd = report["weight_deltas"]["earliest_vs_latest"]
    g = wd["global"]
    lines = [
        "# learning_proof.py - per-tensor weight-delta forensic listing",
        f"# generated: {report.get('generated_at')}",
        f"# comparison: {wd['comparison']} "
        f"(steps {wd['spans']['earliest_step']} -> {wd['spans']['latest_step']})",
        f"# scheme: SHA16 = first 16 hex of sha256(key|dtype|shape|raw_bytes); "
        f"RELCHG = ||delta||_F / ||earliest_weights||_F; eps thresholds are "
        f"relative to the EARLIEST tensor std",
        f"# global: mean_abs={_fmt(g['mean_abs_delta'])} std_abs={_fmt(g['std_abs_delta'])} "
        f"max_abs={_fmt(g['max_abs_delta'])} frac_tensors_changed="
        f"{_fmt(g['frac_tensors_changed_delta_max_gt0'])} frac_params_nz="
        f"{_fmt(g['frac_params_changed_nz'])} rel_l2={_fmt(g['relative_change_l2_vs_a'])}",
        "",
        "# DELTA rows: KEY SHAPE NUMEL ABSMEAN ABSMED ABSSTD ABSMAX FRAC_NZ "
        "FRAC_GT_1E-6STD FRAC_GT_1E-4STD FRAC_GT_1E-3STD FRAC_GT_1E-2STD "
        "RELCHG L2_DELTA L2_W_EARLY NAN INF SHA16_EARLY SHA16_LATE",
        "DELTA\tKEY\tSHAPE\tNUMEL\tABSMEAN\tABSMED\tABSSTD\tABSMAX\tFRAC_NZ\t"
        "GT1E-6STD\tGT1E-4STD\tGT1E-3STD\tGT1E-2STD\tRELCHG\tL2_DELTA\t"
        "L2_W_EARLY\tNAN\tINF\tSHA16_EARLY\tSHA16_LATE",
    ]
    spec_e = report["single_tensor_stats"]["checkpoint-200"]["per_tensor"]
    spec_l = report["single_tensor_stats"]["checkpoint-1869"]["per_tensor"]
    for k in sorted(wd["per_tensor"]):
        r = wd["per_tensor"][k]
        d = r["delta"]
        lines.append(
            f"DELTA\t{k}\t{json.dumps(r['shape'], separators=(',', ':'))}\t{r['numel']}\t"
            f"{_fmt(d['abs_mean'])}\t{_fmt(d['abs_median'])}\t{_fmt(d['abs_std'])}\t"
            f"{_fmt(d['abs_max'])}\t{_fmt(d['frac_nonzero'])}\t"
            f"{_fmt(d[f'gt_{1e-6:g}_x_std'])}\t{_fmt(d[f'gt_{1e-4:g}_x_std'])}\t"
            f"{_fmt(d[f'gt_{1e-3:g}_x_std'])}\t{_fmt(d[f'gt_{1e-2:g}_x_std'])}\t"
            f"{_fmt(r['rel_change_vs_a'])}\t{_fmt(d['l2_norm'])}\t"
            f"{_fmt(r['weights_a_l2'])}\t{d['nan']}\t{d['inf']}\t"
            f"{spec_e[k]['sha256'][:16]}\t{spec_l[k]['sha256'][:16]}"
        )
    lines += [
        "",
        "# OPTIMIZER PROXY rows (checkpoint-1869 AdamW state, no raw gradients):",
        "OPT\tKEY\tCOMPONENT\tEXP_AVG_ABS_MEAN\tEXP_AVG_SQ_ABS_MEAN\t"
        "EFF_UPDATE_MEAN\tEFF_UPDATE_MAX\tEXP_AVG_ZERO_FRAC\tSTEP\tSTARVED",
    ]
    for k in sorted(report["optimizer_state"].get("per_tensor", {})):
        o = report["optimizer_state"]["per_tensor"][k]
        starved = (
            "STARVED"
            if k in report["optimizer_state"].get("starved_tensors", [])
            else ""
        )
        lines.append(
            f"OPT\t{k}\t{o['component']}\t{_fmt(o['exp_avg_abs_mean'])}\t"
            f"{_fmt(o['exp_avg_sq_abs_mean'])}\t{_fmt(o['eff_update_mean'])}\t"
            f"{_fmt(o['eff_update_max'])}\t{_fmt(o['exp_avg_zero_fraction'])}\t"
            f"{_fmt(o['step'])}\t{starved}"
        )
    dead = wd["dead"]
    lines += [
        "",
        "# DEAD/LOW-CHANGE findings:",
        f"# completely unchanged (delta-max == 0): "
        f"{dead['completely_unchanged_delta_max_zero'] or 'NONE'}",
        f"# low relative change < 1e-3: "
        f"{[x['tensor'] for x in dead['low_relative_change_lt_1e-3']] or 'NONE'}",
        "",
        "# FILE hashes:",
        f"FILE\tearliest\t{report['files']['earliest'].get('sha256')}",
        f"FILE\tlatest\t{report['files']['latest'].get('sha256')}",
        "",
        f"# verdict: {report['verdict']['label']}",
    ]
    raw_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    total = json_path.stat().st_size + raw_path.stat().st_size + csv_path.stat().st_size
    report["artifacts"] = {
        "learning_json": str(json_path),
        "learning_json_bytes": json_path.stat().st_size,
        "learning_raw_txt": str(raw_path),
        "learning_raw_txt_bytes": raw_path.stat().st_size,
        "learning_curve_csv": str(csv_path),
        "learning_curve_csv_bytes": csv_path.stat().st_size,
        "total_bytes": total,
    }
    report["new_bytes_written"] = total
    # rewrite with artifacts + verdict final
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )


def _print_summary(report: dict) -> None:
    print(f"\n{'=' * 66}\n[SUMMARY] status={report.get('status')}", flush=True)
    v = report.get("verdict", {})
    print(f"  verdict: {v.get('label')}", flush=True)
    wd = (report.get("weight_deltas") or {}).get("earliest_vs_latest")
    if wd:
        g = wd["global"]
        print(
            f"  delta mean/median(sampled)/std/max abs = "
            f"{g['mean_abs_delta']:.6g} / {g['median_abs_delta_sampled']:.6g} / "
            f"{g['std_abs_delta']:.6g} / {g['max_abs_delta']:.6g}",
            flush=True,
        )
        print(
            f"  frac_tensors_changed={g['frac_tensors_changed_delta_max_gt0']:.6f} "
            f"frac_params_changed_nz={g['frac_params_changed_nz']:.6f} "
            f"rel_l2={g['relative_change_l2_vs_a']:.6g}",
            flush=True,
        )
        dead = wd["dead"]
        print(
            f"  dead (delta-max==0): {dead['completely_unchanged_delta_max_zero'] or 'none'}",
            flush=True,
        )
        print(
            f"  low rel-change<1e-3: {[x['tensor'] for x in dead['low_relative_change_lt_1e-3']] or 'none'}",
            flush=True,
        )
        print(
            f"  delta nan={g['nan_total']} inf={g['inf_total']}",
            flush=True,
        )
    st = report.get("single_tensor_stats") or {}
    for label in ("checkpoint-200", "checkpoint-1869"):
        s = st.get(label)
        if s:
            nis = s["nan_inf_scan"]
            print(
                f"  {label} NaN scan: nan={nis['total_nan']} inf={nis['total_inf']} "
                f"zero_frac={nis['zero_fraction']:.4f}",
                flush=True,
            )
    opt = report.get("optimizer_state") or {}
    if opt.get("param_count"):
        print(
            f"  optimizer PROXY: global |eff_update| mean={opt['global']['eff_update_abs_mean']:.6g} "
            f"starved={len(opt.get('starved_tensors', []))} "
            f"nan_tensors={opt['nan_inf_tensors']['nan'] or 'none'}",
            flush=True,
        )
    act = report.get("activation_scan") or {}
    if "layer0_out" in act:
        print(
            f"  activation scan: layer0 mean={act['layer0_out']['mean']:.4f} "
            f"nan={act['layer0_out']['nan_count']} | last_layer "
            f"mean={act.get('layer10_out', {}).get('mean', float('nan')):.4f} "
            f"nan={act.get('layer10_out', {}).get('nan_count')} | "
            f"last_hidden rms={act.get('last_hidden_state', {}).get('rms', float('nan')):.4f}",
            flush=True,
        )
    else:
        print(f"  activation scan: {act.get('error', 'not run')}", flush=True)
    mem = report.get("memory", {})
    print(f"  peak_rss={mem.get('peak_rss_mb')} MB", flush=True)
    art = report.get("artifacts", {})
    print(
        f"  new_bytes_written={report.get('new_bytes_written')} "
        f"(json+raw+csv: {art.get('learning_json_bytes', '?')}+"
        f"{art.get('learning_raw_txt_bytes', '?')}+{art.get('learning_curve_csv_bytes', '?')})",
        flush=True,
    )
    print(f"  failures={report.get('failures')}", flush=True)
    print("=" * 66, flush=True)


if __name__ == "__main__":
    sys.exit(main())
