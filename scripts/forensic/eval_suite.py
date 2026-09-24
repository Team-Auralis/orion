#!/usr/bin/env python3
"""F5/F4 forensic held-out evaluation suite for COMP-001 100m-real.

Brutal held-out evaluation of `models/comp001/100m-real/checkpoint-1919`
(the TRUE latest trained state; the HF export model.safetensors is a stale
step-1869 artifact and is NOT the primary eval object). Zero trust: no tuning
on eval data, contamination-checked against the training corpus.

Pipeline (sequential phases, ONE model in RAM at a time; RAM-guarded):
  A. Contamination check FIRST  -- corpus_builder.check_leak on every eval
     item text (context + gold). Hits are recorded; contaminated items are
     DROPPED from scoring (expect 0 for HellaSwag/ARC/WinoGrande).
  B. Load checkpoint-1919 from checkpoint.json config + checkpoint.pt
     (weights_only=True, fp32 CPU, mmap when available).
  C. Benchmarks, 3 item-subset seeds (42, 1337, 2026) each: HellaSwag,
     ARC-Easy (test split preferred), WinoGrande (debiased), ORION set.
     Multiple-choice scoring = mean log-prob of each candidate continuation
     conditioned on context, argmax; greedy.
  D. Perplexity on held-out test-* and val-* shards (per-token NLL, chunked
     max_len 512) + optional small out-of-domain slice (HellaSwag contexts).
  E. Non-neural ppl baselines on the same test text: uniform-char (log2 256
     = 8 bits) and a character-frequency model trained on corpus TRAIN
     shards (labeled: per-character, not directly comparable to per-token).
  F. Untrained-init reconstruction (seed 42, the training seed): small
     HellaSwag N=50 + full ORION set, same flow, labeled RECONSTRUCTION.

Outputs (logs/forensic/eval/):
  eval_suite.json             all numbers, per-seed, CI
  eval_raw.jsonl              per-item rows (append-only)
  contamination_report.json   per-benchmark screened/hits/dropped

Usage:
  python scripts/forensic/eval_suite.py --model checkpoint-1919 [--benchmarks all]
      [--n 100] [--seeds 42,1337,2026] [--contamination-check] [--threads 6]
      [--skip-init-recon] [--benchmarks contamination,hellaswag,...]
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gc
import hashlib
import json
import math
import os
import random
import re
import sys
import time
import uuid
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "training"))

import psutil  # noqa: E402
import torch  # noqa: E402
from transformers import Qwen2Config, Qwen2ForCausalLM  # noqa: E402

import orion_corpus  # noqa: E402
from orion_runner.loader import pack_sequences, tokenize_samples  # noqa: E402
from scripts.forensic.orion_eval_set import (  # noqa: E402
    ORION_CHANCE_PER_ITEM,
    ORION_ITEMS,
    orion_probe_text,
)

CORPUS_DIR = REPO_ROOT / "data" / "training" / "corpus"
MANIFEST_PATH = CORPUS_DIR / "manifest.json"
TOKENIZER_DIR = REPO_ROOT / "models" / "tokenizer_bpe"
DEFAULT_MODEL = REPO_ROOT / "models" / "comp001" / "100m-real" / "checkpoint-1919"
OUT_DIR = REPO_ROOT / "logs" / "forensic" / "eval"
MAX_LEN = 512
PAD_ID, BOS_ID, EOS_ID = 0, 1, 2
CHANCE = {"hellaswag": 0.25, "arc_easy": 0.25, "winogrande": 0.50}
RAM_FLOOR_MB = 300.0
DEFAULT_SEEDS = [42, 1337, 2026]
BENCH_NAMES = {
    "hellaswag": "HellaSwag (4-choice commonsense, validation)",
    "arc_easy": "ARC-Easy (4-choice science QA)",
    "winogrande": "WinoGrande (2-choice pronoun, winogrande_debiased validation)",
    "orion": "ORION unseen set (30 completions + 10 MC, hardcoded)",
}
_WS_RE = re.compile(r"\s+")

# ---------------------------------------------------------------------------
# process-pool contamination worker over corpus_builder.check_leak
# ---------------------------------------------------------------------------
_POOL_MANIFEST: dict | None = None


def _init_worker(manifest_path: str) -> None:
    global _POOL_MANIFEST
    with open(manifest_path, "r", encoding="utf-8") as f:
        _POOL_MANIFEST = json.load(f)


def _check_leak_worker(text: str) -> dict:
    """One check_leak call (imported from corpus_builder). Returns {text, hits}."""
    from scripts.training.corpus_builder import check_leak

    hits = check_leak(_POOL_MANIFEST, text) if _POOL_MANIFEST else []
    return {"text": text, "hits": hits}


def screen_texts_parallel(
    texts: list[str], workers: int, n_shards: int = 0
) -> dict[str, list]:
    """Screen unique evaluation strings against the corpus manifest shards
    using the authoritative corpus-builder check_leak (process pool)."""
    n = len(texts)
    print(
        f"[A] screening {n} eval strings against {n_shards} "
        f"corpus shards ({workers} workers)..."
    )
    results: dict[str, list] = {}
    if n == 0:
        return results
    t0 = time.time()
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=workers, initializer=_init_worker, initargs=(str(MANIFEST_PATH),)
    ) as pool:
        for i, res in enumerate(pool.map(_check_leak_worker, texts, chunksize=1), 1):
            results[res["text"]] = res["hits"]
            if i % 25 == 0 or i == n:
                el = time.time() - t0
                print(
                    f"    screened {i}/{n} ({el / i:.1f}s/item, "
                    f"elapsed {el:.0f}s, hits so far {sum(len(v) for v in results.values())})"
                )
    return results


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def free_ram_mb() -> float:
    return psutil.virtual_memory().available / 1024**2


def ramp_guard(phase: str) -> None:
    avail = free_ram_mb()
    if avail < RAM_FLOOR_MB:
        print(
            f"[RAM-GUARD] ABORT before '{phase}': free RAM {avail:.0f} MB "
            f"< floor {RAM_FLOOR_MB:.0f} MB. Stopping cleanly (no OOM)."
        )
        sys.exit(2)
    print(f"[RAM] free RAM before '{phase}': {avail:.0f} MB")


def peak_rss_mb() -> float:
    return psutil.Process().memory_info().rss / 1024**2


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def ci95(acc: float, n: int) -> float | None:
    """Normal-approx 95% CI half-width; only meaningful for n > 30."""
    if n <= 30:
        return None
    return 1.96 * math.sqrt(acc * (1.0 - acc) / n)


# ---------------------------------------------------------------------------
# model + tokenizer
# ---------------------------------------------------------------------------


def load_model_from_checkpoint(ckpt_dir: Path):
    """Build from checkpoint.json config; load state_dict with weights_only.

    weights_only=True (task requirement) with mmap=True when the torch build
    supports it (keeps peak RSS low on the constrained box)."""
    ckpt_dir = Path(ckpt_dir)
    ckj = json.loads((ckpt_dir / "checkpoint.json").read_text(encoding="utf-8"))
    cfg_dict = ckj["config"]
    cfg_keys = (
        "vocab_size",
        "hidden_size",
        "intermediate_size",
        "num_hidden_layers",
        "num_attention_heads",
        "num_key_value_heads",
        "max_position_embeddings",
        "pad_token_id",
        "bos_token_id",
        "eos_token_id",
        "tie_word_embeddings",
    )
    cfg = Qwen2Config(**{k: cfg_dict[k] for k in cfg_keys})
    model = Qwen2ForCausalLM(cfg)
    ckpt_path = ckpt_dir / "checkpoint.pt"
    if not ckpt_path.exists():
        raise FileNotFoundError(f"checkpoint.pt not found in {ckpt_dir}")

    load_kwargs = dict(map_location="cpu", weights_only=True)
    try:
        state = torch.load(ckpt_path, mmap=True, **load_kwargs)
        loaded_note = "checkpoint.pt (weights_only=True, mmap=True)"
    except TypeError:  # older torch without mmap kwarg
        state = torch.load(ckpt_path, **load_kwargs)
        loaded_note = "checkpoint.pt (weights_only=True)"
    model.load_state_dict(state["model"])
    step = int(state.get("step", ckj.get("step", 0)))
    losses = list(state.get("losses", []))
    del state
    gc.collect()
    model.eval()
    n_params = sum(p.numel() for p in model.parameters())
    return model, cfg_dict, step, losses, n_params, loaded_note


def load_tokenizer():
    return orion_corpus.load_bpe_compat()


# ---------------------------------------------------------------------------
# multiple-choice scoring
# ---------------------------------------------------------------------------


def score_candidates(model, tokenizer, ctx: str, cands: list[str]) -> list[float]:
    """Mean log-prob of each candidate continuation conditioned on ctx.

    Separator rule (deterministic, documented): no extra space when ctx
    already ends with whitespace or ':', else a single space (so HellaSwag /
    ORION get ' ctx ending', ARC's 'ANSWER:' gets 'ANSWER:opt', WinoGrande's
    space-terminated prefix gets 'opt+suffix' with no double space).
    Truncation keeps the candidate intact and drops the OLDEST ctx tokens.
    """
    ctx_ids = tokenizer.encode(ctx).ids
    scores = []
    for cand in cands:
        sep = "" if (ctx and ctx[-1] in " \n\t:") else " "
        cand_ids = tokenizer.encode(sep + cand).ids
        if not cand_ids:
            scores.append(float("-inf"))
            continue
        budget = MAX_LEN - 1
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
        tok_logp = logp[torch.arange(len(full) - 1), targets]
        scores.append(float(tok_logp[cand_start - 1 :].mean().item()))
    return scores


# ---------------------------------------------------------------------------
# dataset loading (network only for downloads; cached by datasets)
# ---------------------------------------------------------------------------


def load_hellaswag(limit=None):
    from datasets import load_dataset

    split = f"validation[:{limit}]" if limit else "validation"
    ds = load_dataset("Rowan/hellaswag", split=split)
    items = []
    for i, ex in enumerate(ds):
        items.append(
            {
                "benchmark": "hellaswag",
                "item_id": f"hellaswag-val-{i}",
                "ctx": str(ex["ctx"]),
                "options": list(ex["endings"]),
                "gold": int(ex["label"]),
            }
        )
    print(f"[DATA] hellaswag validation: {len(items)} items")
    return items


def load_arc_easy():
    from datasets import load_dataset

    chosen_split = None
    ds = None
    for split in ("test", "validation"):  # test preferred (task requirement)
        try:
            ds = load_dataset("allenai/ai2_arc", "ARC-Easy", split=split)
            chosen_split = split
            break
        except Exception as exc:
            print(f"[DATA] ai2_arc ARC-Easy split '{split}' failed: {exc!r}")
    if ds is None:
        raise RuntimeError("ai2_arc ARC-Easy: neither test nor validation split loads")
    items = []
    mapping_notes = set()
    for i, ex in enumerate(ds):
        ch = ex["choices"]
        # ARC answers are lettered A-D -> normalize to the option text index.
        if ex["answerKey"] not in ch["label"]:
            continue
        gold = int(ch["label"].index(ex["answerKey"]))
        mapping_notes.add(f"{ex['answerKey']} -> option text index {gold}")
        items.append(
            {
                "benchmark": "arc_easy",
                "item_id": f"arc-easy-{chosen_split}-{i}",
                "ctx": "QUESTION: " + str(ex["question"]) + "\nANSWER:",
                "options": [str(t) for t in ch["text"]],
                "gold": gold,
                "question": str(ex["question"]),
            }
        )
    print(
        f"[DATA] ai2_arc ARC-Easy split={chosen_split}: {len(items)} items "
        f"| answer-key mapping sample: {sorted(mapping_notes)[:4]}"
    )
    return items, chosen_split


def load_winogrande():
    from datasets import load_dataset

    ds = load_dataset("winogrande", "winogrande_debiased", split="validation")
    items = []
    for i, ex in enumerate(ds):
        parts = str(ex["sentence"]).split("_")
        if len(parts) != 2:
            continue
        prefix, suffix = parts[0], parts[1]
        opt1, opt2 = str(ex["option1"]), str(ex["option2"])
        gold = int(ex["answer"]) - 1
        items.append(
            {
                "benchmark": "winogrande",
                "item_id": f"winogrande-debiased-val-{i}",
                "ctx": prefix,
                "options": [opt1 + suffix, opt2 + suffix],
                "gold": gold,
            }
        )
    print(f"[DATA] winogrande_debiased validation: {len(items)} items")
    return items


# ---------------------------------------------------------------------------
# benchmark runners
# ---------------------------------------------------------------------------


def run_mc_items(model, tokenizer, subset, label):
    """Score a FIXED item subset (pre-sampled per seed): for each item, mean
    log-prob of each candidate continuation conditioned on ctx, argmax."""
    rows = []
    correct = 0
    for it in subset:
        scores = score_candidates(model, tokenizer, it["ctx"], it["options"])
        chosen = int(max(range(len(scores)), key=lambda k: scores[k]))
        hit = chosen == it["gold"]
        correct += hit
        rows.append(
            {
                "benchmark": it["benchmark"],
                "item_id": it["item_id"],
                "ctx": it["ctx"],
                "options": it["options"],
                "scores": [round(s, 6) for s in scores],
                "gold": it["gold"],
                "chosen": chosen,
                "hit": hit,
            }
        )
    acc = correct / len(subset) if subset else 0.0
    return rows, {"n": len(subset), "correct": correct, "accuracy": acc}


def sample_subsets(pool, seeds, n, slack=20):
    """Deterministic per-seed item subsets in sampled order (fixed rng seeds).

    Each seed shuffles the pool and takes n+slack items; drops discovered by
    the contamination screen are trimmed OUT (refill headroom) and the first
    `n` clean items per seed are the eval subset. Returns {seed: [items]}.
    """
    subs = {}
    for seed in seeds:
        rng = random.Random(seed)
        order = list(range(len(pool)))
        rng.shuffle(order)
        subs[seed] = [pool[i] for i in order[: n + slack]]
    return subs


def run_orion(model, tokenizer, label):
    rows = []
    stats = {"completion_hits": 0, "completion_n": 0, "mc_hits": 0, "mc_n": 0}
    for it in ORION_ITEMS:
        if it["kind"] == "completion":
            # accuracy: greedy completion match (normalized); likelihood: mean
            # log-prob of the gold continuation conditioned on the prompt.
            input_ids = torch.tensor(
                [tokenizer.encode(it["prompt"]).ids], dtype=torch.long
            )
            with torch.no_grad():
                out_ids = model.generate(
                    input_ids=input_ids,
                    max_new_tokens=10,
                    do_sample=False,
                    pad_token_id=PAD_ID,
                    eos_token_id=EOS_ID,
                )
            completion = tokenizer.decode(
                out_ids[0, input_ids.shape[1] :].tolist(), skip_special_tokens=True
            )
            gold_lp = score_candidates(model, tokenizer, it["prompt"], [it["answer"]])[
                0
            ]
            nc, na = norm(completion), norm(it["answer"])
            comp_hit = bool(na and (na in nc or nc == na))
            stats["completion_n"] += 1
            stats["completion_hits"] += comp_hit
            rows.append(
                {
                    "benchmark": "orion",
                    "item_id": "orion-comp-" + norm(it["prompt"])[:24],
                    "kind": "completion",
                    "ctx": it["prompt"],
                    "gold_text": it["answer"],
                    "greedy": completion,
                    "gold_mean_logp": round(gold_lp, 6)
                    if gold_lp != float("-inf")
                    else None,
                    "hit": comp_hit,
                    "chance": ORION_CHANCE_PER_ITEM["completion"],
                }
            )
        else:
            scores = score_candidates(model, tokenizer, it["prompt"], it["options"])
            chosen = int(max(range(len(scores)), key=lambda k: scores[k]))
            hit = chosen == it["answer"]
            stats["mc_n"] += 1
            stats["mc_hits"] += hit
            rows.append(
                {
                    "benchmark": "orion",
                    "item_id": "orion-mc-" + norm(it["prompt"])[:24],
                    "kind": "mc",
                    "ctx": it["prompt"],
                    "options": it["options"],
                    "scores": [round(s, 6) for s in scores],
                    "gold": it["answer"],
                    "chosen": chosen,
                    "hit": hit,
                    "chance": ORION_CHANCE_PER_ITEM["mc"],
                }
            )
    n_all = stats["completion_n"] + stats["mc_n"]
    acc_all = (stats["completion_hits"] + stats["mc_hits"]) / n_all if n_all else 0.0
    chance_all = (
        (
            sum(
                ORION_CHANCE_PER_ITEM["completion"]
                for _ in range(stats["completion_n"])
            )
            + sum(ORION_CHANCE_PER_ITEM["mc"] for _ in range(stats["mc_n"]))
        )
        / n_all
        if n_all
        else 0.0
    )
    return rows, {
        "n": n_all,
        "accuracy": acc_all,
        "chance": chance_all,
        "completion": {k: stats[k] for k in ("completion_hits", "completion_n")},
        "mc": {"mc_hits": stats["mc_hits"], "mc_n": stats["mc_n"]},
    }


# ---------------------------------------------------------------------------
# perplexity (per-token NLL over packed blocks, manual exact accounting)
# ---------------------------------------------------------------------------


def ppl_blocks(model, blocks):
    total_nll, total_tok = 0.0, 0
    with torch.no_grad():
        for blk in blocks:
            ids = torch.tensor([blk["input_ids"]], dtype=torch.long)
            lbl = torch.as_tensor(blk["labels"], dtype=torch.long)
            logits = model(input_ids=ids).logits[0]
            logp = torch.log_softmax(logits[:-1].float(), dim=-1)
            targets = lbl[1:]
            mask = targets != -100
            sel = logp[torch.arange(logp.shape[0]), targets][mask]
            total_nll += float(-sel.sum().item())
            total_tok += int(mask.sum().item())
    return total_nll, total_tok


def ppl_split(model, tokenizer, split: str) -> dict:
    files = sorted(
        p for p in orion_corpus.shard_files() if p.name.startswith(split + "-")
    )
    if not files:
        return {"split": split, "loss": None, "ppl": None, "tokens": 0, "blocks": 0}
    total_nll, total_tok, n_blocks = 0.0, 0, 0
    for path in files:
        rows = orion_corpus.load_samples([path])
        blocks = pack_sequences(
            tokenize_samples(
                rows, tokenizer, orion_corpus.row_text, max_len=MAX_LEN, truncation=True
            ),
            max_len=MAX_LEN,
            pad_id=PAD_ID,
            seed=42,
            mask_boundaries=True,
            pad_to_max=True,
        )
        nll, tok = ppl_blocks(model, blocks)
        total_nll += nll
        total_tok += tok
        n_blocks += len(blocks)
    loss = total_nll / max(total_tok, 1)
    return {
        "split": split,
        "loss": loss,
        "ppl": math.exp(loss) if loss < 100 else float("inf"),
        "tokens": total_tok,
        "blocks": n_blocks,
    }


def ppl_strings(model, tokenizer, texts: list[str], label: str) -> dict:
    total_nll, total_tok = 0.0, 0
    with torch.no_grad():
        for t in texts:
            ids = tokenizer.encode(t).ids[:MAX_LEN]
            if len(ids) < 2:
                continue
            logits = model(input_ids=torch.tensor([ids], dtype=torch.long)).logits[0]
            logp = torch.log_softmax(logits[:-1].float(), dim=-1)
            targets = torch.as_tensor(ids[1:], dtype=torch.long)
            total_nll += float(-logp[torch.arange(logp.shape[0]), targets].sum().item())
            total_tok += len(ids) - 1
    loss = total_nll / max(total_tok, 1)
    return {
        "split": label,
        "loss": loss,
        "ppl": math.exp(loss) if loss < 100 else float("inf"),
        "tokens": total_tok,
    }


# ---------------------------------------------------------------------------
# char baselines (non-neural, per-character)
# ---------------------------------------------------------------------------


def build_char_model(train_files):
    counter: Counter = Counter()
    total = 0
    for path in train_files:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                text = orion_corpus.row_text(row)
                counter.update(text)
                total += len(text)
    return counter, total


def char_ppl(counter, total, text, smoothing=1.0):
    """Per-character ppl, Laplace(add-1) over the 256-byte alphabet."""
    denom = total + 256.0 * smoothing
    nll = 0.0
    n = 0
    for ch in text:
        frac = (counter[ch] + smoothing) / denom
        nll += -math.log2(frac)
        n += 1
    return 2.0 ** (nll / max(n, 1)), nll / max(n, 1)


def test_split_text():
    files = sorted(p for p in orion_corpus.shard_files() if p.name.startswith("test-"))
    parts = []
    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                parts.append(orion_corpus.row_text(row))
    return "".join(parts)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def parse_benchmarks(arg: str) -> list[str]:
    if arg in ("all", ""):
        return [
            "hellaswag",
            "arc_easy",
            "winogrande",
            "orion",
            "ppl",
            "baselines",
            "init_recon",
        ]
    return [b.strip() for b in arg.split(",") if b.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=str(DEFAULT_MODEL), help="checkpoint dir")
    ap.add_argument(
        "--benchmarks",
        default="all",
        help="comma list or 'all' (hellaswag,arc_easy,winogrande,"
        "orion,ppl,baselines,init_recon,contamination)",
    )
    ap.add_argument("--n", type=int, default=100, help="items per benchmark per seed")
    ap.add_argument(
        "--seeds", default="42,1337,2026", help="comma-separated item-subset seeds"
    )
    ap.add_argument(
        "--contamination-check",
        action="store_true",
        help="run the corpus-builder contamination check first",
    )
    ap.add_argument("--threads", type=int, default=6, help="torch threads")
    ap.add_argument(
        "--skip-init-recon",
        action="store_true",
        help="skip the untrained-init reconstruction phase",
    )
    args = ap.parse_args()

    torch.set_num_threads(args.threads)
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    benches = parse_benchmarks(args.benchmarks)

    ckpt_dir = Path(args.model)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = f"forensic-eval-{uuid.uuid4().hex[:8]}"
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    raw_path = OUT_DIR / "eval_raw.jsonl"
    print(f"[RUN] {run_id} | model={ckpt_dir} | n={args.n} | seeds={seeds}")
    print(f"[RUN] benchmarks={benches} | threads={args.threads} | out={OUT_DIR}")
    ramp_guard("startup")
    peaks = {"startup": round(peak_rss_mb(), 1)}

    manifest = None
    if MANIFEST_PATH.exists():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    else:
        print("[A][WARN] no corpus manifest found - contamination check unavailable")

    need_contam = args.contamination_check and manifest is not None
    contamination = {
        "run_id": run_id,
        "manifest": str(MANIFEST_PATH),
        "per_benchmark": {},
        "total_screened": 0,
        "total_hits": 0,
        "total_dropped": 0,
    }

    # ---------------- A. contamination check (FIRST, before any eval) -----
    if need_contam:
        ramp_guard("contamination check")
        if args.model == str(DEFAULT_MODEL):
            print("[A] running contamination check first (no eval before it)")
        t0 = time.time()
        # Load pools and pre-sample the per-seed subsets; SCREEN ONLY the
        # items that can actually be scored (unique texts across seeds).
        bench_pools: dict[str, list] = {}
        subs_by_bench: dict[str, dict[int, list]] = {}
        bench_split: dict[str, str] = {}

        for bench in ("hellaswag", "arc_easy", "winogrande"):
            if bench not in benches:
                continue
            if bench == "hellaswag":
                items = load_hellaswag()
                bench_split[bench] = "validation"
            elif bench == "arc_easy":
                items, split_note = load_arc_easy()
                bench_split[bench] = split_note
            else:
                items = load_winogrande()
                bench_split[bench] = "winogrande_debiased validation"
            bench_pools[bench] = items
            subs_by_bench[bench] = sample_subsets(items, seeds, args.n, slack=20)

        # unique screening strings: ctx + gold (per benchmark x seed subset)
        screen_to_items: dict[
            str, list[tuple[str, str]]
        ] = {}  # text -> [(bench, item_id)]
        for bench, subs in subs_by_bench.items():
            seen_ids = set()
            for seed, subset in subs.items():
                for it in subset:
                    if it["item_id"] in seen_ids:
                        continue
                    seen_ids.add(it["item_id"])
                    gold_text = it["options"][it["gold"]]
                    key = it["ctx"] + " " + gold_text
                    screen_to_items.setdefault(key, []).append((bench, it["item_id"]))
                    if len(norm(gold_text)) >= 200:  # long gold: also standalone
                        screen_to_items.setdefault(gold_text, []).append(
                            (bench, it["item_id"])
                        )

        print("[A] loading benchmark-aware contamination strings...")
        # ORION set contamination: item prompt + gold (fixed, screened every run)
        orion_texts = [orion_probe_text(it) for it in ORION_ITEMS]

        all_texts = sorted(set(screen_to_items) | set(orion_texts))
        contamination["total_screened"] = len(all_texts)

        if all_texts:
            hit_map = screen_texts_parallel(
                all_texts,
                workers=max(2, min(args.threads, 12)),
                n_shards=len(manifest.get("shards", [])),
            )
            screening_elapsed = time.time() - t0
            hit_item_ids: dict[str, set[str]] = {b: set() for b in bench_pools}
            for text, hits in hit_map.items():
                if not hits:
                    continue
                for bench, item_id in screen_to_items.get(text, []):
                    hit_item_ids.setdefault(bench, set()).add(item_id)
            # Trim contaminated items out of each seed subset (expect 0);
            # keep the first n clean items per seed in sampled order.
            for bench, subs in subs_by_bench.items():
                dropped = hit_item_ids.get(bench, set())
                n_dropped_pool = len(dropped)
                bench_hit_texts = [
                    t
                    for t, v in screen_to_items.items()
                    if hit_map.get(t) and any(b == bench for b, _ in v)
                ]
                n_hits = sum(len(hit_map[t]) for t in bench_hit_texts)
                n_bench_strings = len(
                    {
                        t
                        for t, v in screen_to_items.items()
                        if any(b == bench for b, _ in v)
                    }
                )
                per_seed_after = {}
                for seed, subset in subs.items():
                    clean = [it for it in subset if it["item_id"] not in dropped]
                    per_seed_after[seed] = clean[: args.n]
                subs_by_bench[bench] = per_seed_after
                contamination["per_benchmark"][bench] = {
                    "split": bench_split.get(bench, "unknown"),
                    "screened_strings": n_bench_strings,
                    "hits": n_hits,
                    "dropped_items": n_dropped_pool,
                    "hit_details": {t: hit_map[t][:5] for t in bench_hit_texts},
                    "clean_per_seed_after_drop": {
                        str(s): len(subs_by_bench[bench][s]) for s in seeds
                    },
                }
                contamination["total_hits"] += n_hits
                contamination["total_dropped"] += n_dropped_pool
            # ORION set drops
            orion_hits = {t: hit_map[t] for t in orion_texts if hit_map.get(t)}
            n_orion = sum(len(v) for v in orion_hits.values())
            orion_dropped = len({t for t, h in orion_hits.items() if h})
            contamination["per_benchmark"]["orion"] = {
                "split": "hardcoded",
                "screened_strings": len(orion_texts),
                "hits": n_orion,
                "dropped_items": orion_dropped,
                "hit_details": {k: v[:5] for k, v in orion_hits.items()},
            }
            contamination["total_hits"] += n_orion
            contamination["total_dropped"] += orion_dropped
            contamination["screening_seconds"] = round(screening_elapsed, 1)
            print(
                f"[A] contamination check finished in {screening_elapsed:.0f}s "
                f"| hits={contamination['total_hits']} dropped={contamination['total_dropped']}"
            )
            if contamination["total_hits"]:
                print("[A][WARN] hits found (see contamination_report.json)")
        peaks["contamination"] = round(peak_rss_mb(), 1)
        contamination_report_path = OUT_DIR / "contamination_report.json"
        contamination_report_path.write_text(
            json.dumps(contamination, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"[A] wrote {contamination_report_path}")
    else:
        print("[A] skipped (use --contamination-check with a corpus manifest)")
        # still load the benchmark pools if we eval them
        bench_pools = {}
        subs_by_bench = {}
        bench_split = {}
        for bench in ("hellaswag", "arc_easy", "winogrande"):
            if bench not in benches:
                continue
            if bench == "hellaswag":
                bench_pools[bench] = load_hellaswag()
                bench_split[bench] = "validation"
            elif bench == "arc_easy":
                items, split_note = load_arc_easy()
                bench_pools[bench] = items
                bench_split[bench] = split_note
            else:
                bench_pools[bench] = load_winogrande()
                bench_split[bench] = "winogrande_debiased validation"
            subs_by_bench[bench] = sample_subsets(
                bench_pools[bench], seeds, args.n, slack=0
            )
        if "orion" in benches:
            contamination["per_benchmark"]["orion"] = {"note": "screening skipped"}

    # ---------------- benchmark eval: trained model -----------------------
    eval_payload = {}
    raw_written = 0

    def write_raw(rows):
        nonlocal raw_written
        with open(raw_path, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        raw_written += len(rows)

    bench_evals = {}
    model = None
    if (
        "orion" in benches
        or "hellaswag" in benches
        or "arc_easy" in benches
        or "winogrande" in benches
        or "ppl" in benches
    ):
        ramp_guard("model load (trained checkpoint)")
        t0 = time.time()
        model, cfg_dict, step, losses, n_params, load_note = load_model_from_checkpoint(
            ckpt_dir
        )
        load_elapsed = time.time() - t0
        print(
            f"[B] loaded {ckpt_dir.name} | step={step} | params={n_params:,} "
            f"| {load_note} | {load_elapsed:.0f}s | RSS {peak_rss_mb():.0f} MB"
        )
        # Secondary comparison point: stale HF export at step 1869.
        hf_export = REPO_ROOT / "models" / "comp001" / "100m-real" / "model.safetensors"
        hf_info = "not evaluated (optional secondary export artifact)"
        eval_payload["model"] = {
            "checkpoint": str(ckpt_dir),
            "step": step,
            "ckpt_sha256": sha256_file(ckpt_dir / "checkpoint.pt")[:16],
            "config": cfg_dict,
            "params": n_params,
            "load": load_note,
            "hf_export_artifact": str(hf_export),
            "hf_export_is_primary": False,
            "hf_export_note": hf_info,
        }

        tokenizer = load_tokenizer()

    # HellaSwag
    if "hellaswag" in benches:
        ramp_guard("hellaswag eval")
        print(
            f"[C] HellaSwag: 3 seeds x n={args.n} "
            f"(selected subsets fixed by the contamination phase)"
        )
        per_seed = []
        all_rows = []
        for seed in seeds:
            subset = subs_by_bench["hellaswag"][seed]
            rows, stat = run_mc_items(model, tokenizer, subset, "hellaswag")
            c = ci95(stat["accuracy"], stat["n"])
            per_seed.append({**stat, "seed": seed, "ci95": c})
            for r in rows:
                r.update({"phase": "trained", "seed": seed, "run_id": run_id, "ts": ts})
            all_rows += rows
            print(
                f"    seed {seed}: {stat['accuracy']:.4f} ({stat['correct']}/{stat['n']})"
            )
        write_raw(all_rows)
        accs = [s["accuracy"] for s in per_seed]
        bench_evals["hellaswag"] = {
            "per_seed": per_seed,
            "mean": sum(accs) / len(accs),
            "std": (sum((a - sum(accs) / len(accs)) ** 2 for a in accs) / len(accs))
            ** 0.5,
            "chance": CHANCE["hellaswag"],
            "ci_note": "CI = normal-approx binomial per seed (n>30); std is across the 3 item subsets",
            "seeds": seeds,
        }
        peaks["hellaswag"] = round(peak_rss_mb(), 1)

    # ARC-Easy
    if "arc_easy" in benches:
        ramp_guard("arc_easy eval")
        print(
            f"[C] ARC-Easy (split={bench_split.get('arc_easy', 'unknown')}): "
            f"3 seeds x n={args.n}"
        )
        per_seed = []
        all_rows = []
        for seed in seeds:
            subset = subs_by_bench["arc_easy"][seed]
            rows, stat = run_mc_items(model, tokenizer, subset, "arc_easy")
            c = ci95(stat["accuracy"], stat["n"])
            per_seed.append({**stat, "seed": seed, "ci95": c})
            for r in rows:
                r.update({"phase": "trained", "seed": seed, "run_id": run_id, "ts": ts})
            all_rows += rows
            print(
                f"    seed {seed}: {stat['accuracy']:.4f} ({stat['correct']}/{stat['n']})"
            )
        write_raw(all_rows)
        accs = [s["accuracy"] for s in per_seed]
        bench_evals["arc_easy"] = {
            "per_seed": per_seed,
            "mean": sum(accs) / len(accs),
            "std": (sum((a - sum(accs) / len(accs)) ** 2 for a in accs) / len(accs))
            ** 0.5,
            "chance": CHANCE["arc_easy"],
            "split_used": bench_split.get("arc_easy", "unknown"),
            "ci_note": "CI = normal-approx binomial per seed (n>30); std is across the 3 item subsets",
            "seeds": seeds,
        }
        peaks["arc_easy"] = round(peak_rss_mb(), 1)

    # WinoGrande
    if "winogrande" in benches:
        ramp_guard("winogrande eval")
        print(f"[C] WinoGrande (debiased validation): 3 seeds x n={args.n}")
        per_seed = []
        all_rows = []
        for seed in seeds:
            subset = subs_by_bench["winogrande"][seed]
            rows, stat = run_mc_items(model, tokenizer, subset, "winogrande")
            c = ci95(stat["accuracy"], stat["n"])
            per_seed.append({**stat, "seed": seed, "ci95": c})
            for r in rows:
                r.update({"phase": "trained", "seed": seed, "run_id": run_id, "ts": ts})
            all_rows += rows
            print(
                f"    seed {seed}: {stat['accuracy']:.4f} ({stat['correct']}/{stat['n']})"
            )
        write_raw(all_rows)
        accs = [s["accuracy"] for s in per_seed]
        bench_evals["winogrande"] = {
            "per_seed": per_seed,
            "mean": sum(accs) / len(accs),
            "std": (sum((a - sum(accs) / len(accs)) ** 2 for a in accs) / len(accs))
            ** 0.5,
            "chance": CHANCE["winogrande"],
            "ci_note": "CI = normal-approx binomial per seed (n>30); std is across the 3 item subsets",
            "seeds": seeds,
        }
        peaks["winogrande"] = round(peak_rss_mb(), 1)

    # ORION set (trained)
    if "orion" in benches:
        ramp_guard("orion set eval")
        print(f"[C] ORION set: {len(ORION_ITEMS)} items (fixed, no seed variation)...")
        rows, stat = run_orion(model, tokenizer, "trained")
        for r in rows:
            r.update({"phase": "trained", "run_id": run_id, "ts": ts})
        write_raw(rows)
        bench_evals["orion"] = {**stat, "n_items": len(ORION_ITEMS)}
        print(
            f"    ORION: completion {stat['completion']} | mc {stat['mc']} "
            f"| overall acc {stat['accuracy']:.4f} (chance {stat['chance']:.4f})"
        )
        peaks["orion"] = round(peak_rss_mb(), 1)

    # ---------------- D. perplexity ----------------------------------------
    if "ppl" in benches and model is not None:
        ramp_guard("perplexity eval")
        print("[D] perplexity: test split + val split (per-token NLL)...")
        ppl = {
            "test": ppl_split(model, tokenizer, "test"),
            "val": ppl_split(model, tokenizer, "val"),
        }
        # out-of-domain small slice: HellaSwag contexts (cross-domain check)
        try:
            hs_ctxs = [it["ctx"] for it in load_hellaswag(limit=20)]
            ood = ppl_strings(
                model, tokenizer, hs_ctxs, "out-of-domain (hellaswag ctx, N=20)"
            )
            ppl["out_of_domain"] = ood
        except Exception as exc:
            print(f"[D][WARN] out-of-domain slice failed: {exc!r}")
            ppl["out_of_domain"] = {"error": str(exc)}
        print(
            f"    test ppl={ppl['test']['ppl']:.2f} ({ppl['test']['tokens']:,} tok) | "
            f"val ppl={ppl['val']['ppl']:.2f} ({ppl['val']['tokens']:,} tok) | "
            f"ood ppl={ppl.get('out_of_domain', {}).get('ppl', 'n/a')}"
        )
        bench_evals["ppl"] = ppl
        peaks["ppl"] = round(peak_rss_mb(), 1)

    # ---------------- E. char baselines (no torch) -------------------------
    if "baselines" in benches:
        ramp_guard("char baselines")
        print("[E] non-neural ppl baselines on the same held-out test text...")
        counter, total = build_char_model(
            sorted(p for p in orion_corpus.shard_files() if p.name.startswith("train-"))
        )
        test_text = test_split_text()
        n_chars = len(test_text)
        cppl, bits = char_ppl(counter, total, test_text)
        obs_alpha = len(set(test_text) | set(counter.keys()))
        uniform_obs_bits = math.log2(obs_alpha)
        baselines = {
            "uniform_char": {
                "bits_per_char": 8.0,
                "ppl_per_char": 256.0,
                "note": "uniform over 256-byte alphabet",
            },
            "uniform_observed_charset": {
                "bits_per_char": round(uniform_obs_bits, 4),
                "ppl_per_char": round(2**uniform_obs_bits, 4),
                "charset_size": obs_alpha,
            },
            "char_frequency": {
                "ppl_per_char": round(cppl, 4),
                "bits_per_char": round(bits, 4),
                "model": "add-1 Laplace over corpus TRAIN shard char counts",
                "train_chars": total,
            },
            "test_text": {
                "chars": n_chars,
                "docs": 598,
                "note": "per-character ppl, NOT directly comparable to per-token model ppl",
            },
        }
        bench_evals["baselines"] = baselines
        print(
            f"    uniform-char ppl=256.0 (8 bits) | char-freq ppl={cppl:.2f} "
            f"({bits:.3f} bits/char, train_chars={total:,}, test_chars={n_chars:,})"
        )
        peaks["baselines"] = round(peak_rss_mb(), 1)

    # free the trained model before init reconstruction
    if model is not None:
        del model
        gc.collect()
        torch.set_num_threads(args.threads)
        print(f"[MEM] trained model freed; RSS {peak_rss_mb():.0f} MB")

    # ---------------- F. init reconstruction (seed 42) ---------------------
    if "init_recon" in benches and not args.skip_init_recon:
        ramp_guard("init reconstruction")
        print(
            "[F] untrained-init RECONSTRUCTION (seed 42, training seed): "
            "HellaSwag N=50 + ORION set (small, honest 'init ~= chance')..."
        )
        ckj = json.loads((ckpt_dir / "checkpoint.json").read_text(encoding="utf-8"))
        cfg_dict_r = ckj["config"]
        cfg_keys = (
            "vocab_size",
            "hidden_size",
            "intermediate_size",
            "num_hidden_layers",
            "num_attention_heads",
            "num_key_value_heads",
            "max_position_embeddings",
            "pad_token_id",
            "bos_token_id",
            "eos_token_id",
            "tie_word_embeddings",
        )
        torch.manual_seed(42)
        recon = Qwen2ForCausalLM(Qwen2Config(**{k: cfg_dict_r[k] for k in cfg_keys}))
        recon.eval()
        tokenizer = load_tokenizer()
        # seed-42 fixed 50-item subset of the (already built) HellaSwag pool
        hs_sub = sample_subsets(
            bench_pools.get("hellaswag") or load_hellaswag(), [42], 50, slack=0
        )[42]
        rows, stat = run_mc_items(recon, tokenizer, hs_sub, "hellaswag")
        for r in rows:
            r.update(
                {"phase": "reconstruction", "seed": 42, "run_id": run_id, "ts": ts}
            )
        write_raw(rows)
        orows, ostat = run_orion(recon, tokenizer, "reconstruction")
        for r in orows:
            r.update({"phase": "reconstruction", "run_id": run_id, "ts": ts})
        write_raw(orows)
        bench_evals["init_reconstruction"] = {
            "note": "untrained init RECONSTRUCTED with seed 42 (training seed); the true init "
            "checkpoint was never saved, so this is a reconstruction labeled honestly",
            "hellaswag_n50_seed42": stat,
            "hellaswag_chance": 0.25,
            "orion": ostat,
        }
        print(
            f"    recon hellaswag(N=50): {stat['accuracy']:.4f} (chance 0.25) | "
            f"orion: {ostat['accuracy']:.4f}"
        )
        del recon
        gc.collect()
        peaks["init_reconstruction"] = round(peak_rss_mb(), 1)

    # ---------------- write eval_suite.json --------------------------------
    bench_evals = {k: bench_evals[k] for k in sorted(bench_evals)}
    suite = {
        "run_id": run_id,
        "timestamp": ts,
        "command": " ".join(sys.argv),
        "eval_payload": eval_payload,
        "forensic_model": {
            "primary": str(ckpt_dir),
            "note": "HF export model.safetensors is a STALE step-1869 artifact "
            "(byte-identical to step-1869) and was intentionally NOT used "
            "as the primary eval model; forensics identified checkpoint-1919 "
            "as the true latest trained state.",
        },
    }
    suite.update(bench_evals)
    suite.update(
        {
            "summary": {
                "hellaswag": bench_evals.get("hellaswag", {}),
                "arc_easy": bench_evals.get("arc_easy", {}),
                "winogrande": bench_evals.get("winogrande", {}),
                "orion": bench_evals.get("orion", {}),
            },
            "contamination": contamination,
            "peak_rss_mb_per_phase": peaks,
            "raw_rows_written": raw_written,
        }
    )
    suite_path = OUT_DIR / "eval_suite.json"
    suite_path.write_text(
        json.dumps(suite, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n[OUT] wrote {suite_path}")
    print(f"[OUT] raw rows: {raw_written} in {raw_path}")

    # ---------------- printed summary table --------------------------------
    print("\n" + "=" * 78)
    print("FORENSIC EVAL SUMMARY (step-1919 checkpoint-1919)")
    print("=" * 78)
    for b in ("hellaswag", "arc_easy", "winogrande"):
        if b in bench_evals:
            r = bench_evals[b]
            ps = "  ".join(f"s{s['seed']}={s['accuracy']:.3f}" for s in r["per_seed"])
            print(
                f"  {b:<12} mean={r['mean']:.3f} +/- {r['std']:.3f} | chance={r['chance']:.2f} "
                f"| seeds: {ps}"
            )
    if "orion" in bench_evals:
        r = bench_evals["orion"]
        print(
            f"  {'orion':<12} acc={r['accuracy']:.3f} | chance={r['chance']:.4f} "
            f"| comp={r['completion']} | mc={r['mc']}"
        )
    ppl = bench_evals.get("ppl", {})
    if ppl:
        print(
            f"  ppl: test={ppl.get('test', {}).get('ppl')} val={ppl.get('val', {}).get('ppl')} "
            f"ood={ppl.get('out_of_domain', {}).get('ppl', 'n/a')}"
        )
    bl = bench_evals.get("baselines", {})
    if bl:
        print(
            f"  baselines: uniform-char=256.0 | observed-charset={bl.get('uniform_observed_charset', {}).get('ppl_per_char')} "
            f"| char-freq={bl.get('char_frequency', {}).get('ppl_per_char')} (per-char)"
        )
    if "init_reconstruction" in bench_evals:
        r = bench_evals["init_reconstruction"]
        print(
            f"  RECONSTRUCTION(seed42): hellaswag N=50 acc={r['hellaswag_n50_seed42']['accuracy']:.3f} "
            f"| chance=0.25 | orion acc={r['orion']['accuracy']:.3f}"
        )
    print(
        f"  contamination: screened={contamination.get('total_screened')} "
        f"hits={contamination.get('total_hits')} dropped={contamination.get('total_dropped')}"
    )
    print(f"  peak RSS per phase (MB): {peaks}")
    print(f"  raw rows: {raw_written}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
