"""ORION Runner - airllm bridge (honest low-memory loader + OPT-IN teacher).

What airllm actually does: it splits a checkpoint into per-layer shards on disk,
builds the transformers model on the `meta` device (zero RAM), then streams each
layer disk -> device right before that layer runs and evicts it right after. RAM
stays flat; DISK does not have to.

Honest constraint note for THIS laptop (no GPU, CPU-only torch):

* CPU layer-wise inference is disk-I/O bound. Every token re-reads the shard
  stream, so it is far slower than Ollama, which keeps one model resident in
  RAM and streams nothing. Use airllm here as a fallback, not as an upgrade.
  Measured on this box: Qwen2.5-0.5B-Instruct, 16 new tokens = 121 s, at a flat
  ~390 MB RSS. RAM-frugal, yes; 7.5 s/token, no.
* The binding constraint is free disk, not RAM. Measured at ~8.5 GB free on the
  repo drive (D:), so anything above a ~6 GB checkpoint does NOT fit once a
  safety margin is held back. Qwen2.5-3B (~6.2 GB) is therefore already
  marginal/blocked, and 7B is BLOCKED - Qwen2.5-7B-Instruct alone is 14.19 GB
  of weights per Hub metadata, and 15.2 GB is the conservative figure used by
  the self-check.
* Disk cost is paid twice: the downloaded checkpoint AND the split layer shards
  (airllm links shards it can, but only for already one-per-shard indexes;
  single-file checkpoints such as Qwen2.5-0.5B-Instruct get copied). So the gate
  below asks for the whole checkpoint size, not a token buffer. Measured: the
  0.5B split cost 942 MB of shards.
* On this box the HF cache (~/.cache/huggingface/hub) is a junction onto the SAME
  volume as the repo (D:), so the cache and ORION share one disk budget. That is
  why disk_gate() measures the path the shards will actually land on instead of
  assuming the repo drive.

This mirrors airllm's own gate: `airllm.utils.check_space` (utils.py ~447-468)
raises `NotEnoughSpaceException` when free < total shard bytes, i.e. it checks
*after* you already paid the download. `disk_gate()` here checks *before*, so a
refusal never starts a download.

Nothing here is wired into the default pipeline. The teacher contract in
scripts/teacher/generate_curriculum.py and scripts/training/orion_dataset.py
still resolves to the local Ollama qwen2.5:3b path; `teacher_answer()` below is
an OPT-IN alternative backend and those files are deliberately left alone.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional, Tuple, Union

# Repo root is the drive the disk budget above refers to; used as the default
# measurement root for disk_gate() when the caller does not name one.
DISK_GATE_ROOT = Path(__file__).resolve().parents[1]

# Free disk we refuse to spend on shards, so the OS / pagefile / ORION itself
# keep room to breathe.
DEFAULT_MARGIN_GB = 1.5

# Weight files that actually make up a checkpoint (config/tokenizer are noise).
_WEIGHT_SUFFIXES = (".safetensors", ".bin", ".pt", ".pth")

# airllm writes its split layer shards under this name; they are a *copy* of the
# checkpoint, so they must never be counted as checkpoint size (that would make
# the gate inflate on every re-run).
_SHARD_DIR = "splitted_model"

_AIRLLM = None  # lazy import guard
_TORCH = None


def _weight_bytes(path: Union[str, Path]) -> int:
    """Total weight bytes of a local checkpoint, excluding airllm's shard copy.

    Returns 0 for a snapshot whose weight files are unreadable - which is the
    real state of a cache whose absolute symlinks point at a moved/deleted
    cache root. Treating that as 0 (rather than raising) is what lets the gate
    fall back to Hub metadata and let snapshot_download() repair the links.
    """
    root = Path(path)
    total = 0
    for f in root.rglob("*"):
        if f.suffix not in _WEIGHT_SUFFIXES:
            continue
        if _SHARD_DIR in f.relative_to(root).parts:
            continue
        try:
            total += f.stat().st_size
        except OSError:  # dangling symlink / unreadable blob
            continue
    return total


def _import_airllm():
    """Import airllm on first use. Raises RuntimeError (not ImportError) so a
    missing backend reads as a setup problem, not a bug in the caller."""
    global _AIRLLM
    if _AIRLLM is not None:
        return _AIRLLM
    try:
        import airllm  # lazy: keep this module importable without airllm
    except ImportError as e:  # pragma: no cover - exercised by absence sim
        raise RuntimeError(
            "airllm is not importable, so orion_runner.airllm_bridge cannot run. "
            "Install it with `pip install airllm` (needs torch + transformers). "
            "Note the honest tradeoff: airllm saves RAM, not time - on this "
            "CPU-only laptop the default teacher stays Ollama (qwen2.5:3b) and "
            "this module is opt-in. Original import error: " + str(e)
        ) from e
    _AIRLLM = airllm
    return _AIRLLM


def _import_torch():
    global _TORCH
    if _TORCH is None:
        import torch  # lazy

        _TORCH = torch
    return _TORCH


def checkpoint_size_gb(model_dir: Union[str, Path]) -> Optional[float]:
    """Size of a checkpoint in GB, or None when it cannot be measured.

    Preference order: a local directory, then an already-cached repo id (so the
    gate still works with no network), then Hub *metadata* for an uncached repo
    id - a metadata call, not a download, so it is safe to run before the gate.
    """
    path = Path(model_dir)
    if not path.is_dir():
        path = _snapshot_path(str(model_dir)) or path
    if path.is_dir():
        total = _weight_bytes(path)
        if total:
            return total / 1024**3
    try:
        from huggingface_hub import HfApi  # lazy

        info = HfApi().model_info(str(model_dir), files_metadata=True)
        total = sum(
            s.size or 0
            for s in (info.siblings or [])
            if s.rfilename.endswith(_WEIGHT_SUFFIXES)
        )
        return total / 1024**3 if total else None
    except Exception:
        return None


def disk_gate(
    checkpoint_gb: float,
    margin_gb: float = DEFAULT_MARGIN_GB,
    *,
    path: Optional[Union[str, Path]] = None,
) -> Tuple[bool, str]:
    """Decide whether a checkpoint may be materialised on disk.

    Returns (ok, reason). Mirrors airllm's NotEnoughSpaceException gate
    (airllm/utils.py ~462-468: raise when free < total shard bytes) but runs
    first and keeps DEFAULT_MARGIN_GB of headroom, because airllm's own check
    fires only after the download has already been paid for.

    The measurement is always a fresh shutil.disk_usage - never a cached number.
    """
    root = Path(path) if path is not None else DISK_GATE_ROOT
    probe = root if root.exists() else Path(root.anchor or ".")
    free_gb = shutil.disk_usage(probe).free / 1024**3
    budget_gb = free_gb - margin_gb
    if checkpoint_gb > budget_gb:
        return (
            False,
            f"checkpoint {checkpoint_gb:.2f} GB > budget {budget_gb:.2f} GB "
            f"(free {free_gb:.2f} GB on {probe}, margin {margin_gb:.2f} GB)",
        )
    return (
        True,
        f"checkpoint {checkpoint_gb:.2f} GB <= budget {budget_gb:.2f} GB "
        f"(free {free_gb:.2f} GB on {probe}, margin {margin_gb:.2f} GB)",
    )


def _hf_cache_dir() -> Path:
    home = os.environ.get("HF_HOME")
    base = Path(home) if home else Path.home() / ".cache" / "huggingface"
    return base / "hub"


def _snapshot_path(repo_id: str) -> Optional[Path]:
    """Local snapshot dir of an already-downloaded repo id, else None.

    Prefers the revision named in refs/main; a cache that moved can leave more
    than one snapshot behind, and the newest ref is the one HF would use.
    """
    root = _hf_cache_dir() / ("models--" + repo_id.replace("/", "--"))
    snaps = root / "snapshots"
    try:
        ref = (root / "refs" / "main").read_text(encoding="utf-8").strip()
    except OSError:
        ref = ""
    if ref and (snaps / ref).is_dir():
        return snaps / ref
    try:
        found = sorted(snaps.glob("*"))
    except OSError:
        return None
    return found[-1] if found else None


def _is_cached(repo_id: str) -> bool:
    """True only if the cached snapshot is actually usable.

    A snapshot dir can exist while its weight files are unusable - dangling
    symlinks, or zero-byte stubs, both left behind when a cache root is moved or
    copied without link support. Counting that as "cached" would hand a broken
    path to airllm, so the weights must resolve to real bytes.
    """
    snap = _snapshot_path(repo_id)
    return snap is not None and _weight_bytes(snap) > 0


def _resolve_gate_path(model_dir: Union[str, Path]) -> Path:
    """Where the checkpoint and its layer shards will actually land.

    A local dir is obvious. A repo id downloads into the HF cache, so the gate
    must measure the cache's drive, not the repo's.
    """
    path = Path(model_dir)
    if path.exists():
        return path
    return _hf_cache_dir()


def _ensure_checkpoint(model_dir: Union[str, Path]) -> None:
    """Download a repo id if the gate passed and it is not already cached.

    Never downloads a local path, and never runs for a size we refused on -
    generate() calls this only after disk_gate() returns ok.
    """
    path = Path(model_dir)
    if path.exists() or _is_cached(str(model_dir)):
        print(f"[AIRLLM] checkpoint already present: {model_dir}")
        return
    from huggingface_hub import snapshot_download  # lazy

    print(f"[AIRLLM] downloading {model_dir} ...")
    snapshot_download(str(model_dir))
    print(f"[AIRLLM] download complete: {model_dir}")


def generate(
    prompt: str,
    model_dir: Union[str, Path],
    max_new_tokens: int = 32,
    size_gb: Optional[float] = None,
    device: str = "cpu",
    dtype: str = "float32",
    **kwargs,
) -> str:
    """Generate text with airllm's layer-streaming loader. Returns the text.

    disk_gate() runs FIRST, before any download, layer split, or weight load, so
    an oversized checkpoint costs nothing. Pass size_gb to override the measured
    checkpoint size (needed when the size cannot be probed offline).

    dtype defaults to float32 rather than the checkpoint's native bfloat16: on
    CPU torch has no fast bf16 matmul path, so bf16 here is slower *and* no
    smaller in the one layer that is resident at a time.
    """
    size = size_gb if size_gb is not None else checkpoint_size_gb(model_dir)
    if size is None:
        raise RuntimeError(
            f"cannot measure the checkpoint size of {model_dir} (offline, or no "
            f"weight files found). Pass size_gb=<float> to run the disk gate "
            f"explicitly - this module refuses to guess, because guessing here "
            f"is exactly what fills a disk."
        )
    gate_path = _resolve_gate_path(model_dir)
    ok, reason = disk_gate(size, path=gate_path)
    print(f"[GATE] {reason}")
    if not ok:
        raise RuntimeError(f"disk gate refused {model_dir}: {reason}")

    airllm = _import_airllm()
    torch = _import_torch()
    _ensure_checkpoint(model_dir)

    model = airllm.AutoModel.from_pretrained(
        str(model_dir),
        device=device,
        dtype=getattr(torch, dtype),
        prefetching=(device != "cpu"),  # prefetch is CUDA-only in airllm 4.0
        **kwargs,
    )
    inputs = model.tokenizer(prompt, return_tensors="pt")
    out = model.generate(**inputs, max_new_tokens=max_new_tokens)
    return model.tokenizer.decode(out[0], skip_special_tokens=True).strip()


def teacher_answer(prompt: str, model_dir: Union[str, Path], **kwargs) -> str:
    """OPT-IN teacher backend shaped like the Ollama teacher in
    scripts/teacher/generate_curriculum.py and orion_dataset.teacher_samples().

    Same contract: one question in, one plain-text answer out, no streaming, no
    formatting. Callers that want it pass model_dir explicitly.

    The default teacher is still the local Ollama qwen2.5:3b and those scripts
    are NOT rewired. This exists for the case where Ollama is down and a
    multi-GB model genuinely will not fit this laptop's free disk anyway - in
    which case the small airllm path is the only teacher left, at a large speed
    cost.
    """
    return generate(prompt, model_dir, **kwargs)


def _self_check() -> bool:
    """Gate self-test, then one real tiny generation.

    Returns True only on a generation that actually produced text. An honest
    BLOCKED is a valid outcome, so nothing here may claim a success it did not
    observe.
    """
    free_gb = shutil.disk_usage(DISK_GATE_ROOT).free / 1024**3
    print(f"[SELF-CHECK] disk gate root {DISK_GATE_ROOT} free={free_gb:.2f} GB")

    # 1) The 7B-class candidate must be refused, with no download attempted.
    ok7, why7 = disk_gate(15.2)
    print(
        f"[GATE] 15.20 GB candidate (Qwen2.5-7B class) -> "
        f"{'PASS' if ok7 else 'REJECT'}: {why7}"
    )
    assert not ok7, "15.2 GB must never pass on this box"

    # 2) A 1 GB candidate must pass, since the box has room for it.
    ok1, why1 = disk_gate(1.0)
    print(
        f"[GATE] 1.00 GB candidate (Qwen2.5-0.5B class) -> "
        f"{'PASS' if ok1 else 'REJECT'}: {why1}"
    )
    assert ok1, f"1 GB must fit this box: {why1}"

    repo = "Qwen/Qwen2.5-0.5B-Instruct"
    snap = _snapshot_path(repo)
    if snap is not None and not _is_cached(repo):
        print(
            f"[CACHE] {snap} exists but its weight files do not resolve "
            f"(unusable cache pointers) -> treating as uncached"
        )
    size = checkpoint_size_gb(repo)
    if size is None:
        print(f"BLOCKED: {repo} - checkpoint size unmeasurable (not cached, no Hub)")
        return False
    ok, why = disk_gate(size, path=_resolve_gate_path(repo))
    print(f"[GATE] {repo} ({size:.2f} GB) -> {'PASS' if ok else 'REJECT'}: {why}")
    if not ok:
        print(f"BLOCKED: {repo} - {why}")
        return False

    try:
        import time  # local to the self-check

        t0 = time.time()
        text = generate("Hello, I am ORION.", repo, max_new_tokens=16)
        dt = time.time() - t0
    except Exception as e:  # an honest BLOCKED is a valid outcome
        print(f"BLOCKED: {repo} - {type(e).__name__}: {e}")
        return False

    if not text:
        print(f"BLOCKED: {repo} - generation returned empty text")
        return False

    local = _snapshot_path(repo) or _resolve_gate_path(repo)
    print(f"[GEN] {dt:.1f}s on cpu -> {text!r}")
    print(f"SELF-CHECK ok: {local} ({_weight_bytes(local)} bytes)")
    return True


if __name__ == "__main__":  # self-check on a real tiny generation
    sys.exit(0 if _self_check() else 1)
