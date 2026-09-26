#!/usr/bin/env python3
"""Measure this machine and score airllm teacher candidates before downloading anything.

airllm (lyogavin/airllm) streams one decoder layer at a time from disk into
accelerator memory: it attaches forward hooks to every big module, loads that
module's shard, runs it, then frees it. That keeps steady-state memory tiny,
but it does NOT make a model free — the full checkpoint still has to exist on
disk, and the first pass reads the whole thing.

So this script answers one question honestly: given the disk and RAM this
laptop actually has right now, which teacher models are realistic for the
ORION distillation use-case? Nothing is downloaded here; this is arithmetic
against measured headroom, and the numbers are re-measured on every run
because free space changes as corpora and checkpoints accumulate.

The disk test mirrors airllm's own gate (airllm/utils.py: free space must
cover the shard files, else NotEnoughSpaceException), with an added safety
margin so a run does not wedge the machine mid-conversion.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

GIB = 1024**3

# Candidate teachers for distillation, with approximate full-checkpoint size in
# bytes (bf16 safetensors as published on the Hub). Airllm does not need the
# model to fit in RAM, so these are deliberately graded up past the 3.9 GB of
# free RAM this laptop usually has.
SAFETY_MARGIN_BYTES = 1.5 * GIB


@dataclass(frozen=True)
class Candidate:
    """A teacher model we might want to run under airllm."""

    name: str
    size_bytes: int

    @property
    def size_gb(self) -> float:
        return self.size_bytes / GIB


CANDIDATES = (
    Candidate("Qwen2.5-0.5B-Instruct", int(1.0 * GIB)),
    Candidate("Qwen2.5-1.5B-Instruct", int(3.1 * GIB)),
    Candidate("Qwen2.5-3B-Instruct", int(6.2 * GIB)),
    Candidate("Qwen2.5-7B-Instruct", int(15.2 * GIB)),
)


def free_disk_bytes(path: Path) -> int:
    """Free bytes on the filesystem holding `path`."""
    return shutil.disk_usage(path).free


def free_ram_bytes() -> tuple[int, str]:
    """(free physical RAM, how it was measured).

    psutil is what airllm itself pulls in, so it is the normal path; the
    ctypes fallback keeps the script usable in a bare interpreter.
    """
    try:
        import psutil

        return psutil.virtual_memory().available, "psutil"
    except ImportError:
        pass

    if sys.platform == "win32":

        class _MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
            raise OSError("GlobalMemoryStatusEx failed")
        return status.ullAvailPhys, "ctypes:GlobalMemoryStatusEx"

    # POSIX fallback: MemAvailable from /proc, else page size * free pages.
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024, "/proc/meminfo"
    except OSError:
        pass
    page_size = os.sysconf("SC_PAGE_SIZE")
    return page_size * os.sysconf("SC_AVPHYS_PAGES"), "sysconf"


def verdict(
    cand: Candidate, disk_free: int, ram_free: int
) -> tuple[str, str, bool, bool]:
    """Score one candidate. Returns (verdict, reason, fits_disk, fits_ram)."""
    disk_budget = disk_free - SAFETY_MARGIN_BYTES
    fits_disk = cand.size_bytes < disk_budget
    # The conversion pass materialises the checkpoint, so it needs a fraction
    # of the checkpoint free in RAM even though steady-state inference does not.
    ram_needed = cand.size_bytes // 4
    fits_ram = ram_needed < ram_free

    disk_headroom = disk_budget - cand.size_bytes
    ram_headroom = ram_free - ram_needed

    if not fits_disk and not fits_ram:
        return "BLOCKED", "over disk budget and RAM-loading budget", fits_disk, fits_ram
    if not fits_disk:
        return (
            "BLOCKED",
            f"needs {cand.size_gb:.1f} GB disk, only {disk_budget / GIB:.1f} GB usable",
            fits_disk,
            fits_ram,
        )
    if not fits_ram:
        return (
            "BLOCKED",
            f"RAM-loading step wants {ram_needed / GIB:.1f} GB, only {ram_free / GIB:.1f} GB free",
            fits_disk,
            fits_ram,
        )
    if disk_headroom < 3.0 * GIB or ram_headroom < 1.0 * GIB:
        detail = []
        if disk_headroom < 3.0 * GIB:
            detail.append(f"disk headroom {disk_headroom / GIB:.1f} GB")
        if ram_headroom < 1.0 * GIB:
            detail.append(f"RAM headroom {ram_headroom / GIB:.1f} GB")
        return "MARGINAL", "fits but " + " and ".join(detail), fits_disk, fits_ram
    return "VERIFIED", "fits comfortably", fits_disk, fits_ram


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    disk_free = free_disk_bytes(root)
    ram_free, ram_source = free_ram_bytes()

    print("airllm teacher feasibility probe")
    print("=" * 78)
    print(f"repo path          : {root}")
    print(
        f"free disk          : {disk_free / GIB:.2f} GB (safety margin 1.50 GB -> {max(disk_free - SAFETY_MARGIN_BYTES, 0) / GIB:.2f} GB usable)"
    )
    print(f"free RAM           : {ram_free / GIB:.2f} GB (measured via {ram_source})")
    print()
    print(f"{'model':<28}{'ckpt':>8}{'disk':>7}{'ram':>7}  {'verdict':<9}reason")
    print("-" * 78)

    counts = {"VERIFIED": 0, "MARGINAL": 0, "BLOCKED": 0}
    for cand in CANDIDATES:
        label, reason, fits_disk, fits_ram = verdict(cand, disk_free, ram_free)
        counts[label] += 1
        disk_cell = "ok" if fits_disk else "NO"
        ram_cell = "ok" if fits_ram else "NO"
        print(
            f"{cand.name:<28}{cand.size_gb:>6.1f}GB{disk_cell:>7}{ram_cell:>7}  {label:<9}{reason}"
        )

    print("-" * 78)
    print(
        f"summary: {counts['VERIFIED']} VERIFIED, {counts['MARGINAL']} MARGINAL, {counts['BLOCKED']} BLOCKED"
    )
    print(
        "disk test  : checkpoint < free disk - 1.5 GB  (mirrors airllm's own space gate)"
    )
    print(
        "ram test   : checkpoint / 4 < free RAM        (one-off conversion read, not steady state)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
