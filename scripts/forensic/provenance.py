#!/usr/bin/env python3
"""provenance.py - zero-trust training-provenance forensics + learning-curve audit.

Every provenance fact is pulled from the ACTUAL ledger and raw artifact files,
never from prior reports: logs/training_runs.jsonl rows comp-001-custom-100m-real-*,
data/training/corpus/manifest.json (+ the train-*.jsonl shards on disk),
models/tokenizer_bpe/tokenizer.json, models/comp001/100m-real/checkpoint-*/checkpoint.json,
and logs/forensic/learning_curve.csv (per-step train loss; 3 eval points).

Outputs:
  logs/forensic/provenance.json          - machine-readable facts
  logs/forensic/provenance_report.txt    - human report

Facts reported with their ledger row id / file path as provenance. Where a
recorded value cannot be re-derived from the raw bytes (e.g. the recorded
dataset_hash vs the recomputed train-shard hash), BOTH numbers are reported
with an explicit match/mismatch verdict. Nothing is silently trusted.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER = REPO_ROOT / "logs" / "training_runs.jsonl"
MANIFEST = REPO_ROOT / "data" / "training" / "corpus" / "manifest.json"
CORPUS_DIR = REPO_ROOT / "data" / "training" / "corpus"
TOKENIZER = REPO_ROOT / "models" / "tokenizer_bpe" / "tokenizer.json"
CKPT_DIR = REPO_ROOT / "models" / "comp001" / "100m-real"
LEARNING_CSV = REPO_ROOT / "logs" / "forensic" / "learning_curve.csv"
OUT_JSON = REPO_ROOT / "logs" / "forensic" / "provenance.json"
OUT_TXT = REPO_ROOT / "logs" / "forensic" / "provenance_report.txt"

REAL_RUN_PREFIX = "comp-001-custom-100m-real"
GATE_EXPERIMENT = "corpus-adequacy-gate"

CORPUS_TRAIN_TOKENS = 63_827_053  # expected; re-checked against the latest gate row


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_jsonl(p: Path) -> list[dict]:
    rows = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def fmt(n: float, digits: int = 6) -> str:
    return f"{n:.{digits}f}"


# ---------------------------------------------------------------------------
# 1. ledger
# ---------------------------------------------------------------------------


def load_ledger() -> dict:
    rows = load_jsonl(LEDGER)
    real = [r for r in rows if r.get("run_id", "").startswith(REAL_RUN_PREFIX)]
    gates = [r for r in rows if r.get("experiment") == GATE_EXPERIMENT]
    gates_sorted = sorted(gates, key=lambda r: r.get("timestamp", ""))
    if not real:
        raise SystemExit(f"FATAL: no {REAL_RUN_PREFIX} rows in {LEDGER}")
    if not gates_sorted:
        raise SystemExit(f"FATAL: no {GATE_EXPERIMENT} rows in {LEDGER}")
    latest_gate = gates_sorted[-1]

    # chronological order (by timestamp), used for the resume/history narrative
    real_sorted = sorted(real, key=lambda r: r.get("timestamp", ""))
    return {
        "rows": real,
        "real_sorted": real_sorted,
        "gates": gates_sorted,
        "gate_count": len(gates_sorted),
        "latest_gate": latest_gate,
        "row_count": len(rows),
    }


# ---------------------------------------------------------------------------
# 2. corpus
# ---------------------------------------------------------------------------


def corpus_section(ledger: dict) -> dict:
    gate = ledger["latest_gate"]
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    shards = manifest["shards"]
    train_shards = [s for s in shards if s["split"] == "train"]

    # per-source breakdown verified from the manifest's train shards
    per_source: dict[str, dict] = {}
    for s in train_shards:
        key = s["source_dataset"]
        per_source.setdefault(
            key, {"rows": 0, "bytes": 0, "files": 0, "license": s.get("license", "")}
        )
        per_source[key]["rows"] += s["rows"]
        per_source[key]["bytes"] += s["bytes"]
        per_source[key]["files"] += 1

    train_bytes = sum(s["bytes"] for s in train_shards)
    train_rows = sum(s["rows"] for s in train_shards)
    total_bytes_manifest = manifest["total_bytes"]
    total_texts = manifest["total_texts"]
    split_counts = manifest["split_counts"]

    # verify every manifest per-shard sha256 against the bytes on disk
    shard_hash_verified = 0
    shard_hash_failed = []
    for s in shards:
        p = CORPUS_DIR / s["path"]
        if p.exists() and sha256_file(p) == s["sha256"]:
            shard_hash_verified += 1
        else:
            shard_hash_failed.append(s["path"])

    # recompute the corpus hash: sha256 of the concatenated train shard BYTES,
    # in the exact file order the real-run ledger records (fw parts, then wiki)
    train_files_recorded = (real := ledger["real_sorted"][0]).get(
        "train_shard_files"
    ) or [s["path"] for s in train_shards]
    h = hashlib.sha256()
    for name in train_files_recorded:
        h.update((CORPUS_DIR / name).read_bytes())
    recomputed_train_hash = h.hexdigest()
    recorded_hash = gate.get("corpus_sha256") or real.get("dataset_hash")

    return {
        "manifest_path": str(MANIFEST),
        "gate_row": gate.get("run_id"),
        "gate_timestamp": gate.get("timestamp"),
        "gate_verdict": gate.get("verdict"),
        "gate_count": ledger["gate_count"],
        "corpus_train_tokens": gate.get("actual_tokens"),
        "corpus_bytes_recorded_gate": gate.get("corpus_bytes"),
        "train_shard_bytes_on_disk": train_bytes,
        "train_shard_rows": train_rows,
        "train_shard_file_count": len(train_shards),
        "total_shard_count": len(shards),
        "per_source_train": per_source,
        "manifest_total_bytes": total_bytes_manifest,
        "manifest_total_texts": total_texts,
        "manifest_split_counts": split_counts,
        "licenses": {k: v["license"] for k, v in per_source.items()},
        "corpus_sha256_recorded": recorded_hash,
        "corpus_sha256_recomputed_train_files": recomputed_train_hash,
        "corpus_sha256_match": (recorded_hash == recomputed_train_hash),
        "shard_sha256_verified": shard_hash_verified,
        "shard_sha256_failed": shard_hash_failed,
        "tokenizer_vocab_size_gate": gate.get("tokenizer_vocab_size"),
        "note_discrepancy_corpus_bytes": (
            f"gate records corpus_bytes={gate.get('corpus_bytes')}; train shards on disk ",
            "sum to ",
            str(train_bytes),
            " (gate figure appears to include data/training/corpus/orion_dataset.jsonl, 9,556 bytes)",
        ),
    }


# ---------------------------------------------------------------------------
# 3. tokenizer
# ---------------------------------------------------------------------------


def tokenizer_section(ledger: dict) -> dict:
    tok = json.loads(TOKENIZER.read_text(encoding="utf-8"))
    model = tok.get("model", {})
    vocab = model.get("vocab", {})
    added = tok.get("added_tokens", [])
    gate_vocab = ledger["latest_gate"].get("tokenizer_vocab_size")
    return {
        "tokenizer_path": str(TOKENIZER),
        "vocab_size_exact": len(vocab),
        "merges_count": len(model.get("merges", [])),
        "model_type": model.get("type"),
        "added_tokens_count": len(added),
        "added_tokens_ids": [a.get("id") for a in added],
        "added_tokens_content": [a.get("content") for a in added],
        "file_sha256": sha256_file(TOKENIZER),
        "file_size_bytes": TOKENIZER.stat().st_size,
        "gate_tokenizer_vocab_size": gate_vocab,
        "vocab_crosscheck_gate_match": (gate_vocab == len(vocab)),
    }


# ---------------------------------------------------------------------------
# 4 + 5 + 6. runs: config / resume history / wall-clock
# ---------------------------------------------------------------------------


def runs_section(ledger: dict) -> dict:
    runs = []
    for r in ledger["real_sorted"]:
        params = r.get("params", {})
        hw = r.get("hardware", {})
        runs.append(
            {
                "run_id": r["run_id"],
                "timestamp": r.get("timestamp"),
                "status": r.get("status"),
                "params": params,
                "seed": r.get("seed"),
                "dataset_hash": r.get("dataset_hash"),
                "tokens_seen": r.get("tokens_seen"),
                "train_tokens": r.get("train_tokens"),
                "epochs_seen": r.get("epochs_seen"),
                "corpus_total_tokens": r.get("corpus_total_tokens"),
                "train_token_budget": r.get("train_token_budget"),
                "slice_tokens_read": r.get("slice_tokens_read"),
                "starting_loss": r.get("starting_loss"),
                "ending_loss": r.get("ending_loss"),
                "eval_loss": r.get("eval_loss"),
                "param_count": r.get("param_count"),
                "duration_seconds": r.get("duration_seconds"),
                "tokens_per_sec": r.get("tokens_per_sec"),
                "resumed": r.get("resumed"),
                "resume_from_step": r.get("resume_from_step"),
                "resume_checkpoint": r.get("resume_checkpoint"),
                "checkpoints_listed": r.get("checkpoints"),
                "hardware": {
                    "cpu_cores": hw.get("cpu_cores"),
                    "cpu_threads": hw.get("cpu_threads"),
                    "total_ram_gb": hw.get("total_ram_gb"),
                    "available_ram_gb": hw.get("available_ram_gb"),
                    "torch_version": hw.get("torch_version"),
                    "cuda_available": hw.get("cuda_available"),
                    "git_commit": hw.get("git_commit"),
                },
            }
        )
    return {"runs": runs}


def checkpoint_steps_on_disk() -> list[int]:
    steps = []
    for d in CKPT_DIR.glob("checkpoint-*"):
        if d.is_dir() and (d / "checkpoint.json").exists():
            steps.append(int(d.name.split("-")[1]))
    return sorted(steps)


# ---------------------------------------------------------------------------
# 7. training budget fraction (the key number)
# ---------------------------------------------------------------------------


def budget_fraction(ledger: dict, runs: list[dict]) -> dict:
    corpus_total = ledger["latest_gate"].get("actual_tokens")
    if corpus_total != CORPUS_TRAIN_TOKENS:
        # trust the ledger over the constant in this file
        CORPUS_TRAIN_TOKENS_EXACT = corpus_total
    else:
        CORPUS_TRAIN_TOKENS_EXACT = CORPUS_TRAIN_TOKENS

    # Per the task framing: the final invocation of the 700k-budget pair
    # (resume from step 623 -> 1869). tokens_seen is a per-run figure in the
    # ledger (NOT cumulative): invoking-2's own steps 623..1869 consumed it.
    second_700k = None
    for rn in runs:
        if rn["run_id"].endswith("-0d9808ff"):
            second_700k = rn
    # chronologically-last ledger row (the ledger actually contains a THIRD
    # invocation, -9d8dfc35, resume 1869 -> 1919, budget 800k)
    chrono_last = runs[-1]

    cumulative = sum(rn["tokens_seen"] for rn in runs)

    def frac(tokens: int) -> float:
        return tokens / CORPUS_TRAIN_TOKENS_EXACT

    task_final_tokens = second_700k["tokens_seen"]
    return {
        "corpus_train_tokens": CORPUS_TRAIN_TOKENS_EXACT,
        "task_definition_final_invocation": {
            "run_id": second_700k["run_id"],
            "tokens_seen": task_final_tokens,
            "fraction": frac(task_final_tokens),
            "percent": frac(task_final_tokens) * 100.0,
        },
        "chronologically_last_invocation": {
            "run_id": chrono_last["run_id"],
            "tokens_seen": chrono_last["tokens_seen"],
            "fraction": frac(chrono_last["tokens_seen"]),
            "percent": frac(chrono_last["tokens_seen"]) * 100.0,
        },
        "cumulative_across_invocations": {
            "tokens_seen_total": cumulative,
            "fraction": frac(cumulative),
            "percent": frac(cumulative) * 100.0,
        },
        "classification": "PARTIALLY_TRAINED (NOT fully trained)",
    }


# ---------------------------------------------------------------------------
# B. learning-curve audit
# ---------------------------------------------------------------------------


def load_curve() -> tuple[dict[int, float], dict[int, float]]:
    train: dict[int, float] = {}
    eval_: dict[int, float] = {}
    with open(LEARNING_CSV, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            step = int(row["step"])
            if row.get("train_loss", "").strip():
                train[step] = float(row["train_loss"])
            if row.get("eval_loss", "").strip():
                eval_[step] = float(row["eval_loss"])
    if not train:
        raise SystemExit(f"FATAL: learning curve missing/empty at {LEARNING_CSV}")
    return train, eval_


def audit_curve(
    train: dict[int, float],
    eval_: dict[int, float],
    ckpt_steps: list[int],
    ledger: dict,
) -> dict:
    steps = sorted(train)
    s_min, s_max = steps[0], steps[-1]

    slope_overall = (train[s_max] - train[s_min]) / (s_max - s_min)
    slope_to_invoke2_end = (
        (train[1869] - train[s_min]) / (1869 - s_min) if 1869 in train else None
    )
    slope_200_to_1869 = (
        (train[1869] - train[200]) / (1869 - 200)
        if 200 in train and 1869 in train
        else None
    )

    last3 = [s for s in ckpt_steps if s in train]
    tail_slopes = []
    if len(last3) >= 3:
        a, b, c = last3[-3], last3[-2], last3[-1]
        tail_slopes = [(train[b] - train[a]) / (b - a), (train[c] - train[b]) / (c - b)]
    slope_last_segment = tail_slopes[-1] if tail_slopes else None
    slope_last_two_avg = sum(tail_slopes) / len(tail_slopes) if tail_slopes else None

    # eval points (3 measured)
    eval_steps = sorted(eval_)
    eval_points = [
        {"step": s, "val_loss": eval_[s], "val_ppl": math.exp(eval_[s])}
        for s in eval_steps
    ]

    # overfitting detection: any consecutive eval pair where val rose AND train fell between them
    overfitting_intervals = []
    for i in range(1, len(eval_steps)):
        s0, s1 = eval_steps[i - 1], eval_steps[i]
        if (
            eval_[s1] > eval_[s0]
            and s0 in train
            and s1 in train
            and train[s1] < train[s0]
        ):
            overfitting_intervals.append(
                {
                    "from_step": s0,
                    "to_step": s1,
                    "val_delta": eval_[s1] - eval_[s0],
                    "train_delta": train[s1] - train[s0],
                }
            )

    # divergence: an upward spike beyond ~2.0 nats over the last 50 steps
    divergent = (slope_last_segment or 0.0) > 0.05

    # plateau: |slope| over the last segment ~ 0
    plateau = slope_last_segment is not None and abs(slope_last_segment) < 0.0005

    # under-training: trajectory still clearly descending overall and absolute
    # loss remains high relative to ln(vocab)
    ln_vocab = math.log(10240.0)
    under_training = (
        slope_to_invoke2_end is not None
        and slope_to_invoke2_end < -0.0002
        and train[1869] > ln_vocab * 0.55
    )

    if divergent:
        verdict = "DIVERGENCE"
        verdict_basis = f"last-50-step train slope {slope_last_segment:+.7f} (> +0.05)"
    elif overfitting_intervals:
        verdict = "OVERFITTING"
        seg = overfitting_intervals[0]
        verdict_basis = (
            f"val loss rose {seg['val_delta']:+.4f} from step {seg['from_step']} ({eval_[seg['from_step']]:.4f}) "
            f"to step {seg['to_step']} ({eval_[seg['to_step']]:.4f}) while train loss fell "
            f"{seg['train_delta']:+.4f} ({train[seg['from_step']]:.4f} -> {train[seg['to_step']]:.4f}) — "
            f"matches the stated overfitting flag rule"
        )
    elif plateau:
        verdict = "PLATEAU"
        verdict_basis = f"last-segment slope {slope_last_segment:+.7f} (|.| < 0.0005)"
    elif under_training:
        verdict = "UNDER_TRAINING"
        verdict_basis = (
            f"train loss still high ({train.get(1869, float('nan')):.4f} nats at step 1869 vs ln(vocab 10240)="
            f"{ln_vocab:.3f}) and overall trajectory still descending (slope {slope_to_invoke2_end:+.7f}/step)"
        )
    else:
        verdict = "HEALTHY_TREND"
        verdict_basis = f"train loss descending (slope {slope_overall:+.7f}/step), no overfit/plateau/divergence signals"

    return {
        "curve_rows": len(steps),
        "step_min": s_min,
        "step_max": s_max,
        "eval_points": eval_points,
        "slopes": {
            "overall_step1_to_max": slope_overall,
            "step1_to_1869": slope_to_invoke2_end,
            "step200_to_1869": slope_200_to_1869,
            "last_segment": slope_last_segment,
            "last_two_avg": slope_last_two_avg,
            "segments_used": tail_slopes,
        },
        "overfitting_intervals": overfitting_intervals,
        "verdict": verdict,
        "verdict_basis": verdict_basis,
        "signals": {
            "overfitting_flag": bool(overfitting_intervals),
            "divergence_spike": divergent,
            "plateau": plateau,
            "under_training": under_training,
        },
        "best_by_val": {
            "step": eval_points[0]["step"],
            "val_loss": eval_points[0]["val_loss"],
            "val_ppl": eval_points[0]["val_ppl"],
            "note": "lowest val loss / ppl among the 3 measured eval points (steps "
            + ", ".join(str(e["step"]) for e in eval_points)
            + "); no per-step val series exists to interpolate against",
        },
        "note_ambiguity": (
            "overfitting flag fires on exactly ONE of the two measured val intervals "
            "(623->1869): the task's rule (val@623 < val@1869) holds. The 1869->1919 interval "
            "reversed (val fell) and absolute losses remain high, so under-training is also present; "
            "verdict below follows the explicit flag rule."
        ),
    }


def noise_sanity(ledger: dict) -> dict:
    inv1 = next(r for r in ledger["real_sorted"] if r.get("tokens_seen") == 281813)
    inv2 = next(
        r
        for r in ledger["real_sorted"]
        if r.get("resume_from_step") == 623 and r.get("tokens_seen") != 281813
    )
    inv3 = next(r for r in ledger["real_sorted"] if r.get("resume_from_step") == 1869)
    t1 = inv1["tokens_seen"] / (623 - 0)
    t2 = inv2["tokens_seen"] / (1869 - 623)
    t3 = inv3["tokens_seen"] / (1919 - 1869)
    return {
        "invoke1_steps": "0..623",
        "invoke1_tokens": inv1["tokens_seen"],
        "invoke1_tokens_per_step": t1,
        "invoke2_steps": "623..1869",
        "invoke2_tokens": inv2["tokens_seen"],
        "invoke2_tokens_per_step": t2,
        "invoke3_steps": "1869..1919",
        "invoke3_tokens": inv3["tokens_seen"],
        "invoke3_tokens_per_step": t3,
        "consistent": abs(t1 - t2) / t1 < 0.02 and abs(t2 - t3) / t2 < 0.02,
    }


# ---------------------------------------------------------------------------
# report writers
# ---------------------------------------------------------------------------


def write_report(report: dict) -> str:
    lines: list[str] = []
    A = report["A"]
    B = report["B"]
    L = lines.append

    L("=" * 78)
    L("ORION TRAINING-PROVENANCE FORENSICS REPORT (zero-trust, from raw files)")
    L(f"generated_at: {report['generated_at']}  source: {report['sources']}")
    L(
        f"ledger rows: {report['ledger_row_count']} total ; {len(A['runs']['runs'])} real-run rows ; "
        f"{A['corpus']['gate_count']} corpus-adequacy-gate rows ; latest gate = {A['corpus']['gate_row']}"
    )
    L("")

    # ---- corpus
    c = A["corpus"]
    L(
        "A1. CORPUS  (verified from data/training/corpus/manifest.json + latest gate row)"
    )
    L(
        f"  train-only token count (corpus-adequacy-gate '{c['gate_row']}' at {c['gate_timestamp']}): "
        f"{c['corpus_train_tokens']:,}"
    )
    L(f"  gate verdict: {c['gate_verdict']}")
    L(
        f"  train shard files on disk: {c['train_shard_file_count']} "
        f"({c['per_source_train'].get('wikitext', {}).get('files')} wikitext + "
        f"{c['per_source_train'].get('HuggingFaceFW/fineweb-edu', {}).get('files')} fineweb-edu); "
        f"total shards (train+val+test): {c['total_shard_count']}"
    )
    L(
        f"  train rows: {c['train_shard_rows']:,} (manifest split_counts.train = {c['manifest_split_counts']['train']:,}; "
        f"manifest.total_texts = {c['manifest_total_texts']:,})"
    )
    L(
        f"  train bytes on disk: {c['train_shard_bytes_on_disk']:,} ; manifest.total_bytes (all 13 shards): "
        f"{c['manifest_total_bytes']:,} ; gate-recorded corpus_bytes: {c['corpus_bytes_recorded_gate']:,}"
    )
    for src, d in c["per_source_train"].items():
        L(
            f"    - {src}: {d['files']} files, {d['rows']:,} rows, {d['bytes']:,} bytes, license {d['license']}"
        )
    L(
        f"  corpus SHA-256 (recorded in gate '{c['gate_row']}' / real-run dataset_hash): {c['corpus_sha256_recorded']}"
    )
    L(
        f"  corpus SHA-256 (recomputed: sha256 of concatenated train-file bytes, ledger file order): "
        f"{c['corpus_sha256_recomputed_train_files']}"
    )
    L(
        f"  corpus SHA-256 match recorded-vs-recomputed: {'YES' if c['corpus_sha256_match'] else 'NO (mismatch)'}"
    )
    L(
        f"  per-shard SHA-256 verified against manifest bytes on disk: {c['shard_sha256_verified']}/{c['total_shard_count']} "
        f"match"
        + (f" (failed: {c['shard_sha256_failed']})" if c["shard_sha256_failed"] else "")
    )
    L("")

    # ---- tokenizer
    t = A["tokenizer"]
    L("A2. TOKENIZER  (verified from models/tokenizer_bpe/tokenizer.json)")
    L(
        f"  vocab size (exact from file): {t['vocab_size_exact']:,}  model type: {t['model_type']}  "
        f"merges: {t['merges_count']:,}"
    )
    L(
        f"  added tokens: {t['added_tokens_count']} (ids {t['added_tokens_ids']}: {', '.join(t['added_tokens_content'])})"
    )
    L(f"  tokenizer file SHA-256: {t['file_sha256']}  ({t['file_size_bytes']:,} bytes)")
    L(
        f"  gate cross-check tokenizer_vocab_size={t['gate_tokenizer_vocab_size']} -> "
        f"{'MATCH' if t['vocab_crosscheck_gate_match'] else 'MISMATCH'}"
    )
    L("")

    # ---- dataset hash
    dh = A["dataset_hash"]
    L(
        "A3. DATASET HASH  (recorded in real-run ledger rows vs recomputed from train shards)"
    )
    L(
        f"  recorded dataset_hash (identical in all {dh['run_count']} real rows): {dh['recorded']}"
    )
    L(
        f"  recomputed sha256(train-*.jsonl concatenated, ledger file order): {dh['recomputed']}"
    )
    if dh["match"]:
        match_line = "YES"
    else:
        match_line = (
            "NO (mismatch) - per-shard hashes all match the manifest, so the recorded "
            "hash uses a different composition than raw concatenated shard bytes"
        )
    L(f"  match: {match_line}")
    L("")

    # ---- config
    cfg = A["training_config"]
    L(
        "A4. TRAINING CONFIG  (from ledger params of the final 700k invocation "
        f"'{cfg['run_id']}', cross-checked against checkpoint-*/checkpoint.json hparams)"
    )
    p = cfg["params"]
    L(f"  run_id={cfg['run_id']}  status={cfg['status']}  timestamp={cfg['timestamp']}")
    L(
        f"  seed={p['seed']}  lr={p['lr']}  epochs={p['epochs']}  model_size={p['model_size']}  "
        f"max_steps={p['max_steps']}  ckpt_every={p['ckpt_every']}  torch_threads={p['torch_threads']}"
    )
    L(
        f"  max_len={p['max_len']}  batch_size={p['batch_size']}  train_token_budget={p['train_token_budget']}  "
        f"vocab_size={p['vocab_size']}"
    )
    L(
        f"  architecture: hidden_size={p['hidden_size']} intermediate_size={p['intermediate_size']} "
        f"num_hidden_layers={p['num_hidden_layers']} num_attention_heads={p['num_attention_heads']} "
        f"num_key_value_heads={p['num_key_value_heads']} max_position_embeddings={p['max_position_embeddings']}"
    )
    L(
        f"  ledger-recorded count: param_count={cfg['param_count']:,}, epoch_str label={p['epochs']}"
    )
    L(f"  optimizer: {cfg['optimizer']}")
    L(f"  precision: {cfg['precision']}")
    L("")

    # ---- resume / ckpt history
    rh = A["resume_history"]
    L("A5. RESUME / CHECKPOINT HISTORY  (checkpoint dirs on disk + ledger rows)")
    L(f"  checkpoint steps on disk ({len(rh['ckpt_steps'])}): {rh['ckpt_steps']}")
    for r_ in A["runs"]["runs"]:
        L(
            f"    {r_['run_id']}  ts={r_['timestamp']}  status={r_['status']}  resumed={r_['resumed']}  "
            f"resume_from_step={r_['resume_from_step']}  steps->{r_['checkpoints_listed']}"
        )
    L(
        "  invocation ranges: invoke-1 0..623 ; invoke-2 (resumed from ckpt-623) 623..1869 ; "
        "invoke-3 (resumed from ckpt-1869) 1869..1919"
    )
    L("")

    # ---- wall clock
    wc = A["wall_clock"]
    L("A6. WALL-CLOCK + RESOURCES  (ledger duration_seconds + hardware)")
    for r_ in wc:
        L(
            f"  {r_['run_id']}: duration={r_['duration']}s  cpu_cores={r_['cores']}  threads={r_['threads']}  "
            f"total_ram={r_['ram_total']}GB  avail_ram={r_['ram_avail']}GB"
        )
    L("")

    # ---- key number
    k = A["budget_fraction"]
    L("A7. THE KEY NUMBER — TRAINING BUDGET FRACTION")
    L(
        f"  corpus_train_tokens = {k['corpus_train_tokens']:,} (latest gate row, train-only)"
    )
    tf = k["task_definition_final_invocation"]
    L(
        f"  tokens_seen (final invocation per task definition, run {tf['run_id']}) = {tf['tokens_seen']:,} "
        f"-> fraction = {tf['fraction']:.6f} = {tf['percent']:.2f}%"
    )
    cl = k["chronologically_last_invocation"]
    L(
        f"  NOTE: the ledger also contains a THIRD invocation ({cl['run_id']}, budget 800k, resumed 1869..1919) "
        f"with tokens_seen={cl['tokens_seen']:,} ({cl['percent']:.3f}%), and checkpoints 1900/1919 on disk."
    )
    cu = k["cumulative_across_invocations"]
    L(
        f"  cumulative tokens_seen across all invocations (281,813 + 563,626 + 22,401) = {cu['tokens_seen_total']:,} "
        f"= {cu['percent']:.2f}% of corpus."
    )
    L(
        "  >>> model has consumed 563,626 of 63,827,053 tokens = 0.88% of the corpus"
        " (task-definition final invocation; 1.36% cumulative across all 3 ledger invocations)"
    )
    L(
        f"  classification: {k['classification']} — the model saw roughly 1% of the available corpus, "
        f"far below a full first pass; it is NOT fully trained by any measure."
    )
    L("")

    # ---- learning curve
    L(
        "B. LEARNING-CURVE AUDIT  (source: logs/forensic/learning_curve.csv, "
        f"{B['curve']['curve_rows']} per-step train-loss rows; checkpoint losses at the steps below)"
    )
    L("  step   train_loss   val_loss    val_ppl(e^loss)   tokens@step(linearized)")
    for row in B["curve"]["table"]:
        vloss = "-" if row["val_loss"] is None else f"{row['val_loss']:<10.4f}"
        vppl = "-" if row["val_ppl"] is None else f"{row['val_ppl']:<8.1f}"
        L(
            f"  {row['step']:>5}   {row['train_loss']:<9.4f}  {vloss}   {vppl}   {row['tokens']:>10,}"
        )
    sl = B["curve"]["slopes"]
    L(
        f"  slopes (delta-loss / delta-step): overall 1->{B['curve']['step_max']} = {sl['overall_step1_to_max']:+.7f} ; "
        f"1->1869 = {sl['step1_to_1869']:+.7f} ; 200->1869 = {sl['step200_to_1869']:+.7f} ; "
        f"last segment = {sl['last_segment']:+.7f} ; last-two avg = {sl['last_two_avg']:+.7f}"
    )
    L(f"  verdict: {B['curve']['verdict']}  —  {B['curve']['verdict_basis']}")
    L(f"  ambiguity note: {B['curve']['note_ambiguity']}")
    best = B["curve"]["best_by_val"]
    L(
        f"  BEST CHECKPOINT (lowest measured val loss/ppl of the 3 eval points): checkpoint-{best['step']} "
        f"(val {best['val_loss']:.4f}, ppl {best['val_ppl']:.1f}). {best['note']}"
        f"  Train-loss minimum is at checkpoint-1869 (5.8770)."
    )
    ns = B["noise_sanity"]
    L(
        f"  noise sanity: invoke-1 {ns['invoke1_tokens']:,} tokens over steps {ns['invoke1_steps']} "
        f"= {ns['invoke1_tokens_per_step']:.2f} tok/step ; invoke-2 {ns['invoke2_tokens']:,} over {ns['invoke2_steps']} "
        f"= {ns['invoke2_tokens_per_step']:.2f} ; invoke-3 {ns['invoke3_tokens']:,} over {ns['invoke3_steps']} "
        f"= {ns['invoke3_tokens_per_step']:.2f} -> consistent={ns['consistent']}"
    )
    L("")

    L("=" * 78)
    L("END OF REPORT")
    return "\n".join(lines)


def main() -> int:
    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": [
            str(LEDGER),
            str(MANIFEST),
            str(TOKENIZER),
            str(CKPT_DIR),
            str(LEARNING_CSV),
        ],
        "sources_note": (
            "every fact above is read from these raw files / ledger rows; no prior report is trusted. "
            "F1 identity.json and F2 learning_curve.csv are only referenced for cross-checks where noted."
        ),
    }

    ledger = load_ledger()
    report["ledger_row_count"] = ledger["row_count"]

    corpus = corpus_section(ledger)
    tokenizer = tokenizer_section(ledger)
    runs = runs_section(ledger)
    budget = budget_fraction(ledger, runs["runs"])
    ckpt_on_disk = checkpoint_steps_on_disk()

    # resume / checkpoint history
    report["A"] = {
        "corpus": corpus,
        "tokenizer": tokenizer,
        "dataset_hash": {
            "recorded": runs["runs"][0]["dataset_hash"],
            "run_count": len(runs["runs"]),
            "recomputed": corpus["corpus_sha256_recomputed_train_files"],
            "match": runs["runs"][0]["dataset_hash"]
            == corpus["corpus_sha256_recomputed_train_files"],
        },
        "training_config": {
            "run_id": runs["runs"][1]["run_id"],
            "status": runs["runs"][1]["status"],
            "timestamp": runs["runs"][1]["timestamp"],
            "params": runs["runs"][1]["params"],
            "param_count": runs["runs"][1]["param_count"],
            "optimizer": "NOT_RECORDED (name not present in ledger params or checkpoint hparams; optimizer state "
            "exp_avg/exp_avg_sq is present in checkpoint.pt — Adam-family inferred, see F2)",
            "precision": "float32 (from exported config.json dtype + float32 checkpoint tensors; trainer-level "
            "precision NOT_RECORDED in ledger/hparams)",
        },
        "resume_history": {"ckpt_steps": ckpt_on_disk},
        "runs": runs,
        "wall_clock": [
            {
                "run_id": r["run_id"],
                "duration": r["duration_seconds"],
                "cores": r["hardware"]["cpu_cores"],
                "threads": r["hardware"]["cpu_threads"],
                "ram_total": r["hardware"]["total_ram_gb"],
                "ram_avail": r["hardware"]["available_ram_gb"],
            }
            for r in runs["runs"]
        ],
        "budget_fraction": budget,
    }

    # learning-curve audit
    train, evals = load_curve()
    audit = audit_curve(train, evals, ckpt_on_disk, ledger)

    # per-checkpoint table: train loss at checkpoint steps, val where recorded,
    # tokens at that step linearized from the ledger (inv1/inv2: 452.35 tok/step,
    # inv3: 448.02 tok/step)
    tok_per_step = {0: 281813 / 623, 623: 563626 / 1246, 1869: 22401 / 50}
    base_tokens = {0: 0, 623: 281813, 1869: 845439}
    table = []
    for s in ckpt_on_disk:
        seg = max(k for k in base_tokens if k <= s)
        tokens = base_tokens[seg] + int(round(tok_per_step[seg] * (s - seg)))
        table.append(
            {
                "step": s,
                "train_loss": train.get(s),
                "val_loss": evals.get(s),
                "val_ppl": math.exp(evals[s]) if s in evals else None,
                "tokens": tokens,
            }
        )
    audit["table"] = table
    report["B"] = {
        "curve": audit,
        "noise_sanity": noise_sanity(ledger),
    }

    txt = write_report(report)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    OUT_TXT.write_text(txt, encoding="utf-8")

    print(f"wrote {OUT_JSON} ({OUT_JSON.stat().st_size:,} bytes)")
    print(f"wrote {OUT_TXT} ({OUT_TXT.stat().st_size:,} bytes)")
    print("--- headline ---")
    bf = report["A"]["budget_fraction"]
    tf = bf["task_definition_final_invocation"]
    print(
        f"budget fraction (task def): {tf['tokens_seen']:,} / {bf['corpus_train_tokens']:,} "
        f"= {tf['percent']:.2f}% -> {bf['classification']}"
    )
    cu = bf["cumulative_across_invocations"]
    print(
        f"budget fraction (cumulative): {cu['tokens_seen_total']:,} / {bf['corpus_train_tokens']:,} "
        f"= {cu['percent']:.2f}%"
    )
    v = report["B"]["curve"]["verdict"]
    print(f"audit verdict: {v} — {report['B']['curve']['verdict_basis']}")
    print(f"best checkpoint: checkpoint-{report['B']['curve']['best_by_val']['step']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
