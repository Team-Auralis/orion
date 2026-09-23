#!/usr/bin/env python3
"""ORION-COMP-002 evaluation suite (Task T5): held-out generalization + reasoning benchmark.

Three measurements on the COMP-001 100m-real checkpoint (HF safetensors, fp32 CPU):

(a) Held-out generalization: every val-* and test-* corpus shard under
    data/training/corpus/ is BPE-tokenized (models/tokenizer_bpe), packed with the
    SAME methodology the training harness used (tokenize_samples + pack_sequences,
    max_len 512, mask_boundaries), and evaluated with the trained model. Per-shard
    token-weighted loss/ppl plus a combined (sum-nll / sum-tokens) number per split.
    val and test ppl are reported SEPARATELY (test is the true held-out; val was used
    for the in-training eval loss).

(b) Reasoning benchmark: HellaSwag (Rowan/hellaswag, validation split; streams cleanly
    from the HF hub). Fallback: ARC-Easy (allenai/ai2_arc, ARC-Easy, validation) when
    HellaSwag fails to load. A fixed, reproducible N-item slice is used: seeded (42)
    shuffle of the full dataset order, take the first N items, then drop+refill on any
    contamination hit. Scoring: for each of the 4 candidate continuations compute the
    model's mean log-prob of the continuation tokens conditioned on the context, pick
    argmax -> top-1 accuracy vs the gold label. Random baseline = 0.25 for HellaSwag
    (fixed 4 choices) / mean(1/n_choices) for ARC-Easy.

(c) Contamination isolation: for every eval item, check context AND gold answer with
    corpus_builder.check_leak() against ALL corpus shards (train/val/test). Hit items
    are dropped and the slice refilled; the hit/drop count is REQUIRED output (0 expected).

Raw per-item output is appended to logs/comp002_eval_raw.jsonl (append-only, keep raw).

CLI:
    python scripts/evaluation/comp002_eval.py --model models/comp001/100m-real/
        [--benchmark hellaswag] [--n 100] [--workers 4]
"""

import argparse
import json
import math
import os
import random
import shutil
import sys
import time
import uuid
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "training"))

import torch  # noqa: E402
from transformers import Qwen2ForCausalLM  # noqa: E402

import orion_corpus  # noqa: E402
import corpus_builder  # noqa: E402
from orion_runner.loader import pack_sequences, tokenize_samples  # noqa: E402

MAX_LEN = 512
EVAL_BATCH = 4  # blocks are all padded to 512; batch 4 keeps RSS ~620 MB on this box
SLICE_SEED = 42
DEFAULT_N = 100
RAW_LOG = REPO_ROOT / "logs" / "comp002_eval_raw.jsonl"
MANIFEST_PATH = orion_corpus.CORPUS_DIR / "manifest.json"

N_CHOICES = 4  # HellaSwag / ARC-Easy are 4-choice; random baseline reported per dataset


def _hf_cache_mb() -> float:
    root = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    if not root.is_dir():
        return 0.0
    n = 0
    for p in root.rglob("*"):
        try:
            if p.is_file():
                n += p.stat().st_size
        except OSError:
            pass
    return n / 1024**2


def _free_gb(path) -> float:
    try:
        return shutil.disk_usage(path).free / 1024**3
    except OSError:
        return float("nan")


def disk_report(label: str) -> dict:
    return {
        "label": label,
        "repo_drive_free_gb": round(_free_gb(REPO_ROOT), 2),
        "cache_drive_free_gb": round(_free_gb(Path.home() / ".cache"), 2),
        "hf_cache_mb": round(_hf_cache_mb(), 1),
    }


# --- (a) held-out generalization --------------------------------------------


def eval_split(model, tokenizer, split: str) -> dict:
    """Per-shard + combined token-weighted CE loss/ppl for one split (val|test)."""
    files = sorted(
        p for p in orion_corpus.shard_files() if p.name.startswith(split + "-")
    )
    if not files:
        raise SystemExit(f"[EVAL] no {split}-* shards under {orion_corpus.CORPUS_DIR}")
    shards = []
    total_nll, total_n, total_attn, total_blocks = 0.0, 0, 0, 0
    for path in files:
        rows = orion_corpus.load_samples([path])
        blocks = pack_sequences(
            tokenize_samples(
                rows, tokenizer, orion_corpus.row_text, max_len=MAX_LEN, truncation=True
            ),
            max_len=MAX_LEN,
            pad_id=orion_corpus.PAD_ID,
            seed=42,
            mask_boundaries=True,
            pad_to_max=True,
        )
        sh_nll, sh_n = 0.0, 0
        with torch.no_grad():
            for i in range(0, len(blocks), EVAL_BATCH):
                b = blocks[i : i + EVAL_BATCH]
                ids = torch.tensor([x["input_ids"] for x in b], dtype=torch.long)
                lbl = torch.tensor([x["labels"] for x in b], dtype=torch.long)
                out = model(input_ids=ids, labels=lbl)
                n_lbl = int((lbl != -100).sum().item())
                sh_nll += float(out.loss.item()) * n_lbl
                sh_n += n_lbl
        attn = sum(
            sum(b["attention_mask"]) for b in blocks
        )  # raw token count (incl. boundary)
        loss = sh_nll / max(sh_n, 1)
        shards.append(
            {
                "shard": path.name,
                "rows": len(rows),
                "blocks": len(blocks),
                "attention_tokens": attn,
                "loss_tokens": sh_n,
                "loss": loss,
                "ppl": math.exp(loss),
            }
        )
        total_nll += sh_nll
        total_n += sh_n
        total_attn += attn
        total_blocks += len(blocks)
        print(
            f"  [{split}] {path.name}: rows={len(rows)} blocks={len(blocks)} "
            f"loss_tokens={sh_n:,} loss={loss:.4f} ppl={math.exp(loss):,.1f}"
        )
    loss = total_nll / max(total_n, 1)
    combined = {
        "split": split,
        "shards": len(files),
        "blocks": total_blocks,
        "attention_tokens": total_attn,
        "loss_tokens": total_n,
        "loss": loss,
        "ppl": math.exp(loss),
    }
    print(
        f"[HELDOUT] {split}: tokens={total_attn:,} loss_tokens={total_n:,} "
        f"loss={loss:.4f} ppl={math.exp(loss):,.1f}"
    )
    return {"combined": combined, "shards": shards}


# --- (b) benchmark load + slice --------------------------------------------


def load_ds_hellaswag():
    from datasets import load_dataset

    ds = load_dataset("Rowan/hellaswag", split="validation")
    n_choices_hint = set()
    for k in range(0, min(len(ds), 500), 7):
        n_choices_hint.add(len(ds[k]["endings"]))
    assert n_choices_hint == {N_CHOICES}, (
        f"unexpected hellaswag endings {n_choices_hint}"
    )

    def to_item(ex):
        return {
            "ctx": ex["ctx"],
            "endings": list(ex["endings"]),
            "label": int(ex["label"]),
        }

    return ds, to_item, "hellaswag", "Rowan/hellaswag", 0.25


def load_ds_arc():
    from datasets import load_dataset

    ds = load_dataset("allenai/ai2_arc", "ARC-Easy", split="validation")

    def to_item(ex):
        ch = ex["choices"]
        return {
            "ctx": "QUESTION: " + ex["question"] + "\nANSWER:",
            "endings": [str(t) for t in ch["text"]],
            "label": int(ch["label"].index(ex["answerKey"])),
        }

    return ds, to_item, "arc-easy", "allenai/ai2_arc (ARC-Easy)", None


def load_benchmark(benchmark: str, n: int, seed: int) -> dict:
    """Load the requested benchmark (hellaswag default, ARC fallback on failure)."""
    if benchmark == "arc":
        ds, to_item, name, source, fixed_base = load_ds_arc()
    else:
        try:
            ds, to_item, name, source, fixed_base = load_ds_hellaswag()
        except Exception as e:  # noqa: BLE001 - required fallback to ARC-Easy
            print(
                f"[DATASET] hellaswag load failed ({type(e).__name__}: {str(e)[:160]})"
            )
            ds, to_item, name, source, fixed_base = load_ds_arc()

    rng = random.Random(seed)
    order = list(range(len(ds)))
    rng.shuffle(order)
    return {
        "ds": ds,
        "to_item": to_item,
        "name": name,
        "source": source,
        "order": order,
        "fixed_baseline": fixed_base,
    }


# --- (c) contamination screening (ProcessPool: check_leak is a full corpus scan) --


def _leak_probe(job) -> dict:
    """One worker call: check_leak of one eval string against the corpus manifest."""
    manifest, idx, kind, text = job
    hits = corpus_builder.check_leak(manifest, text)
    return {
        "idx": idx,
        "kind": kind,
        "hits": len(hits),
        "splits": sorted({str(h["shard"]).split("-")[0] for h in hits}),
    }


def screen_items(manifest, ds, to_item, order, n, workers=4) -> dict:
    """First-N-clean slice: seeded order, contamination screen, drop + refill."""
    final, leaked = [], []
    rest = list(order)
    meta = {"checked_strings": 0, "checked_items": 0}

    def probe(jobs):
        out = []
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for r in ex.map(_leak_probe, jobs):
                out.append(r)
        return out

    while len(final) < n and rest:
        take = rest[: max(8, n)]
        rest = rest[max(8, n) :]
        items = {i: to_item(ds[i]) for i in take}
        jobs = []
        for i in take:
            jobs.append((manifest, i, "context", items[i]["ctx"]))
            jobs.append((manifest, i, "gold", items[i]["endings"][items[i]["label"]]))
        meta["checked_strings"] += len(jobs)
        meta["checked_items"] += len(take)
        res = probe(jobs)
        by_item = {}
        for r in res:
            by_item.setdefault(r["idx"], []).append(r)
        for i in take:
            item_hits = [r for r in by_item[i] if r["hits"] > 0]
            if item_hits:
                leaked.append({"idx": i, "kinds": [r["kind"] for r in item_hits]})
            else:
                if len(final) < n:
                    final.append((i, items[i]))
        if len(leaked) > n * 4:  # safety: pathological corpus, stop looping
            break

    if leaked:
        print(
            f"[CONTAM] {len(leaked)} leaked item(s) dropped and refilled: "
            f"{[l['idx'] for l in leaked]}"
        )
    return {"items": final, "leaked": leaked, "meta": meta}


# --- benchmark scoring ------------------------------------------------------


def score_candidates(model, tokenizer, ctx: str, endings: list) -> list:
    """Mean log-prob of each candidate's continuation tokens conditioned on ctx."""
    ctx_ids = tokenizer.encode(ctx).ids
    scores = []
    for cand in endings:
        cand_ids = tokenizer.encode(" " + cand).ids
        if not cand_ids:
            scores.append(float("-inf"))
            continue
        budget = MAX_LEN - 1
        cand_ids = cand_ids[: budget - min(len(ctx_ids), budget - 1) - 1]
        if len(ctx_ids) + len(cand_ids) > budget:
            keep = budget - len(cand_ids)
            ctx_use = ctx_ids[-max(keep, 1) :]
        else:
            ctx_use = ctx_ids
        full = ctx_use + cand_ids
        cand_start = len(ctx_use)
        if len(full) < 2 or cand_start < 1:
            scores.append(float("-inf"))
            continue
        with torch.no_grad():
            logits = model(input_ids=torch.tensor([full], dtype=torch.long)).logits[0]
        logp = torch.log_softmax(logits[:-1].float(), dim=-1)
        targets = torch.as_tensor(full[1:], dtype=torch.long)
        tok_logp = logp[
            torch.arange(len(full) - 1), targets
        ]  # logp[t] = p(tok t+1 | past)
        scores.append(float(tok_logp[cand_start - 1 :].mean().item()))
    return scores


def run_benchmark(model, tokenizer, bench: dict, items, raw_rows: list) -> dict:
    correct = 0
    per_item = []
    for rank, (ds_idx, it) in enumerate(items):
        scores = score_candidates(model, tokenizer, it["ctx"], it["endings"])
        pred = int(max(range(len(scores)), key=lambda k: scores[k]))
        ok = pred == it["label"]
        correct += ok
        per_item.append(
            {
                "event": "bench_item",
                "benchmark": bench["name"],
                "rank": rank,
                "dataset_index": ds_idx,
                "ctx": it["ctx"],
                "endings": it["endings"],
                "label": it["label"],
                "scores": [None if s == float("-inf") else s for s in scores],
                "pred": pred,
                "correct": ok,
            }
        )
        print(
            f"  [{rank + 1:3d}/{len(items)}] {'OK ' if ok else 'XX '} "
            f"pred={pred} label={it['label']} ctx={it['ctx'][:50]!r}"
        )
    raw_rows.extend(per_item)
    n = len(items)
    accuracy = correct / n if n else 0.0
    if bench["fixed_baseline"] is not None:
        baseline = bench["fixed_baseline"]
    else:
        baseline = sum(1.0 / len(it["endings"]) for _, it in items) / max(n, 1)
    return {
        "benchmark": bench["name"],
        "dataset": bench["source"],
        "n": n,
        "correct": correct,
        "accuracy": accuracy,
        "random_baseline": baseline,
    }


def append_raw(rows: list) -> None:
    RAW_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(RAW_LOG, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--model", required=True, help="HF export dir (config.json + model.safetensors)"
    )
    ap.add_argument(
        "--benchmark",
        default="hellaswag",
        choices=["hellaswag", "arc"],
        help="benchmark: hellaswag (default; ARC-Easy auto-fallback) or arc",
    )
    ap.add_argument(
        "--n", type=int, default=DEFAULT_N, help=f"slice size (default {DEFAULT_N})"
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=4,
        help="contamination-check worker processes (check_leak is a full corpus scan)",
    )
    ap.add_argument("--threads", type=int, default=6, help="torch.set_num_threads")
    args = ap.parse_args()

    model_dir = Path(args.model)
    if not (model_dir / "config.json").exists():
        raise SystemExit(f"[EVAL] no HF export found at {model_dir} (need config.json)")
    run_id = f"comp002-{uuid.uuid4().hex[:8]}"
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    disk_before = disk_report("before model load")
    print(f"\n{'=' * 70}\n  ORION-COMP-002 EVAL: {run_id}\n{'=' * 70}")

    torch.set_num_threads(args.threads)
    model = Qwen2ForCausalLM.from_pretrained(str(model_dir))
    model.eval()
    tokenizer = orion_corpus.load_bpe_compat()
    print(f"[MODEL] loaded {model_dir} fp32 CPU | threads={args.threads}")
    raw_rows = []

    # --- (a) held-out generalization -----------------------------------------
    val = eval_split(model, tokenizer, "val")
    test = eval_split(model, tokenizer, "test")
    raw_rows.extend(
        [
            {"event": "heldout_shard", "run_id": run_id, "split": "val", **s}
            for s in val["shards"]
        ]
        + [{"event": "heldout_combined", "run_id": run_id, **val["combined"]}]
        + [
            {"event": "heldout_shard", "run_id": run_id, "split": "test", **s}
            for s in test["shards"]
        ]
        + [{"event": "heldout_combined", "run_id": run_id, **test["combined"]}]
    )

    # --- (b/c) benchmark + contamination -------------------------------------
    bench = load_benchmark(args.benchmark, args.n, SLICE_SEED)
    print(
        f"[DATASET] benchmark={bench['name']} source={bench['source']} "
        f"split=validation rows={len(bench['ds'])} "
        f"slice_rule=seed{SLICE_SEED}-shuffle-first-{args.n}-clean"
    )
    disk_mid = disk_report("after dataset load")
    print(f"[DISK] {json.dumps(disk_mid)}")

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    screen = screen_items(
        manifest, bench["ds"], bench["to_item"], bench["order"], args.n, args.workers
    )
    items = screen["items"]
    leaked = screen["leaked"]
    hits_per_split = {}
    if leaked:
        # re-run the probe to attribute split counts exactly for the leaked items
        jobs = []
        for l in leaked:
            for kind in ("context", "gold"):
                jobs.append((manifest, l["idx"], kind, ""))
        it_map = {
            i: bench["to_item"](bench["ds"][i]) for i in {l["idx"] for l in leaked}
        }
        jobs = []
        for l in leaked:
            jobs.append((manifest, l["idx"], "context", it_map[l["idx"]]["ctx"]))
            jobs.append(
                (
                    manifest,
                    l["idx"],
                    "gold",
                    it_map[l["idx"]]["endings"][it_map[l["idx"]]["label"]],
                )
            )
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            res = list(ex.map(_leak_probe, jobs))
        for r in res:
            for sp in r["splits"]:
                hits_per_split[sp] = hits_per_split.get(sp, 0) + 1

    result = run_benchmark(model, tokenizer, bench, items, raw_rows)
    raw_rows.append(
        {
            "event": "bench_summary",
            "run_id": run_id,
            "timestamp": timestamp,
            **{
                k: result[k]
                for k in (
                    "benchmark",
                    "dataset",
                    "n",
                    "correct",
                    "accuracy",
                    "random_baseline",
                )
            },
            "contamination_hits": len(leaked),
            "dropped_items": len(leaked),
            "slice_rule": f"seed={SLICE_SEED}: shuffled full-dataset order, first {args.n} clean items "
            "(check_leak drops+refills on hits)",
            "scoring": "mean log-prob of continuation tokens given context; argmax over choices",
            "model_dir": str(model_dir),
            "tokens_seen_ledger": 563626,
            "disk_before": disk_before,
            "disk_after_dataset": disk_mid,
        }
    )
    raw_rows.append(
        {
            "event": "contamination_summary",
            "run_id": run_id,
            "checked_strings": screen["meta"]["checked_strings"],
            "checked_items": screen["meta"]["checked_items"],
            "hit_items": len(leaked),
            "dropped_items": len(leaked),
            "hits_per_split": hits_per_split,
        }
    )
    append_raw(raw_rows)
    disk_after = disk_report("after eval")
    print(f"[DISK] {json.dumps(disk_after)}")

    # --- compact results block ----------------------------------------------
    print("\n==== ORION-COMP-002 RESULTS ====")
    print(
        f"HELDOUT val: loss={val['combined']['loss']:.4f} ppl={val['combined']['ppl']:,.2f} "
        f"(tokens={val['combined']['loss_tokens']:,}, blocks={val['combined']['blocks']})"
    )
    print(
        f"HELDOUT test: loss={test['combined']['loss']:.4f} ppl={test['combined']['ppl']:,.2f} "
        f"(tokens={test['combined']['loss_tokens']:,}, blocks={test['combined']['blocks']})"
    )
    print(
        f"BENCHMARK {result['benchmark']}: N={result['n']} accuracy={result['accuracy']:.4f} "
        f"({result['correct']}/{result['n']}) random_baseline={result['random_baseline']:.4f} "
        f"contamination_hits={len(leaked)} dropped={len(leaked)}"
    )
    print(
        f"DISK repo_free_gb {disk_before['repo_drive_free_gb']}->{disk_after['repo_drive_free_gb']} "
        f"cache_free_gb {disk_before['cache_drive_free_gb']}->{disk_after['cache_drive_free_gb']} "
        f"hf_cache_mb {disk_before['hf_cache_mb']}->{disk_after['hf_cache_mb']}"
    )
    print(f"RAW appended {len(raw_rows)} lines -> {RAW_LOG}")
    print("================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
