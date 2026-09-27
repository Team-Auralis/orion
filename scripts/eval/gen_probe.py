#!/usr/bin/env python3
"""Generation probe: the honest held-out / generalization / fluency matrix.

For a given adapter (or the base model), answer every question in the probe
file with greedy decoding (plus an optional sampled pass) and compute
automatic metrics. This turns the three vague claims into numbers:

  - HOLD-OUT GENERATION : latch_rate on heldout_same rows (was the 0/10 A:
    latch claim) - a LATCH is a continuation that starts by re-emitting the
    scaffolding (A:/Q:/user:/screen:) instead of answering.
  - GENERALIZATION      : same metrics on fresh_domain rows + reference-match
    rates (teacher answer contained / exact) on both QA sets.
  - FLUENT GENERATION   : fluency rows have no reference; we measure
    mechanical quality only - clean starts, length, repetition
    (distinct-token ratio), stop-token completion.

Every raw generation is logged; nothing is asserted, everything is recorded.

    python scripts/eval/gen_probe.py --adapter models/comp001/100m-teacher-distill-v7 \
        --tag v7 --data data/eval/gen_probe_questions.jsonl
    python scripts/eval/gen_probe.py --adapter "" --tag base ...
"""

import argparse
import json
import time
from pathlib import Path

import torch

REPO_ROOT = Path(__file__).resolve().parents[2]
LATCH_PREFIXES = ("A:", "Q:", "user:", "screen:")


def normalize(s: str) -> str:
    return " ".join(s.lower().replace("'", " ").replace('"', " ").split())


def next_tokens(s: str, n: int = 3) -> list[str]:
    return normalize(s).split()[:n]


def is_latch(text: str) -> bool:
    t = text.strip()
    return t.startswith(LATCH_PREFIXES)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default="", help="adapter dir; '' = base model")
    ap.add_argument("--tag", required=True, help="short model label for the log")
    ap.add_argument(
        "--data", default=str(REPO_ROOT / "data" / "eval" / "gen_probe_questions.jsonl")
    )
    ap.add_argument("--max-new-tokens", type=int, default=80)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--sampled", action="store_true", help="also do a seeded sampled pass"
    )
    args = ap.parse_args()

    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    base_dir = REPO_ROOT / "models" / "comp001" / "100m-real"
    tokenizer = AutoTokenizer.from_pretrained(base_dir, local_files_only=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    base = AutoModelForCausalLM.from_pretrained(
        base_dir, dtype=torch.float32, local_files_only=True, low_cpu_mem_usage=True
    )
    base.eval()
    adapter = None if args.adapter in ("", "base", "none") else args.adapter
    model = base if adapter is None else PeftModel.from_pretrained(base, adapter)
    model.eval()
    print(f"[MODEL] tag={args.tag} adapter={adapter or 'base'}")

    rows = [
        json.loads(l)
        for l in Path(args.data).read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    out_log = REPO_ROOT / "logs" / f"gen_probe_{args.tag}.jsonl"
    summary: dict = {"tag": args.tag, "adapter": args.adapter, "sets": {}}

    def run_pass(mode: str):
        for r in rows:
            prompt = f"Q: {r['question']}\nA:"
            ids = tokenizer(
                prompt, return_tensors="pt", truncation=True, max_length=128
            )
            ids.pop("token_type_ids", None)
            with torch.no_grad():
                if mode == "greedy":
                    gen = model.generate(
                        **ids,
                        max_new_tokens=args.max_new_tokens,
                        do_sample=False,
                        pad_token_id=tokenizer.pad_token_id,
                        eos_token_id=tokenizer.eos_token_id,
                    )
                else:
                    torch.manual_seed(args.seed)
                    gen = model.generate(
                        **ids,
                        max_new_tokens=args.max_new_tokens,
                        do_sample=True,
                        temperature=0.9,
                        top_p=0.9,
                        pad_token_id=tokenizer.pad_token_id,
                        eos_token_id=tokenizer.eos_token_id,
                    )
            full = tokenizer.decode(gen[0], skip_special_tokens=True)
            cont = full[len(prompt) :]
            cont_tokens = tokenizer.decode(
                gen[0][len(ids.input_ids[0]) :], skip_special_tokens=True
            )
            new_ids = gen[0][len(ids.input_ids[0]) :].tolist()
            stop_reached = tokenizer.eos_token_id in new_ids
            words = cont_tokens.split()
            distinct_ratio = (
                (len(set(w.lower() for w in words)) / len(words)) if words else 0.0
            )
            record = {
                "mode": mode,
                "set": r["set"],
                "category": r["category"],
                "question": r["question"],
                "teacher_answer": r.get("teacher_answer"),
                "generated": full,
                "continuation": cont_tokens,
                "n_new_tokens": len(new_ids),
                "stop_reached": stop_reached,
                "latch": is_latch(cont_tokens),
                "distinct_ratio": round(distinct_ratio, 4),
                "ends_with_punct": bool(cont_tokens.strip().endswith((".", "!", "?"))),
            }
            if r.get("teacher_answer"):
                ta = r["teacher_answer"]
                record["ref_exact"] = normalize(cont_tokens) == normalize(ta)
                record["ref_contain"] = normalize(ta) in normalize(cont_tokens)
                f3 = " ".join(next_tokens(ta, 3))
                record["ref_first3"] = f3 and f3 in normalize(cont_tokens)
            with open(out_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    for mode in ["greedy", "sampled"] if args.sampled else ["greedy"]:
        run_pass(mode)

    # aggregate over the fresh log (so re-runs keep only this tag's rows)
    agg = {}
    for line in out_log.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        if rec["mode"] != "greedy":
            continue
        s = rec["set"]
        a = agg.setdefault(
            s,
            {
                "n": 0,
                "latch": 0,
                "clean": 0,
                "stop": 0,
                "punct": 0,
                "distinct": [],
                "lengths": [],
                "ref_contain": 0,
                "ref_exact": 0,
                "ref_first3": 0,
                "ref_n": 0,
            },
        )
        a["n"] += 1
        a["latch"] += int(rec["latch"])
        a["clean"] += int(not rec["latch"])
        a["stop"] += int(rec["stop_reached"])
        a["punct"] += int(rec["ends_with_punct"])
        a["distinct"].append(rec["distinct_ratio"])
        a["lengths"].append(rec["n_new_tokens"])
        if rec.get("ref_contain") is not None:
            a["ref_n"] += 1
            a["ref_contain"] += int(rec["ref_contain"])
            a["ref_exact"] += int(rec["ref_exact"])
            a["ref_first3"] += int(rec["ref_first3"])
    for s, a in agg.items():
        summary["sets"][s] = {
            "n": a["n"],
            "latch_rate": round(a["latch"] / a["n"], 4),
            "clean_rate": round(a["clean"] / a["n"], 4),
            "stop_rate": round(a["stop"] / a["n"], 4),
            "punct_rate": round(a["punct"] / a["n"], 4),
            "avg_len_tokens": round(sum(a["lengths"]) / a["n"], 1),
            "avg_distinct_ratio": round(sum(a["distinct"]) / a["n"], 4),
            "ref_contain_rate": round(a["ref_contain"] / a["ref_n"], 4)
            if a["ref_n"]
            else None,
            "ref_exact_rate": round(a["ref_exact"] / a["ref_n"], 4)
            if a["ref_n"]
            else None,
            "ref_first3_rate": round(a["ref_first3"] / a["ref_n"], 4)
            if a["ref_n"]
            else None,
        }
    summary_path = REPO_ROOT / "logs" / f"gen_probe_summary_{args.tag}.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"[LOG] {out_log}")
    print(f"[SUMMARY] {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
