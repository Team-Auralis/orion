#!/usr/bin/env python3
"""F5 memorization / contamination checks for checkpoint-1919.

The evaluation items (`logs/forensic/eval/eval_raw.jsonl` + the hardcoded ORION
set) are the external probe; the training corpus is `data/training/corpus/train-*`.
Zero-trust: nothing is assumed clean; every hit below is a reported fact.

Parts:
  1. Exact-duplicate check  - a rolling 13-token n-gram set over the eval items
     is tested against a single streaming pass over ALL train shards (hash set,
     verified by exact substring). PROBE GATE: only probe strings with >= 13
     tokens enter this leg (a 13-token exact substring is the minimum evidence
     of copied text). Shorter fragments (single-word ARC answers, "The capital
     city of Nauru is", winogrande prefixes) float into a separate fragment
     summary that is reported but NOT counted as contamination.
  2. Verbatim-memorization probe - 5 prompts that are literally the first 32
     BPE tokens of corpus rows (train-fw-part-00000 rows 1-5) + 5 non-corpus
     prompts (ORION eval set). Greedy generation; corpus-prefix prompts are
     compared token-for-token against the true corpus continuation; ORION
     generations are checked for corpus n-gram contamination.
  3. Near-duplicate check - for a 20-item sample, normalized bigram Jaccard vs
     a deterministic 1/40 sample of corpus rows; max similarity per item;
     items with max > 0.8 flagged POSSIBLE_NEAR_DUP. Bounded, cheap.

Output: logs/forensic/memorization.json
"""

from __future__ import annotations

import gc
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import psutil  # noqa: E402
import torch  # noqa: E402

from scripts.forensic.eval_suite import (  # noqa: E402
    load_model_from_checkpoint,
    load_tokenizer,
)
from scripts.forensic.orion_eval_set import ORION_ITEMS  # noqa: E402
from scripts.training.corpus_builder import normalize_key  # noqa: E402
from scripts.training.orion_corpus import row_text, shard_files  # noqa: E402

CKPT_DIR = REPO_ROOT / "models" / "comp001" / "100m-real" / "checkpoint-1919"
CORPUS_DIR = REPO_ROOT / "data" / "training" / "corpus"
EVAL_RAW = REPO_ROOT / "logs" / "forensic" / "eval" / "eval_raw.jsonl"
OUT_DIR = REPO_ROOT / "logs" / "forensic"
NGRAM = 13
PAD_ID, EOS_ID = 0, 2

TS = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def ram_mb() -> float:
    return psutil.virtual_memory().available / 1024**2


def rss_mb() -> float:
    return psutil.Process().memory_info().rss / 1024**2


# ---------------------------------------------------------------------------
# eval items + probes
# ---------------------------------------------------------------------------


def load_eval_items() -> list[dict]:
    items = []
    seen = set()
    if EVAL_RAW.exists():
        with open(EVAL_RAW, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = (r.get("benchmark"), r.get("item_id"))
                if not all(key) or key in seen:
                    continue
                seen.add(key)
                items.append(
                    {
                        "benchmark": r["benchmark"],
                        "item_id": r["item_id"],
                        "ctx": r.get("ctx") or "",
                        "gold_text": r.get("gold_text"),
                        "gold_idx": r.get("gold") if isinstance(r.get("gold"), int) else None,
                        "options": r.get("options"),
                        "kind": r.get("kind"),
                    }
                )
    for it in ORION_ITEMS:
        base = "orion-set-" + ("comp" if it["kind"] == "completion" else "mc")
        key = ("orion", base + "-" + normalize_key(it["prompt"])[:24])
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "benchmark": "orion",
                "item_id": key[1],
                "ctx": it["prompt"],
                "gold_text": it["answer"] if it["kind"] == "completion" else None,
                "gold_idx": None if it["kind"] == "completion" else it["answer"],
                "options": None if it["kind"] == "completion" else it["options"],
                "kind": it["kind"],
            }
        )
    return items


def build_probes(items) -> list[tuple[tuple, str, str, str, int]]:
    """Returns (key, field, item_id, text, n_tokens) for every meaningful probe.

    Evaluators score (ctx, option) pairs, so the real text under test is the
    full sentence; a winogrande ctx is just a prefix ("People think ") and only
    becomes a sentence with an option attached.
    """
    out = []
    for it in items:
        b, iid = it["benchmark"], it["item_id"]
        ctx = it["ctx"]
        opts = it["options"]
        gold_i = it["gold_idx"]
        if opts:
            full = [ctx + " " + o.strip() for o in opts]
            gi = max(0, gold_i or 0)
            # gold sentence + the other candidate sentences for this item
            for j, sent in enumerate(full):
                field = "gold" if j == gi else f"opt{j}"
                out.append(((b, field, iid), field, iid, sent, 0))
            if b == "orion" and it["kind"] == "completion" and it["gold_text"]:
                out.append(((b, "gold", iid), "gold", iid, it["gold_text"], 0))
        else:
            if ctx:
                out.append(((b, "ctx", iid), "ctx", iid, ctx, 0))
            if it["gold_text"]:
                out.append(((b, "gold", iid), "gold", iid, it["gold_text"], 0))
    for p in out:
        p_l = list(p)
        p_l[4] = len(normalize_key(p[3]).split())
        yield tuple(p_l)


# ---------------------------------------------------------------------------
# 2. verbatim-memorization probe (runs while the model is resident)
# ---------------------------------------------------------------------------


def gen_from_ids(model, ids: list[int], max_new: int) -> list[int]:
    with torch.no_grad():
        out = model.generate(
            input_ids=torch.tensor([ids], dtype=torch.long),
            max_new_tokens=max_new,
            do_sample=False,
            pad_token_id=PAD_ID,
            eos_token_id=EOS_ID,
        )
    return out[0, len(ids):].tolist()


def corpus_prefix_prompts(tokenizer, n=5) -> list[dict]:
    fw = CORPUS_DIR / "train-fw-part-00000.jsonl"
    rows = []
    with open(fw, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
            if len(rows) >= n:
                break
    out = []
    for r in rows:
        text = row_text(r)
        ids = tokenizer.encode(text).ids
        prompt_ids = ids[:32]
        cont = ids[32:64]
        out.append(
            {
                "prompt_ids": prompt_ids,
                "continuation_ids_gt": cont,
                "prompt_text": tokenizer.decode(prompt_ids, skip_special_tokens=True),
                "continuation_text_gt": tokenizer.decode(cont, skip_special_tokens=True),
            }
        )
    return out


def verbatim_probe(model, tokenizer) -> dict:
    prefix_prompts = corpus_prefix_prompts(tokenizer, n=5)
    corpus_res = []
    for i, pp in enumerate(prefix_prompts):
        gen = gen_from_ids(model, pp["prompt_ids"], max_new=32)
        gt = pp["continuation_ids_gt"]
        overlap = next(
            (k for k, (a, b) in enumerate(zip(gen, gt)) if a != b), min(len(gen), len(gt))
        )
        corpus_res.append(
            {
                "prompt": pp["prompt_text"],
                "generated": tokenizer.decode(gen, skip_special_tokens=True)[:220],
                "corpus_continuation": tokenizer.decode(gt, skip_special_tokens=True)[:220],
                "exact_padded_match": gen == gt[: len(gen)] and len(gen) == len(gt),
                "overlap_tokens": overlap,
            }
        )
    orion_prompts = [it for it in ORION_ITEMS if it["kind"] == "completion"][:5]
    orion_res = []
    for it in orion_prompts:
        ids = tokenizer.encode(it["prompt"]).ids[:512]
        gen = gen_from_ids(model, ids, max_new=32)
        orion_res.append(
            {
                "prompt": it["prompt"],
                "generated": tokenizer.decode(gen, skip_special_tokens=True)[:220],
                "gold_answer": it["answer"],
            }
        )
    return {"corpus_prefix": corpus_res, "orion": orion_res}


# ---------------------------------------------------------------------------
# 1. exact-duplicate check: one streaming pass over all train shards
# ---------------------------------------------------------------------------

# probes: list of (key, field, item_id, text)
#  - windowed: probes with >= NGRAM tokens -> 13-gram hash lookup
#  - fragments: probes with < NGRAM tokens -> containment summary only


def build_gram_lookup(windowed_probes, extra_windowed):
    lookup: dict[int, list[dict]] = defaultdict(list)
    for key, field, item_id, text in windowed_probes:
        norm = normalize_key(text)
        toks = norm.split()
        for i in range(len(toks) - NGRAM + 1):
            g = " ".join(toks[i : i + NGRAM])
            lookup[hash(g)].append({"key": (key, field, item_id), "gram": g})
    for gram_str, key in extra_windowed:
        lookup[hash(gram_str)].append({"key": key, "gram": gram_str})
    return lookup


def corpus_exact_scan(lookup, fragments) -> dict:
    t0 = time.time()
    window_hits: dict[tuple, int] = defaultdict(int)     # key -> distinct gram hits
    details: dict[tuple, list] = defaultdict(list)
    frag_present: set[tuple] = set()                     # keys with >=1 fragment match
    n_docs = 0
    for path in sorted(p for p in shard_files() if p.name.startswith("train-")):
        with open(path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    doc = row_text(json.loads(line))
                except json.JSONDecodeError:
                    continue
                n_docs += 1
                norm = normalize_key(doc)
                toks = norm.split()
                if len(toks) >= NGRAM:
                    for i in range(len(toks) - NGRAM + 1):
                        g = " ".join(toks[i : i + NGRAM])
                        refs = lookup.get(hash(g))
                        if refs:
                            if g not in norm:  # hash-collision guard
                                continue
                            for ref in refs:
                                k = ref["key"]
                                if window_hits[k] < 3 and len(details[k]) < 5:
                                    details[k].append(
                                        {"gram": g[:120], "shard": path.name,
                                         "line": line_no}
                                    )
                                window_hits[k] += 1
                for fkey, fnorm in fragments:
                    if fkey not in frag_present and fnorm in norm:
                        frag_present.add(fkey)
    return {
        "docs_scanned": n_docs,
        "seconds": round(time.time() - t0, 1),
        "window_hits": {f"{a}|{b}|{c}": n for (a, b, c), n in window_hits.items()},
        "window_hit_keys": [f"{a}|{b}|{c}" for (a, b, c) in window_hits],
        "details": {f"{a}|{b}|{c}": v for (a, b, c), v in details.items()},
        "fragment_present_keys": [f"{a}|{b}|{c}" for (a, b, c) in frag_present],
        "fragment_present_count": len(frag_present),
    }


# ---------------------------------------------------------------------------
# 3. near-duplicate check (sample of 20 items vs 1/40 corpus row sample)
# ---------------------------------------------------------------------------


def bigrams(toks):
    return set(zip(toks, toks[1:]))


def corpus_row_sample(step=40) -> list[str]:
    rows = []
    for path in sorted(p for p in shard_files() if p.name.startswith("train-")):
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                if i % step == 0:
                    try:
                        rows.append(row_text(json.loads(line)))
                    except json.JSONDecodeError:
                        continue
    return rows


def near_dup_check(items) -> dict:
    rng = random.Random(4242)
    sample = rng.sample(items, min(20, len(items)))
    rows = corpus_row_sample(step=40)
    rownorm = [normalize_key(r) for r in rows]
    per_item = []
    worst = []
    for it in sample:
        opts = it["options"]
        text = it["ctx"]
        if opts:
            text = it["ctx"] + " " + (opts[max(0, it["gold_idx"] or 0)] if opts else "")
        elif it["gold_text"]:
            text = it["ctx"] + " " + it["gold_text"]
        text = normalize_key(text)
        toks = text.split()
        if len(toks) < 2:
            continue
        bg = bigrams(toks)
        best = 0.0
        best_row = ""
        for rn in rownorm:
            rtoks = rn.split()
            if len(rtoks) < 2:
                continue
            rbg = bigrams(rtoks)
            if not rbg:
                continue
            jac = len(bg & rbg) / len(bg | rbg)
            if jac > best:
                best = jac
                best_row = rn[:140]
        per_item.append(
            {
                "benchmark": it["benchmark"],
                "item_id": it["item_id"],
                "max_bigram_jaccard": round(best, 4),
                "nearest_corpus_row": best_row,
            }
        )
        if best > 0.8:
            worst.append(it["item_id"])
    return {
        "sample_size": len(sample),
        "corpus_rows_sampled": len(rows),
        "sample_step": 40,
        "per_item": per_item,
        "items_flagged_possible_near_dup": worst,
        "max_over_sample": round(max((p["max_bigram_jaccard"] for p in per_item), default=0.0), 4),
        "note": "ponytail: 1/40 row sample, not an exhaustive scan; near-dup is a "
        "bounded approximate net for cheap triage, upgrade to a full index if "
        "any hits approach 0.8.",
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    torch.set_num_threads(6)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    print(f"[RUN] F5 memorization checks | ckpt={CKPT_DIR} | avail RAM {ram_mb():.0f} MB")

    items = load_eval_items()
    print(f"[0] eval items loaded: {len(items)}")

    model, _cfg, step, _l, n_params, _note = load_model_from_checkpoint(CKPT_DIR)
    tokenizer = load_tokenizer()
    print(f"[A] model loaded step={step} params={n_params:,} | RSS {rss_mb():.0f} MB")

    verbatim = verbatim_probe(model, tokenizer)
    print(f"[A] verbatim probe done: {len(verbatim['corpus_prefix'])} corpus-prefix + "
          f"{len(verbatim['orion'])} orion generations")
    del model
    gc.collect()
    print(f"[A] model freed | RSS {rss_mb():.0f} MB | avail {ram_mb():.0f} MB")

    # probe gate: >= NGRAM tokens -> windowed leg, else fragment summary
    all_probes = list(build_probes(items))
    n_probes_by_field: dict[str, int] = defaultdict(int)
    windowed, fragments = [], []
    for key, field, iid, text, ntok in all_probes:
        n_probes_by_field[field] += 1
        if ntok >= NGRAM:
            windowed.append((key, field, iid, text))
        else:
            fragments.append((key, normalize_key(text)))
    print(f"[B] probes: windowed(>= {NGRAM} tok)={len(windowed)} fragments={len(fragments)} "
          f"fields={dict(n_probes_by_field)}")

    # ORION-generated continuations join the exact-dup scan as corpus-match probes
    extra_windowed = []
    for j, o in enumerate(verbatim["orion"]):
        norm = normalize_key(o["generated"])
        toks = norm.split()
        if len(toks) >= NGRAM:
            for i in range(len(toks) - NGRAM + 1):
                extra_windowed.append(
                    (" ".join(toks[i : i + NGRAM]),
                     ("orion_generation", "gen", o["prompt"]))
                )

    lookup = build_gram_lookup(windowed, extra_windowed)
    print(f"[B] gram lookup built: {len(lookup)} hashes")
    scan = corpus_exact_scan(lookup, fragments)
    print(f"[B] corpus scan done: {scan['docs_scanned']} docs in {scan['seconds']}s | "
          f"windowed hit keys: {len(scan['window_hit_keys'])} | "
          f"fragment present keys: {scan['fragment_present_count']}")

    per_bench: dict[str, int] = defaultdict(int)
    for k in scan["window_hit_keys"]:
        per_bench[k.split("|")[0]] += 1
    orion_gen_hits = {k: n for k, n in scan["window_hits"].items() if k.startswith("orion_generation")}

    near = near_dup_check(items)
    print(f"[C] near-dup: max bigram Jaccard over {near['sample_size']} items = "
          f"{near['max_over_sample']}")

    payload = {
        "timestamp": TS,
        "elapsed_seconds": round(time.time() - t0, 1),
        "method": "13-token rolling n-gram set (hash, substring-verified) over train-* "
        "shards in ONE pass; check_leak-style per-item scan NOT used for speed. "
        "Probe gate: only strings with >= 13 tokens count as contamination evidence.",
        "eval_items": {"n": len(items)},
        "probes": {
            "total": len(all_probes),
            "windowed": len(windowed),
            "fragments": len(fragments),
            "by_field": dict(n_probes_by_field),
            "fragment_gate_note": "fragments (< 13 tokens: single-word ARC answers, "
            "winogrande prefixes, ORION completion prompts/answers) are reported "
            "only as uninformative presence; they are NOT contamination evidence",
        },
        "exact_duplicate": {
            "ngram_tokens": NGRAM,
            "docs_scanned": scan["docs_scanned"],
            "seconds": scan["seconds"],
            "window_hits": scan["window_hits"],
            "window_hit_keys": scan["window_hit_keys"],
            "hit_keys_per_benchmark": dict(per_bench),
            "details": scan["details"],
            "orion_generation_corpus_hits": orion_gen_hits,
            "fragment": {
                "fragment_present_keys": scan["fragment_present_keys"],
                "fragment_present_count": scan["fragment_present_count"],
                "uninformative": True,
            },
            "f4_cross_reference": "F4 contamination_report.json reported 0 hits; "
            "this is the brute-force windowed double-check",
        },
        "verbatim_memorization": {
            "exact_continuation_match_count": sum(
                1 for r in verbatim["corpus_prefix"] if r["exact_padded_match"]
            ),
            "corpus_prefix": verbatim["corpus_prefix"],
            "orion": verbatim["orion"],
        },
        "near_duplicate": near,
        "tmp_created": [],
    }
    out = OUT_DIR / "memorization.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[OUT] wrote {out}")
    print(f"  windowed hits: {scan['window_hits']} | per-benchmark: {dict(per_bench)}")
    print(f"  verbatim exact matches: {payload['verbatim_memorization']['exact_continuation_match_count']}/5")
    print(f"  near-dup max sim: {near['max_over_sample']} | flagged: {near['items_flagged_possible_near_dup']}")
    print(f"  elapsed {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())