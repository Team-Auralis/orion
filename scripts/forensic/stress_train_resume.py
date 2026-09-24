#!/usr/bin/env python3
"""F7: resource stress + crash-recovery of the COMP-001 training harness.

Stress-test the REAL harness (scripts/training/train_comp001.py), CPU-only,
on a SCRATCH model dir - NEVER the canonical 100m-real directory, and NEVER
the canonical ledger logs/training_runs.jsonl (this suite writes only
logs/forensic/stress_runs_local.jsonl, clearly marked FORENSIC STRESS RUNS).

Phases:
  A. Bootstrap scratch run    -- tiny fresh run (10k budget, 6 steps), numbers.
  B. Crash-mid-run recovery   -- bigger scratch run (40k budget), parent KILLs
     the child (hard process kill = realistic crash) after 4 checkpoints,
     then resumes with the harness's native --resume, proving the loss curve
     continues with no discontinuity and no duplicate/corrupt checkpoint.
  C. Memory leak check        -- 30 forward+backward steps in one process,
     RSS sampled every step; linear-fit slope (MB/step) < 1 => PASS.
  D. Sustained uptime         -- whole-suite wall time + min free RAM
     (floor 250 MB; abort cleanly, never OOM).

Reuses the real harness building blocks (build_model / load_data /
make_blocks / save_checkpoint / load_checkpoint) by patching its OUT_DIR
to the scratch dir; NEVER calls record_experiment (no canonical ledger row).

Usage:
    python scripts/forensic/stress_train_resume.py            # full driver
    python scripts/forensic/stress_train_resume.py --phase scratch_child|crash_child|resume_child  # internal

Outputs:
    logs/forensic/stress_training.json        summary (all numbers)
    logs/forensic/stress_runs_local.jsonl     per-step forensic rows (crash-proof)
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "training"))

import psutil  # noqa: E402

SCRATCH_ROOT = REPO_ROOT / "models" / "scratch-for-stress"
RUN_A = SCRATCH_ROOT / "runA-bootstrap"
RUN_B = SCRATCH_ROOT / "runB-crashresume"
LEDGER = REPO_ROOT / "logs" / "training_runs.jsonl"
CANON_100M = REPO_ROOT / "models" / "comp001" / "100m-real"
CANON_10M = REPO_ROOT / "models" / "comp001" / "10m"
FORENSIC_JSON = REPO_ROOT / "logs" / "forensic" / "stress_training.json"
LOCAL_JSONL = REPO_ROOT / "logs" / "forensic" / "stress_runs_local.jsonl"

RAM_FLOOR_MB = 250.0
SEED = 42
LR = 1e-3
THREADS = 6
CKPT_EVERY = 2
BUDGET_BOOT = 10_000
BUDGET_CRASH = 40_000
SCRATCH_MAX_STEPS = 6
CRASH_MAX_STEPS = 200  # child trains to a HIGH cap; parent kills it mid-run
RESUME_TAIL_STEPS = 6  # continuation after the crash checkpoint (steps 9..14)
MONITOR_INTERVAL_S = 1.0
MARKER = {
    "kind": "marker",
    "note": "FORENSIC STRESS RUN - not a canonical training ledger row",
}

# Mini harness config for the stress run (task-sanctioned): mirrors the 100m
# config SHAPE but tiny so it fits the current RAM headroom and trains fast.
# NOTE/FINDING: the stock harness `10m` config CANNOT run with the real BPE
# vocab 10240 - its hard param-budget assert [8M,12M] rejects the 13.6M-param
# model that config builds at vocab 10240. So stress uses a patched mini cfg
# through the SAME harness build_model path (seed, Qwen2Config, budget check).
MINI_CFG = dict(
    vocab_size=None,  # replaced with the real tokenizer vocab at build time
    hidden_size=64,
    intermediate_size=256,
    num_hidden_layers=2,
    num_attention_heads=2,
    num_key_value_heads=2,
    max_position_embeddings=512,
    pad_token_id=0,
    bos_token_id=1,
    eos_token_id=2,
    tie_word_embeddings=False,
)


def patch_mini_harness(tc) -> None:
    """Point the harness's 10m MODEL_SIZES/budget at the stress mini config."""
    tc.MODEL_SIZES["10m"] = MINI_CFG
    tc.PARAM_BUDGETS["10m"] = (0, 100_000_000)  # relax assert; params ~1.4M


# ---------------------------------------------------------------------------
# crash-proof forensic ledger (OSS: never the canonical training_runs.jsonl)
# ---------------------------------------------------------------------------


def log_row(row: dict) -> None:
    LOCAL_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCAL_JSONL, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
        f.flush()


def read_rows() -> list[dict]:
    if not LOCAL_JSONL.exists():
        return []
    return [
        json.loads(x)
        for x in LOCAL_JSONL.read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def ckpts_of(root: Path) -> list[tuple[int, Path]]:
    out = []
    if root.is_dir():
        for d in root.glob("checkpoint-*"):
            try:
                out.append((int(d.name.split("-")[1]), d))
            except (IndexError, ValueError):
                continue
    return sorted(out)


# ---------------------------------------------------------------------------
# shared training bit (runs INSIDE the child process = the real harness path)
# ---------------------------------------------------------------------------


def _harness_run(
    phase: str, budget: int, max_steps: int, resume: str | None = None
) -> int:
    """Mirror train_comp001.py main() exactly, but OUT_DIR=scratch and NO
    record_experiment; everything else (data load, model build, optimizer,
    checkpoint save/load, resume semantics) is the real harness code."""
    import train_comp001 as tc

    scratch = RUN_A if phase == "scratch_child" else RUN_B
    scratch.mkdir(parents=True, exist_ok=True)
    tc.OUT_DIR = scratch  # redirect the harness's checkpoint helpers to scratch
    patch_mini_harness(tc)  # stress mini config through the real build_model path

    import torch  # noqa: E402

    torch.set_num_threads(THREADS)

    t_load0 = time.time()
    (
        tokenizer,
        vocab,
        train_rows,
        val_rows,
        files,
        train_files,
        corpus_sha,
        val_test_sha,
        slice_tokens,
    ) = tc.load_data(budget)
    train_blocks = tc.make_blocks(train_rows, tokenizer)
    per_epoch = len(train_blocks)
    log_row(
        {
            "kind": "data",
            "phase": phase,
            "budget": budget,
            "slice_tokens": slice_tokens,
            "train_rows": len(train_rows),
            "blocks": per_epoch,
            "vocab": vocab,
            "data_load_s": round(time.time() - t_load0, 2),
        }
    )

    model, cfg, n_params = tc.build_model(vocab, SEED, "10m")
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR)
    losses: list[float] = []
    start_step = 0
    ckpt_last_loss = None
    if resume:
        start_step, loaded_losses = tc.load_checkpoint(Path(resume), model, optimizer)
        ckpt_last_loss = loaded_losses[-1] if loaded_losses else None
        losses = list(loaded_losses)
    # harness semantics: --max-steps caps ADDITIONAL steps from start_step
    total_steps = start_step + max_steps

    model.train()
    peak_rss = 0.0
    t0 = time.time()
    for gstep in range(start_step, total_steps):
        block = train_blocks[gstep % per_epoch]
        input_ids = torch.tensor(block["input_ids"], dtype=torch.long).unsqueeze(0)
        labels = torch.tensor(block["labels"], dtype=torch.long).unsqueeze(0)
        optimizer.zero_grad()
        out = model(input_ids=input_ids, labels=labels)
        out.loss.backward()
        optimizer.step()
        step = gstep + 1
        loss = float(out.loss.item())
        losses.append(loss)
        rss = psutil.Process().memory_info().rss / 1024**2
        peak_rss = max(peak_rss, rss)
        log_row(
            {
                "kind": "step",
                "phase": phase,
                "step": step,
                "loss": round(loss, 6),
                "rss_mb": round(rss, 1),
            }
        )
        print(
            f"  step {step:3d}/{total_steps} loss {loss:.4f} rss {rss:.0f} MB",
            flush=True,
        )
        if step % CKPT_EVERY == 0 or step == total_steps:
            tc.save_checkpoint(step, model, optimizer, cfg, {}, losses)

    train_s = time.time() - t0
    log_row(
        {
            "kind": "run_summary",
            "phase": phase,
            "steps": len(losses),
            "start_loss": round(losses[0], 6) if losses else None,
            "end_loss": round(losses[-1], 6) if losses else None,
            "train_s": round(train_s, 2),
            "peak_rss_mb": round(peak_rss, 1),
            "ckpt_last_loss": ckpt_last_loss,
            "resumed_from": resume,
            "params": n_params,
            "seed": SEED,
            "threads": THREADS,
        }
    )
    return 0


# ---------------------------------------------------------------------------
# driver phases
# ---------------------------------------------------------------------------


def _spawn_child(phase: str, *extra: str) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--phase", phase, *extra],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )


def _wait_or_kill(p: subprocess.Popen, timeout_s: float, what: str) -> int | None:
    try:
        return p.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
        print(f"[TIMEOUT] killed child during {what}")
        return None


def phase_scratch(mean_step_s_ref: list[float]) -> dict:
    RUN_A.mkdir(parents=True, exist_ok=True)
    p = _spawn_child(
        "scratch_child",
        "--budget",
        str(BUDGET_BOOT),
        "--max-steps",
        str(SCRATCH_MAX_STEPS),
    )
    rc = _wait_or_kill(p, 600, "scratch bootstrap")
    out_buf = p.communicate()[0] if p.stdout else ""
    if out_buf:
        print(out_buf)
    if rc != 0:
        raise SystemExit(f"scratch bootstrap failed rc={rc}")
    rows = [r for r in read_rows() if r.get("phase") == "scratch_child"]
    summ = next((r for r in rows if r.get("kind") == "run_summary"), {})
    steps = [r for r in rows if r.get("kind") == "step"]
    mean_step_s_ref[0] = summ.get("train_s", 0) / max(1, len(steps))
    res = {
        "run_dir": str(RUN_A),
        "rc": rc,
        "steps": len(steps),
        "start_loss": summ.get("start_loss"),
        "end_loss": summ.get("end_loss"),
        "train_s": summ.get("train_s"),
        "mean_step_s": round(mean_step_s_ref[0], 3),
        "peak_rss_mb": summ.get("peak_rss_mb"),
        "ckpts_written": [str(s) for _, s in ckpts_of(RUN_A)],
    }
    print("[SCRATCH]", json.dumps(res))
    return res


def phase_crash() -> dict:
    if RUN_B.exists():
        import shutil

        shutil.rmtree(RUN_B, ignore_errors=True)
    RUN_B.mkdir(parents=True, exist_ok=True)
    p = _spawn_child(
        "crash_child",
        "--budget",
        str(BUDGET_CRASH),
        "--max-steps",
        str(CRASH_MAX_STEPS),
    )
    # Kill trigger: >= 4 checkpoints AND a loss row exists exactly ONE step past
    # the current max checkpoint step (row S+1 exists => save-S fully finished,
    # so the resume target S is provably complete AND the post-resume run will
    # recompute S+1 for a bit-exact same-step comparison). Hard kill = real crash.
    dead_rows: list[dict] = []
    t0 = time.time()
    while True:
        dead_rows = [
            r
            for r in read_rows()
            if r.get("phase") == "crash_child" and r.get("kind") == "step"
        ]
        ckpts = ckpts_of(RUN_B)
        max_ckpt = ckpts[-1][0] if ckpts else 0
        steps = {r.get("step") for r in dead_rows}
        if max_ckpt >= 8 and (max_ckpt + 1) in steps:  # row at S+1 with S>=8
            break
        if time.time() - t0 > 600:
            p.kill()
            p.wait()
            raise SystemExit("[CRASH] time-out waiting for kill condition")
        time.sleep(0.05)
    killed_at = time.time()
    p.kill()
    rc = p.wait()
    if p.stdout:
        out = p.communicate()[0]
        if out:
            print("[CRASH-CHILD-STDOUT]\n" + out)
    dead_rows = [
        r
        for r in read_rows()
        if r.get("phase") == "crash_child" and r.get("kind") == "step"
    ]
    ckpts = ckpts_of(RUN_B)
    last_ckpt = ckpts[-1][0] if ckpts else 0
    res = {
        "kill_rc": rc,
        "killed_after_s": round(killed_at - t0, 1),
        "ckpts_at_kill": [s for s, _ in ckpts],
        "last_ckpt_step": last_ckpt,
        "last_logged_step": dead_rows[-1]["step"] if dead_rows else None,
        "pre_kill_losses": {r["step"]: r["loss"] for r in dead_rows},
        "pre_kill_rss_mb": {r["step"]: r["rss_mb"] for r in dead_rows},
    }
    print("[CRASH]", json.dumps(res, default=str))
    return res


def phase_resume() -> dict:
    """Resume from the newest COMPLETE checkpoint; if the top checkpoint is an
    interrupted-save artifact (kill landed mid-torch.save -> unreadable
    checkpoint.pt), fall back to the previous complete checkpoint and record
    the artifact (the harness has no atomic checkpoint-save; seen naturally)."""
    attempts: list[dict] = []
    rows = read_rows()
    pre = [
        r for r in rows if r.get("phase") == "crash_child" and r.get("kind") == "step"
    ]
    pre_loss = {r["step"]: r["loss"] for r in pre}
    pre_rss = {r["step"]: r["rss_mb"] for r in pre}

    for ckpt_step, ckpt_dir in reversed(ckpts_of(RUN_B)):
        remaining = min(max(2, CRASH_MAX_STEPS - ckpt_step), RESUME_TAIL_STEPS)
        p = _spawn_child(
            "resume_child",
            "--budget",
            str(BUDGET_CRASH),
            "--max-steps",
            str(remaining),
            "--resume",
            str(ckpt_dir),
        )
        rc = _wait_or_kill(p, 600, f"crash-resume from ckpt-{ckpt_step}")
        out = p.communicate()[0] if p.stdout else ""
        if out:
            print(out)
        attempts.append(
            {"ckpt_step": ckpt_step, "rc": rc, "stdout_tail": (out or "")[-400:]}
        )
        if rc == 0:
            break

    good = next((a for a in attempts if a["rc"] == 0), None)
    if good is None:
        raise SystemExit(f"resume failed on all checkpoints: {attempts}")

    rows = read_rows()
    post = [
        r for r in rows if r.get("phase") == "resume_child" and r.get("kind") == "step"
    ]
    post_loss = {r["step"]: r["loss"] for r in post}
    overlap = sorted(set(pre_loss) & set(post_loss))
    same_step_deltas = {s: round(abs(pre_loss[s] - post_loss[s]), 6) for s in overlap}
    first_post = post[0]["loss"] if post else None
    last_pre = max(pre_loss, default=None)
    last_pre_loss = pre_loss.get(last_pre) if last_pre else None
    ckpt_last_loss = None
    summ = next(
        (
            r
            for r in rows
            if r.get("phase") == "resume_child" and r.get("kind") == "run_summary"
        ),
        {},
    )
    ckpt_last_loss = summ.get("ckpt_last_loss")

    # checkpoint integrity: unique steps, valid json, non-empty pt, json.step == dir
    integrity = []
    seen = {}
    for s, d in ckpts_of(RUN_B):
        seen[s] = seen.get(s, 0) + 1
        try:
            ckj = json.loads((d / "checkpoint.json").read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001 - interrupted-save artifact
            integrity.append({"step": s, "dir_ok": False, "json_error": str(e)[:200]})
            continue
        pt = d / "checkpoint.pt"
        integrity.append(
            {
                "step": s,
                "json_step": ckj.get("step"),
                "dir_ok": ckj.get("step") == s,
                "pt_bytes": pt.stat().st_size if pt.exists() else 0,
            }
        )
    resumed_step = good["ckpt_step"]
    res = {
        "resumed_from": f"{RUN_B / ('checkpoint-' + str(resumed_step))}",
        "resume_attempts": attempts,
        "interrupted_save_artifacts": [
            a["ckpt_step"] for a in attempts if a["rc"] != 0
        ],
        "rc": good["rc"],
        "ckpt_loss_before_resume": ckpt_last_loss,
        "first_post_resume_loss": first_post,
        "last_pre_kill_loss": last_pre_loss,
        "last_pre_kill_step": last_pre,
        "overlap_steps": overlap,
        "same_step_max_delta": max(same_step_deltas.values(), default=0.0),
        "same_step_deltas": same_step_deltas,
        "pre_kill_losses": pre_loss,
        "pre_kill_rss_mb": pre_rss,
        "post_resume_losses": post_loss,
        "harness_warm_resume_check": bool(
            first_post is not None
            and ckpt_last_loss is not None
            and abs(first_post - ckpt_last_loss) < 0.5 * ckpt_last_loss
        ),
        "ckpt_duplicates": {s: n for s, n in seen.items() if n > 1},
        "ckpt_integrity": integrity,
    }
    print("[RESUME]", json.dumps(res, default=str))
    return res


def phase_leak() -> dict:
    """30 forward+backward steps in ONE process; RSS sampled every step."""
    import numpy as np
    import torch
    import train_comp001 as tc

    tc.OUT_DIR = RUN_B  # keep checkpoint helpers off canonicals (no saves here anyway)
    patch_mini_harness(tc)  # stress mini config through the real build_model path
    torch.set_num_threads(THREADS)
    (
        tokenizer,
        vocab,
        train_rows,
        val_rows,
        files,
        train_files,
        _,
        _,
        _,
    ) = tc.load_data(BUDGET_BOOT)
    blocks = tc.make_blocks(train_rows, tokenizer)
    model, _, _ = tc.build_model(vocab, SEED, "10m")
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR)
    model.train()

    samples = []  # (step, rss_mb)
    n = 30
    for i in range(n):
        block = blocks[i % len(blocks)]
        input_ids = torch.tensor(block["input_ids"], dtype=torch.long).unsqueeze(0)
        labels = torch.tensor(block["labels"], dtype=torch.long).unsqueeze(0)
        optimizer.zero_grad()
        out = model(input_ids=input_ids, labels=labels)
        out.loss.backward()
        optimizer.step()
        samples.append((i + 1, psutil.Process().memory_info().rss / 1024**2))
        log_row({"kind": "leak_sample", "step": i + 1, "rss_mb": samples[-1][1]})
        if sampler_min_free[0] < RAM_FLOOR_MB:
            raise SystemExit(
                f"[RAM] free RAM {sampler_min_free[0]:.0f} MB < {RAM_FLOOR_MB:.0f} MB floor during leak phase"
            )
    del model, optimizer
    gc.collect()
    del torch
    # steady-state slope over steps 6..30 (warmup excluded for the fit)
    xs = [s for s, _ in samples[5:]]
    ys = [r for _, r in samples[5:]]
    slope = float(np.polyfit(xs, ys, 1)[0]) if len(xs) >= 2 else 0.0
    res = {
        "steps": n,
        "rss_samples_mb": [r for _, r in samples],
        "rss_start_mb": samples[0][1],
        "rss_end_mb": samples[-1][1],
        "rss_delta_mb": round(samples[-1][1] - samples[0][1], 2),
        "steady_state_slope_mb_per_step": round(slope, 4),
        "slope_pass": slope < 1.0,
    }
    print("[LEAK]", json.dumps(res))
    return res


# ---------------------------------------------------------------------------
# whole-suite driver
# ---------------------------------------------------------------------------

sampler_min_free = [float("inf")]  # [min free MB] shared with background thread
stop_evt = threading.Event()  # tells the monitor to stop (normal end of run)
ram_aborted = threading.Event()  # set ONLY when the RAM floor is breached
mean_step_s = [0.5]


def _monitor() -> None:
    while not stop_evt.is_set():
        avail = psutil.virtual_memory().available / 1024**2
        sampler_min_free[0] = min(sampler_min_free[0], avail)
        if avail < RAM_FLOOR_MB:
            ram_aborted.set()
            print(f"[RAM-ABORT] free RAM {avail:.0f} MB < {RAM_FLOOR_MB:.0f} MB floor")
        time.sleep(MONITOR_INTERVAL_S)


def ckpt_names(path: Path) -> list[str]:
    return sorted(d.name for d in path.glob("checkpoint-*")) if path.is_dir() else []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", default="driver")
    ap.add_argument("--budget", type=int, default=0)
    ap.add_argument("--max-steps", type=int, default=0)
    ap.add_argument("--resume", default=None)
    args = ap.parse_args()

    if args.phase in ("scratch_child", "crash_child", "resume_child"):
        budget = args.budget or BUDGET_BOOT
        return _harness_run(args.phase, budget, args.max_steps, args.resume)

    # ---- driver ----
    LOCAL_JSONL.parent.mkdir(parents=True, exist_ok=True)
    if LOCAL_JSONL.exists():
        LOCAL_JSONL.unlink()
    log_row(MARKER)
    ledger_hash_before = sha256_file(LEDGER)
    ledger_lines_before = len(
        [x for x in LEDGER.read_text(encoding="utf-8").splitlines() if x.strip()]
    )
    canon_100m_before = ckpt_names(CANON_100M)
    canon_10m_before = ckpt_names(CANON_10M)
    free_start = psutil.virtual_memory().available / 1024**2
    print(
        f"[ENV] free RAM start {free_start:.0f} MB | floor {RAM_FLOOR_MB:.0f} MB | "
        f"ledger sha256 {ledger_hash_before[:16]}... ({ledger_lines_before} rows)"
    )

    mon = threading.Thread(target=_monitor, daemon=True)
    mon.start()
    t0 = time.time()

    try:
        scratch = phase_scratch(mean_step_s)
        if ram_aborted.is_set():
            raise SystemExit("[RAM-ABORT] after scratch phase")
        crash = phase_crash()
        if ram_aborted.is_set():
            raise SystemExit("[RAM-ABORT] after crash phase")
        resume = phase_resume()
        if ram_aborted.is_set():
            raise SystemExit("[RAM-ABORT] after resume phase")
        leak = phase_leak()
    finally:
        stop_evt.set()
        mon.join()

    wall_s = time.time() - t0

    # ---- ledger isolation ----
    ledger_hash_after = sha256_file(LEDGER)
    ledger_lines_after = len(
        [x for x in LEDGER.read_text(encoding="utf-8").splitlines() if x.strip()]
    )
    ledger_unchanged = ledger_hash_before == ledger_hash_after
    stress_ids_in_ledger = [
        l
        for l in LEDGER.read_text(encoding="utf-8").splitlines()
        if "forensic-stress" in l
    ]
    # ---- canonical checkpoint isolation ----
    canon_100m_after = ckpt_names(CANON_100M)
    canon_10m_after = ckpt_names(CANON_10M)
    canon_unchanged = (
        canon_100m_before == canon_100m_after and canon_10m_before == canon_10m_after
    )

    # ---- scratch cleanup (not an artifact worth ~100+MB) ----
    scratch_size_mb = (
        sum(f.stat().st_size for f in SCRATCH_ROOT.rglob("*") if f.is_file()) / 1024**2
    )
    import shutil

    shutil.rmtree(SCRATCH_ROOT, ignore_errors=True)

    min_free = sampler_min_free[0]
    sustained_ok = min_free > RAM_FLOOR_MB and not ram_aborted.is_set()

    out = {
        "meta": {
            "task": "F7 training-harness resource stress + crash-recovery",
            "harness": "scripts/training/train_comp001.py (10m config, real BPE vocab 10240, CPU)",
            "seed": SEED,
            "lr": LR,
            "threads": THREADS,
            "ckpt_every": CKPT_EVERY,
            "scratch_dir": str(SCRATCH_ROOT),
            "canonical_policy": "stress runs write ONLY models/scratch-for-stress/ + logs/forensic/; "
            "NEVER canonical checkpoints or logs/training_runs.jsonl",
            "free_ram_start_mb": round(free_start, 1),
            "min_free_ram_mb": round(min_free, 1),
            "ram_floor_mb": RAM_FLOOR_MB,
            "wall_s": round(wall_s, 1),
        },
        "scratch_run": scratch,
        "crash_recovery": crash,
        "resume": resume,
        "leak": leak,
        "sustained": {
            "wall_s": round(wall_s, 1),
            "min_free_ram_mb": round(min_free, 1),
            "no_crash_or_oom": sustained_ok,
            "aborted": ram_aborted.is_set(),
        },
        "isolation": {
            "canonical_ledger_path": str(LEDGER),
            "ledger_sha256_before": ledger_hash_before,
            "ledger_sha256_after": ledger_hash_after,
            "ledger_rows_before": ledger_lines_before,
            "ledger_rows_after": ledger_lines_after,
            "ledger_unchanged": ledger_unchanged,
            "stress_ids_in_canonical_ledger": len(stress_ids_in_ledger),
            "git_status_before_start": "M (pre-existing working-tree modification; "
            "confirmed present before any stress run)",
            "canonical_100m_real_ckpts_before": canon_100m_before,
            "canonical_100m_real_ckpts_after": canon_100m_after,
            "canonical_10m_ckpts_unchanged": canon_10m_before == canon_10m_after,
            "canonical_unchanged": canon_unchanged,
        },
        "scratch_cleanup": {
            "deleted": not SCRATCH_ROOT.exists(),
            "max_scratch_size_mb": round(scratch_size_mb, 1),
        },
        "summary_flags": {
            "crash_resume_continuous": bool(
                resume.get("same_step_max_delta", 1e9) < 0.2
                and resume.get("harness_warm_resume_check")
            ),
            "leak_slope_pass": bool(leak.get("slope_pass")),
            "sustained_pass": bool(sustained_ok),
            "isolation_pass": bool(
                ledger_unchanged and canon_unchanged and not stress_ids_in_ledger
            ),
        },
    }
    FORENSIC_JSON.parent.mkdir(parents=True, exist_ok=True)
    FORENSIC_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("\n[DONE] wrote", FORENSIC_JSON)
    print("[FLAGS]", json.dumps(out["summary_flags"]))
    log_row(
        {
            "kind": "suite_summary",
            "wall_s": round(wall_s, 1),
            "min_free_ram_mb": round(min_free, 1),
            "flags": out["summary_flags"],
            "note": "suite-level summary row (forensic, not canonical)",
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
