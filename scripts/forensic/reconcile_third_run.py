#!/usr/bin/env python3
"""reconcile_third_run.py - F3b forensic reconciliation of the discovered third
training run (comp-001-custom-100m-real-9d8dfc35, steps 1869..1919).

Answers, from raw files only (no prior report trusted):
  1. DELTA   what the final 50 steps moved: checkpoint-1869 -> checkpoint-1919
             per-tensor + global abs-delta statistics.
  2. CURVE   honest re-audit over ALL THREE eval points (623 / 1869 / 1919):
             did val loss recover, updated F3 verdict, best checkpoint.
  3. BUDGET  corrected learning-budget fraction. The ledger `tokens_seen`
             values cannot be summed naively across resumed invocations
             (double-counts the re-processed slice); code-verified semantics
             are recorded.
  4. TRUTH   true latest checkpoint = checkpoint-1919; the committed HF export
             model.safetensors is stale (byte-identical to checkpoint-1869 per
             F1). The export is NEVER modified here.

Memory discipline (this box is RAM-starved, one 1.27 GB checkpoint at a time):
  * load checkpoint-1919, extract weights, del + gc.collect();
  * load checkpoint-1869, extract weights, del + gc.collect();
  * compare per-tensor; transient delta arrays are freed each iteration.
Outputs (small text only; existing forensic files are never deleted):
  logs/forensic/reconcile.json
  append section -> logs/forensic/provenance_report.txt
"""

from __future__ import annotations

import gc
import json
import math
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_identity import Tracker, load_checkpoint, rss_now_mb  # reuse F1 loader

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "logs" / "training_runs.jsonl"
CKPT_DIR = ROOT / "models" / "comp001" / "100m-real"
EXPORT = CKPT_DIR / "model.safetensors"
OUT_JSON = ROOT / "logs" / "forensic" / "reconcile.json"
OUT_REPORT = ROOT / "logs" / "forensic" / "provenance_report.txt"
CORPUS_TOKENS = 63_827_053
HIST_BINS = 1_000_000

RUN_IDS = [
    "comp-001-custom-100m-real-e08d7bb7",
    "comp-001-custom-100m-real-0d9808ff",
    "comp-001-custom-100m-real-9d8dfc35",
]
# ground truth taken from logs/training_runs.jsonl (orchestrator-verified)
EXPECTED = [
    {
        "run_id": RUN_IDS[0],
        "step": 623,
        "tokens_seen": 281_813,
        "eval_loss": 7.622762,
        "start_loss": 9.460998,
        "end_loss": 6.56257,
        "perplexity": 2044.201,
    },
    {
        "run_id": RUN_IDS[1],
        "step": 1869,
        "tokens_seen": 563_626,
        "eval_loss": 7.938125,
        "start_loss": 6.574713,
        "end_loss": 5.877017,
        "perplexity": 2802.101,
    },
    {
        "run_id": RUN_IDS[2],
        "step": 1919,
        "tokens_seen": 22_401,
        "eval_loss": 7.706575,
        "start_loss": 6.495296,
        "end_loss": 6.435823,
        "perplexity": 2222.9157,
    },
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def rss_mb() -> int:
    return int(rss_now_mb())


# ---------------------------------------------------------------------------
# ledger
# ---------------------------------------------------------------------------


def read_ledger_rows() -> dict:
    rows = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        if d.get("run_id") in RUN_IDS:
            rows[d["run_id"]] = d
    missing = [r for r in RUN_IDS if r not in rows]
    assert not missing, f"ledger rows missing: {missing}"
    verified = []
    for exp in EXPECTED:
        d = rows[exp["run_id"]]
        checks = {
            "tokens_seen": d["tokens_seen"] == exp["tokens_seen"],
            "eval_loss": abs(d["eval_loss"] - exp["eval_loss"]) < 1e-9,
            "start_loss": abs(d["starting_loss"] - exp["start_loss"]) < 1e-9,
            "end_loss": abs(d["ending_loss"] - exp["end_loss"]) < 1e-9,
            "perplexity": abs(d["perplexity"] - exp["perplexity"]) / exp["perplexity"]
            < 0.01,
        }
        assert all(checks.values()), (exp["run_id"], checks)
        verified.append(
            {
                "run_id": exp["run_id"],
                "step": exp["step"],
                "timestamp": d["timestamp"],
                "tokens_seen": d["tokens_seen"],
                "eval_loss": round(float(d["eval_loss"]), 6),
                "start_loss": round(float(d["starting_loss"]), 6),
                "end_loss": round(float(d["ending_loss"]), 6),
                "perplexity_ledger": d["perplexity"],
                "ppl_from_eval_loss": round(math.exp(float(d["eval_loss"])), 4),
                "duration_seconds": d["duration_seconds"],
                "resume_from_step": d["resume_from_step"],
                "max_steps": d["params"].get("max_steps"),
            }
        )
    return verified


# ---------------------------------------------------------------------------
# checkpoint loads (ONE at a time: extract, del, gc)
# ---------------------------------------------------------------------------


def load_model_sd(ckpt_subdir: str, tracker: Tracker):
    p = CKPT_DIR / ckpt_subdir / "checkpoint.pt"
    obj, attempts, mode = load_checkpoint(p, tracker)
    assert isinstance(obj, dict) and "model" in obj, (
        f"{ckpt_subdir}: unexpected checkpoint object"
    )
    sd = obj["model"]
    meta = {
        "step": obj.get("step"),
        "losses_len": len(obj.get("losses") or []),
        "losses_last": round(float(obj["losses"][-1]), 6)
        if obj.get("losses")
        else None,
        "timestamp": obj.get("timestamp"),
        "load_mode": mode,
    }
    del obj
    gc.collect()
    mb = sum(t.numel() for t in sd.values()) * 4 / 2**20
    tracker.log(
        "MEM",
        f"after {ckpt_subdir}: rss={rss_mb()} MB holding ~{mb:.0f} MB fp32 weights",
    )
    return sd, meta


def load_pair(tracker: Tracker):
    """load 1919 first, then 1869 (task order). Returns (new, new_meta, old, old_meta)."""
    sd1919, meta1919 = load_model_sd("checkpoint-1919", tracker)
    sd1869, meta1869 = load_model_sd("checkpoint-1869", tracker)
    assert sorted(sd1919) == sorted(sd1869), "state dict key sets differ"
    return sd1919, meta1919, sd1869, meta1869


# ---------------------------------------------------------------------------
# delta statistics
# ---------------------------------------------------------------------------


def compute_deltas(sd_new, sd_old, tracker: Tracker):
    """new = checkpoint-1919, old = checkpoint-1869. delta = new - old."""
    per_tensor = {}
    g = {  # global accumulators (population statistics)
        "numel": 0,
        "sum": 0.0,
        "sumsq": 0.0,
        "max_abs": 0.0,
        "min_abs": math.inf,
        "n_gt0": 0,
        "n_gt_abs1e6": 0,
        "n_gt_rel1e6": 0,
        "n_gt_rel1e4": 0,
        "n_tensors": 0,
    }
    best_mean = {"key": None, "val": -1.0}
    best_max = {"key": None, "val": -1.0}
    t0 = time.perf_counter()
    for k in sorted(sd_new):
        a, b = sd_new[k], sd_old[k]
        n = a.numel()
        diff = a - b
        d = diff.abs()
        da = d.numpy()
        mean_abs = float(np.mean(da))
        std_abs = float(np.std(da))
        med_abs = float(np.median(da))
        max_abs = float(np.max(da))
        min_abs = float(np.min(da))
        signed_mean = float(diff.mean())
        n_gt0 = int(np.count_nonzero(da))
        n_gt_abs1e6 = int(np.count_nonzero(da > 1e-6))
        ref_std = float(
            b.std()
        )  # baseline (old) tensor std, denominators for rel thresholds
        if ref_std == 0.0:
            ref_std = 1e-12
        n_gt_rel1e6 = int(np.count_nonzero(da > 1e-6 * ref_std))
        n_gt_rel1e4 = int(np.count_nonzero(da > 1e-4 * ref_std))
        rec = {
            "shape": list(a.shape),
            "numel": n,
            "mean_abs_delta": round(mean_abs, 9),
            "median_abs_delta": round(med_abs, 9),
            "std_abs_delta": round(std_abs, 9),
            "max_abs_delta": round(max_abs, 9),
            "min_abs_delta": round(min_abs, 9),
            "signed_mean_delta": round(signed_mean, 9),
            "ref_std_old": round(ref_std, 9),
            "n_changed_gt0": n_gt0,
            "n_gt_abs_1e6": n_gt_abs1e6,
            "n_gt_1e6_std": n_gt_rel1e6,
            "n_gt_1e4_std": n_gt_rel1e4,
        }
        per_tensor[k] = rec
        # global accumulation
        g["numel"] += n
        g["sum"] += mean_abs * n
        g["sumsq"] += (mean_abs**2 + std_abs**2) * n
        g["max_abs"] = max(g["max_abs"], max_abs)
        g["min_abs"] = min(g["min_abs"], min_abs)
        g["n_gt0"] += n_gt0
        g["n_gt_abs1e6"] += n_gt_abs1e6
        g["n_gt_rel1e6"] += n_gt_rel1e6
        g["n_gt_rel1e4"] += n_gt_rel1e4
        g["n_tensors"] += 1
        if mean_abs > best_mean["val"]:
            best_mean = {"key": k, "val": mean_abs}
        if max_abs > best_max["val"]:
            best_max = {"key": k, "val": max_abs}
        del diff, d, da
    global_mean = g["sum"] / g["numel"]
    global_std = math.sqrt(max(0.0, g["sumsq"] / g["numel"] - global_mean**2))
    # global median via 1e6-bin histogram over [min_abs, max_abs]
    lo, hi = g["min_abs"], g["max_abs"]
    median_abs = None
    method = "histogram"
    if hi <= lo:
        median_abs = hi
        method = "degenerate_single_value"
    else:
        hist = np.zeros(HIST_BINS, dtype=np.int64)
        for k in sorted(sd_new):
            d = (sd_new[k] - sd_old[k]).abs()
            hist += np.histogram(d.numpy(), bins=HIST_BINS, range=(lo, hi))[0]
            del d
        half = g["numel"] // 2
        cum = 0
        for i in range(HIST_BINS):
            cum += int(hist[i])
            if cum >= half:
                bin_w = (hi - lo) / HIST_BINS
                median_abs = lo + (i + 0.5) * bin_w
                break
    global_stats = {
        "numel": g["numel"],
        "n_tensors": g["n_tensors"],
        "mean_abs_delta": round(global_mean, 9),
        "median_abs_delta": round(median_abs, 9),
        "median_method": method,
        "median_histogram_bin_width": round((hi - lo) / HIST_BINS, 12)
        if hi > lo
        else 0.0,
        "std_abs_delta": round(global_std, 9),
        "max_abs_delta": round(g["max_abs"], 9),
        "min_abs_delta": round(g["min_abs"], 9),
        "fraction_changed_gt0": round(g["n_gt0"] / g["numel"], 9),
        "epsilon_abs_1e6": {
            "threshold": 1e-6,
            "n_changed": g["n_gt_abs1e6"],
            "fraction_changed": round(g["n_gt_abs1e6"] / g["numel"], 9),
        },
        "relative_to_ref_std_1e6": {
            "threshold": "1e-6 * std(tensor@1869)",
            "n_changed": g["n_gt_rel1e6"],
            "fraction_changed": round(g["n_gt_rel1e6"] / g["numel"], 9),
        },
        "relative_to_ref_std_1e4": {
            "threshold": "1e-4 * std(tensor@1869)",
            "n_changed": g["n_gt_rel1e4"],
            "fraction_changed": round(g["n_gt_rel1e4"] / g["numel"], 9),
        },
    }
    for k, rec in per_tensor.items():
        rec["fraction_changed_gt0"] = round(rec["n_changed_gt0"] / rec["numel"], 9)
        rec["fraction_gt_abs_1e6"] = round(rec["n_gt_abs_1e6"] / rec["numel"], 9)
        rec["fraction_gt_1e6_std"] = round(rec["n_gt_1e6_std"] / rec["numel"], 9)
        rec["fraction_gt_1e4_std"] = round(rec["n_gt_1e4_std"] / rec["numel"], 9)
    tracker.log(
        "DELTA", f"computed {g['n_tensors']} tensors in {time.perf_counter() - t0:.1f}s"
    )
    return {
        "global": global_stats,
        "largest_by_mean_abs_delta": {
            "key": best_mean["key"],
            "mean_abs_delta": round(best_mean["val"], 9),
        },
        "largest_by_max_abs_delta": {
            "key": best_max["key"],
            "max_abs_delta": round(best_max["val"], 9),
        },
        "per_tensor": per_tensor,
    }


# ---------------------------------------------------------------------------
# curve re-audit
# ---------------------------------------------------------------------------


def curve_reaudit(rows: list) -> dict:
    evals = [
        {"step": 623, "val_loss": 7.622762, "train_loss": 6.56257},
        {"step": 1869, "val_loss": 7.938125, "train_loss": 5.877017},
        {"step": 1919, "val_loss": 7.706575, "train_loss": 6.435823},
    ]
    legs = []
    overfitting_legs = []
    for i in range(len(evals) - 1):
        p0, p1 = evals[i], evals[i + 1]
        leg = {
            "from_step": p0["step"],
            "to_step": p1["step"],
            "steps": p1["step"] - p0["step"],
            "val_delta": round(p1["val_loss"] - p0["val_loss"], 6),
            "train_delta": round(p1["train_loss"] - p0["train_loss"], 6),
            "overfitting_signature": bool(
                p1["val_loss"] > p0["val_loss"] and p1["train_loss"] < p0["train_loss"]
            ),
        }
        legs.append(leg)
        if leg["overfitting_signature"]:
            overfitting_legs.append(leg)
    # mirror the provenance.py decision tree, then apply the explicit caveat
    divergent = False
    overfitting = bool(overfitting_legs)
    plateau = False
    under_training = False
    if overfitting:
        verdict = "OVERFITTING"
        basis = (
            f"leg 623->1869 fired the flag rule: val rose "
            f"{legs[0]['val_delta']:+.4f} (7.6228->7.9381) while train fell "
            f"{legs[0]['train_delta']:+.4f} (6.5626->5.8770). "
        )
        basis += (
            f"leg 1869->1919 REVERSED it: val fell {legs[1]['val_delta']:+.4f} "
            f"(7.9381->7.7066) while train ROSE {legs[1]['train_delta']:+.4f} "
            f"(5.8770->6.4358) - the opposite of an overfit signature. "
        )
    elif under_training:
        verdict = "UNDER_TRAINING"
        basis = "no flag fired; overall train loss still descending slowly"
    elif plateau:
        verdict = "PLATEAU"
        basis = "last segment slope ~0"
    elif divergent:
        verdict = "DIVERGENCE"
        basis = "last-50-step train slope > +0.05"
    else:
        verdict = "HEALTHY_TREND"
        basis = "no overfit/plateau/divergence flag fired"
    support = "PARTIALLY_SUPPORTED" if overfitting_legs else "NOT_ESTABLISHED"
    caveat = (
        "With only 3 eval points there is no per-step val series, so the curve "
        "cannot distinguish 'val recovered (1869->1919)' from 'val noise band "
        "~7.6-7.9 nats'. The 1869->1919 recovery (-0.2315) covered "
        f"{abs(legs[1]['val_delta']) / abs(legs[0]['val_delta']) * 100:.1f}% of the "
        "623->1869 rise (+0.3154), but 1919 (7.7066) still sits ABOVE 623 (7.6228) "
        "by +0.0838, so the decline was not fully reversed. Verdict is therefore "
        "PARTIALLY SUPPORTED at best."
    )
    return {
        "eval_points": [
            {
                "step": e["step"],
                "val_loss": e["val_loss"],
                "train_loss": e["train_loss"],
                "val_ppl": round(math.exp(e["val_loss"]), 4),
            }
            for e in evals
        ],
        "legs": legs,
        "overfitting_legs": overfitting_legs,
        "verdict": verdict,
        "support_level": support,
        "verdict_basis": basis,
        "caveat": caveat,
        "best_by_val": {
            "step": min(evals, key=lambda e: e["val_loss"])["step"],
            "val_loss": min(e["val_loss"] for e in evals),
            "val_ppl": round(math.exp(min(e["val_loss"] for e in evals)), 4),
            "1919_beats_623": evals[-1]["val_loss"] < evals[0]["val_loss"],
            "gap_1919_vs_best": round(
                evals[-1]["val_loss"] - min(e["val_loss"] for e in evals), 6
            ),
        },
        "best_by_train_loss": {
            "step": min(evals, key=lambda e: e["train_loss"])["step"],
            "train_loss": min(e["train_loss"] for e in evals),
        },
    }


# ---------------------------------------------------------------------------
# budget
# ---------------------------------------------------------------------------


def budget_analysis(rows: list) -> dict:
    t1 = next(r["tokens_seen"] for r in rows if r["step"] == 623)
    t2 = next(r["tokens_seen"] for r in rows if r["step"] == 1869)
    t3 = next(r["tokens_seen"] for r in rows if r["step"] == 1919)
    naive_sum = t1 + t2 + t3
    corrected = t2 + t3  # == t1 + (t2 - t1) + t3
    return {
        "corpus_train_tokens": CORPUS_TOKENS,
        "tokens_seen_by_invocation": {
            "invoke1_0_623": t1,
            "invoke2_623_1869": t2,
            "invoke3_1869_1919": t3,
        },
        "naive_sum_all_ledger_tokens_seen": naive_sum,
        "naive_sum_fraction": round(naive_sum / CORPUS_TOKENS, 9),
        "naive_sum_label": "WRONG for budget purposes - double-counts the resumed overlap (see hazard)",
        "corrected_cumulative_tokens": corrected,
        "corrected_cumulative_fraction": round(corrected / CORPUS_TOKENS, 9),
        "formula": "281,813 + (563,626 - 281,813) + 22,401 = 563,626 + 22,401 = 586,027",
        "extra_tokens_naive_vs_corrected": naive_sum - corrected,
        "corrected_learning_budget_fraction": f"{corrected / CORPUS_TOKENS * 100:.4f}%",
        "double_count_hazard": (
            "the ledger field name `tokens_seen` reads as a cumulative total, so naive "
            "tooling summing it across resumed rows over-counts: invoke-2's 563,626 "
            "counts 2 full passes over the same 623-block/281,813-token slice (one pass "
            "over data invoke-1 already processed), and summing rows treats invoke-1's "
            "281,813 as new data twice -> naive 867,840 overstates the corrected "
            "cumulative 586,027 by exactly 281,813 tokens (+48%)."
        ),
        "code_verified_semantics": (
            "train_comp001.py L588-595: tokens_seen is THIS process's own count "
            "(final_step = len(losses), local losses list; tokens_seen = "
            "divmod(final_step, per_epoch) full cycles x tokens_per_epoch + partial), "
            "NOT a chain-cumulative counter. L477-484 + L561: every invocation "
            "re-builds the SAME train_blocks slice (load_data(train_token_budget) from "
            "corpus head, seed 42) and indexes train_blocks[gstep % per_epoch], so all "
            "three invocations replay the same 281,813-token slice -> the literal "
            "unique-data floor is 281,813 tokens = 0.44% of the corpus, regardless of "
            "which cumulative convention is used."
        ),
    }


# ---------------------------------------------------------------------------
# stale export statement
# ---------------------------------------------------------------------------


def stale_export_note() -> dict:
    identity = json.loads(
        (ROOT / "logs" / "forensic" / "identity.json").read_text(encoding="utf-8")
    )
    cc = identity.get("export_cross_check", {})
    return {
        "true_latest_checkpoint": "checkpoint-1919",
        "hf_export_path": str(EXPORT),
        "hf_export_status": "STALE - not updated since step 1869",
        "evidence": (
            f"F1 identity.json export_cross_check: consistent_with_checkpoint={cc.get('consistent_with_checkpoint')} "
            f"against checkpoint-1869 (key_set_match={cc.get('key_set_match')}); the checkpoint-1919 weights "
            "differ from 1869 (this reconcile, delta section) while the on-disk export file is untouched."
        ),
        "export_modified": False,
        "do_not_modify": "NEVER overwrite models/comp001/100m-real/model.safetensors (canonical committed export).",
        "f4_plus_instruction": (
            "Later forensic eval phases must load checkpoint-1919/checkpoint.pt in memory, "
            "or write a NEW export directory (e.g. models/comp001/100m-real/checkpoint-1919-export/); "
            "never modify the canonical export."
        ),
    }


# ---------------------------------------------------------------------------
# report write
# ---------------------------------------------------------------------------

_REPORT_END = "END OF REPORT"


def append_report_section(report: dict) -> bool:
    txt = OUT_REPORT.read_text(encoding="utf-8")
    g = report["delta"]["global"]
    cr = report["curve"]
    b = report["budget"]
    e = report["stale_export"]
    s = "\n".join(
        [
            "=" * 78,
            "RECONCILIATION ADDENDUM (F3b) - third-run reconciliation, appended "
            + now_iso(),
            "previous sections above are untouched; new facts from raw files + checkpoint bytes.",
            "",
            "TRUE LATEST CHECKPOINT: checkpoint-1919  (HF export is STALE vs 1919:",
            "  model.safetensors is byte-identical to checkpoint-1869 per F1; NOT modified).",
            "",
            "DELTA 1869 -> 1919 (50 steps, new - old):",
            f"  tensors={g['numel']:,} params | mean_abs={g['mean_abs_delta']}  median_abs={g['median_abs_delta']} "
            f"std_abs={g['std_abs_delta']} max_abs={g['max_abs_delta']}",
            f"  fraction changed (abs>0)={g['fraction_changed_gt0']}  "
            f"abs>1e-6={g['epsilon_abs_1e6']['fraction_changed']}  "
            f">1e-4*std={g['relative_to_ref_std_1e4']['fraction_changed']}",
            f"  largest layer by mean |d|: {report['delta']['largest_by_mean_abs_delta']['key']} "
            f"({report['delta']['largest_by_mean_abs_delta']['mean_abs_delta']})",
            f"  largest layer by max |d|: {report['delta']['largest_by_max_abs_delta']['key']} "
            f"({report['delta']['largest_by_max_abs_delta']['max_abs_delta']})",
            "",
            "CURVE RE-AUDIT (all 3 eval points 623 / 1869 / 1919):",
            "  val loss: 7.6228 -> 7.9381 (+0.3154, overfit-signature leg) -> 7.7066 (-0.2315, recovery)",
            "  train loss at those steps: 6.5626 -> 5.8770 -> 6.4358 (final leg train ROSE while val FELL)",
            f"  verdict: {cr['verdict']} ({cr['support_level']})",
            f"  basis: {cr['verdict_basis']}",
            f"  caveat: {cr['caveat']}",
            "  BEST CHECKPOINT BY VAL LOSS: checkpoint-623 (7.6228, ppl 2044.2); "
            "1919 does NOT beat it (7.7066 > 7.6228). best by train loss: checkpoint-1869 (5.8770).",
            "",
            "LEARNING-BUDGET (corrected):",
            f"  naive sum of ledger tokens_seen = {b['naive_sum_all_ledger_tokens_seen']:,} "
            f"({b['naive_sum_fraction']:.6f} = {b['naive_sum_fraction'] * 100:.2f}%) - WRONG, double counts",
            f"  corrected cumulative = {b['corrected_cumulative_tokens']:,} tokens = "
            f"{b['corrected_cumulative_fraction']:.6f} = {b['corrected_cumulative_fraction'] * 100:.3f}% of "
            f"{b['corpus_train_tokens']:,} token corpus",
            f"  hazard: {b['double_count_hazard']}",
            f"  code-verified: {b['code_verified_semantics']}",
            "",
            f"STALE-EXPORT: {e['hf_export_status']}. {e['do_not_modify']}",
            f"  {e['f4_plus_instruction']}",
            "",
        ]
    )
    idx = txt.rfind(_REPORT_END)
    if idx == -1:
        OUT_REPORT.write_text(txt + "\n" + s, encoding="utf-8")
    else:
        sep = txt.rfind("=" * 78, 0, idx)
        if sep == -1:
            OUT_REPORT.write_text(txt + "\n" + s, encoding="utf-8")
        else:
            OUT_REPORT.write_text(txt[:sep] + s + txt[sep:], encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    torch.set_num_threads(6)
    tracker = Tracker()
    report: dict = {
        "generated_at": now_iso(),
        "sources": [
            str(LEDGER),
            str(CKPT_DIR),
            str(EXPORT),
            str(ROOT / "logs/forensic/identity.json"),
        ],
        "task": "F3b reconcile_third_run",
    }
    try:
        rows = read_ledger_rows()
        report["ledger_verified"] = rows

        sd1919, meta1919, sd1869, meta1869 = load_pair(tracker)
        report["checkpoints"] = {
            "new": {"subdir": "checkpoint-1919", "_meta": meta1919},
            "old": {"subdir": "checkpoint-1869", "_meta": meta1869},
        }
        # cheap cross-checks while both are in memory
        assert meta1919["step"] == 1919 and meta1869["step"] == 1869, (
            "checkpoint step mismatch"
        )
        assert (
            meta1919["losses_len"] == 50
            and abs(meta1919["losses_last"] - 6.435823) < 1e-4
        ), "ckpt-1919 losses"
        assert (
            meta1869["losses_len"] == 1246
            and abs(meta1869["losses_last"] - 5.877017) < 1e-4
        ), "ckpt-1869 losses"

        report["delta"] = compute_deltas(sd1919, sd1869, tracker)
        del sd1919, sd1869
        gc.collect()

        report["curve"] = curve_reaudit(rows)
        report["budget"] = budget_analysis(rows)
        report["stale_export"] = stale_export_note()

        append_report_section(report)
        report["verification"] = {
            "reconcile_json_written": True,
            "provenance_report_appended": True,
            "export_untouched": EXPORT.stat().st_size == 443_689_408,
            "rss_final_mb": rss_mb(),
        }
        OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")

        g = report["delta"]["global"]
        print("\n" + "=" * 70)
        print("F3b RECONCILE THIRD RUN - summary")
        print("=" * 70)
        print(
            f"  true latest checkpoint: checkpoint-1919 (HF export STALE vs 1919, untouched)"
        )
        print(
            f"  delta 1869->1919: mean|d|={g['mean_abs_delta']} median|d|={g['median_abs_delta']} "
            f"std|d|={g['std_abs_delta']} max|d|={g['max_abs_delta']}"
        )
        print(
            f"  fraction changed abs>0: {g['fraction_changed_gt0']:.6f} | abs>1e-6: "
            f"{g['epsilon_abs_1e6']['fraction_changed']:.6f} | >1e-4*std: "
            f"{g['relative_to_ref_std_1e4']['fraction_changed']:.6f}"
        )
        print(f"  largest layer: {report['delta']['largest_by_mean_abs_delta']['key']}")
        cr = report["curve"]
        print(
            f"  verdict: {cr['verdict']} ({cr['support_level']}) - best by val: step "
            f"{cr['best_by_val']['step']} ({cr['best_by_val']['val_loss']})"
        )
        b = report["budget"]
        print(
            f"  budget: corrected cumulative {b['corrected_cumulative_tokens']:,} / "
            f"{b['corpus_train_tokens']:,} = {b['corrected_cumulative_fraction'] * 100:.3f}% "
            f"(naive sum {b['naive_sum_all_ledger_tokens_seen']:,} = {b['naive_sum_fraction'] * 100:.2f}% is WRONG)"
        )
        print(
            f"  outputs: {OUT_JSON} (+ append to {OUT_REPORT}) | rss_final={rss_mb()} MB"
        )
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
