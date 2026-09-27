#!/usr/bin/env python3
"""ORION generative-failure root-cause investigation (2026-09-27).

One harness, one raw-output dir (logs/gen_root_cause/), every step
reproducible from the frozen v8 checkpoint + the exact 687-row dataset.

  python scripts/eval/root_cause.py repro                          # reproduce 0/16, 0/9, 0%
  python scripts/eval/root_cause.py static                         # tokenizer/round-trip/label align
  python scripts/eval/root_cause.py teacher_forced --tags base     # per-zone teacher-forced diag
  python scripts/eval/root_cause.py decode_sweep                   # greedy/temp/top-k/top-p
  python scripts/eval/root_cause.py compare                        # init vs v7 vs v8 fixed prompts
  python scripts/eval/root_cause.py tiny_overfit                   # memorization control
  python scripts/eval/root_cause.py synth_control                  # larger synthetic-language control
  python scripts/eval/root_cause.py report                         # -> docs/ORION_GENERATION_ROOT_CAUSE.md
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import random
import sys
import time
from pathlib import Path

import torch
import torch.nn.functional as F

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

BASE = REPO_ROOT / "models" / "comp001" / "100m-real"
ADAPTERS = {
    "v7": REPO_ROOT / "models" / "comp001" / "100m-teacher-distill-v7",
    "v8": REPO_ROOT / "models" / "comp001" / "100m-teacher-distill-v8",
}
DATA = REPO_ROOT / "data" / "training" / "teacher_curriculum_merged6.jsonl"
PROBE = REPO_ROOT / "data" / "eval" / "gen_probe_questions.jsonl"
OUT = REPO_ROOT / "logs" / "gen_root_cause"
LATCH_PREFIXES = ("A:", "Q:", "user:", "screen:")
MAX_NEW = 80
SEED = 42

# fixed prompts for compare + decode sweep (2 heldout, 2 fresh, 1 fluency)
FIXED_PROMPTS = [
    ("heldout", "Q: What is 13 * 7?\nA:"),
    ("heldout", "Q: What is the capital of Spain?\nA:"),
    ("fresh", "Q: What is an API?\nA:"),
    ("fresh", "Q: Who wrote 'Pride and Prejudice'?\nA:"),
    ("fluency", "Q: Hello, how are you?\nA:"),
]
SWEEP_PROMPTS = FIXED_PROMPTS[:4]


def save(name: str, obj) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    return p


def load_model(tag: str):
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(BASE, local_files_only=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    base = AutoModelForCausalLM.from_pretrained(
        BASE, dtype=torch.float32, local_files_only=True, low_cpu_mem_usage=True
    )
    base.eval()
    if tag == "base":
        return tok, base
    model = PeftModel.from_pretrained(base, ADAPTERS[tag])
    model.eval()
    return tok, model


def is_latch(text: str) -> bool:
    return text.strip().startswith(LATCH_PREFIXES)


def greedy(tok, model, prompt: str, max_new: int = MAX_NEW):
    ids = tok(prompt, return_tensors="pt", truncation=True, max_length=128)
    ids.pop("token_type_ids", None)
    with torch.no_grad():
        out = model.generate(
            **ids,
            max_new_tokens=max_new,
            do_sample=False,
            pad_token_id=tok.pad_token_id,
            eos_token_id=tok.eos_token_id,
        )
    new_ids = out[0, ids["input_ids"].size(1) :].tolist()
    return new_ids, tok.decode(new_ids, skip_special_tokens=True)


# ---------------------------------------------------------------------------
def cmd_repro(args):
    """Reproduce the committed matrix numbers with frozen v8."""
    import json as _json
    from transformers import AutoTokenizer

    rows = [
        _json.loads(l)
        for l in PROBE.read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    tok, model = load_model("v8")
    recs = []
    for r in rows:
        new_ids, cont = greedy(tok, model, f"Q: {r['question']}\nA:")
        rec = {
            "set": r["set"],
            "question": r["question"],
            "teacher_answer": r.get("teacher_answer"),
            "continuation": cont,
            "latch": is_latch(cont),
            "n_tokens": len(new_ids),
            "stop": tok.eos_token_id in new_ids,
        }
        recs.append(rec)
    agg: dict = {"stop_rate": None}
    for s in ("heldout_same", "fresh_domain", "fluency"):
        sub = [x for x in recs if x["set"] == s]
        agg[f"{s}_latch"] = round(sum(x["latch"] for x in sub) / len(sub), 4)
        agg[f"{s}_ref"] = sum(
            1
            for x in sub
            if x["teacher_answer"]
            and " ".join(x["teacher_answer"].lower().split())
            in " ".join(x["continuation"].lower().split())
        )
    agg["stop_rate"] = round(sum(x["stop"] for x in recs) / len(recs), 4)
    save("repro_v8.json", {"agg": agg, "rows": recs})
    print(json.dumps(agg, indent=2))


# ---------------------------------------------------------------------------
def cmd_static(args):
    from transformers import AutoTokenizer
    from orion_runner.loader import pack_sequences, tokenize_samples
    from scripts.teacher.distill_train import FORMATS, fmt_qa

    tok = AutoTokenizer.from_pretrained(BASE, local_files_only=True)
    rows = [
        json.loads(l)
        for l in DATA.read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    out = {
        "config": {
            "vocab": tok.vocab_size,
            "bos": (tok.bos_token, tok.bos_token_id),
            "eos": (tok.eos_token, tok.eos_token_id),
            "pad": (tok.pad_token, tok.pad_token_id),
        },
        "roundtrip": [],
        "label_alignment": None,
        "format_stats": {},
    }
    # round-trip: random + adversarial
    rng = random.Random(SEED)
    tests = []
    for r in rng.sample(rows, 10):
        tests.append(fmt_qa(r))
    tests += [
        "Q: \nA: ",
        "Q: 42\nA: 42",
        "Q: How are you?\nA: \U0001f600",
        "A: broken format here",
        "Q: " + "z" * 300 + "\nA: y",
        "\n\n\nQ: x\nA: y\n\n",
    ]
    for t in tests:
        ids = tok(t, truncation=True, max_length=512).input_ids
        dec = tok.decode(ids, skip_special_tokens=False)
        out["roundtrip"].append(
            {
                "ok": dec.strip() == t.strip(),
                "text": t[:60],
                "decoded": dec[:60],
                "ids": ids[:12],
            }
        )
    # label alignment: rebuild the exact 137 packed blocks used in training
    packed = pack_sequences(
        tokenize_samples(rows, tok, fmt_qa, 512),
        512,
        pad_id=tok.pad_token_id or 0,
        seed=SEED,
        mask_boundaries=True,
    )
    bad = 0
    checked = 0
    for b in packed:
        ids, labels = b["input_ids"], b["labels"]
        for i in range(1, len(ids)):
            if labels[i] == -100:
                continue
            checked += 1
            # HF shift: target at position i-1 is labels[i]; must equal ids[i]
            if labels[i] != ids[i]:
                bad += 1
    out["label_alignment"] = {
        "n_blocks": len(packed),
        "unmasked_positions_checked": checked,
        "mismatches": bad,
    }
    # how much of a block is format vs content
    fmt_ids = set(tok("Q:").input_ids) | set(tok("\nA:").input_ids)
    tot, fmt = 0, 0
    for b in packed:
        ids = b["input_ids"]
        tot += sum(1 for i in ids if i not in (tok.pad_token_id,))
        fmt += sum(1 for i in ids if i in fmt_ids)
    out["format_stats"] = {
        "block_tokens": tot,
        "format_tokens": fmt,
        "format_pct": round(100 * fmt / tot, 2),
    }
    p = save("static.json", out)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    print("[SAVE]", p)


# ---------------------------------------------------------------------------
def cmd_teacher_forced(args):
    """Teacher-forced diagnostics: can the model REPRODUCE answers when the
    answer is already in the context? Per-zone (format vs answer) metrics."""
    rows_data = [
        json.loads(l)
        for l in DATA.read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    rows_probe = [
        json.loads(l)
        for l in PROBE.read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]

    # unique train questions (first occurrence wins, deterministic order)
    seen = {}
    for r in rows_data:
        seen.setdefault(r["instruction"], r["response"])
    train_items = list(seen.items())[:24]
    probe_items = [
        (r["question"], r.get("teacher_answer"))
        for r in rows_probe
        if r.get("teacher_answer")
    ]

    tok, model = load_model(args.tag)
    results = []
    for q, a in train_items + probe_items:
        text = f"Q: {q}\nA: {a}"
        ids = tok(text, truncation=True, max_length=512).input_ids
        x = torch.tensor([ids])
        with torch.no_grad():
            logits = model(x).logits[0]  # [T, V]
        probs = F.softmax(logits, dim=-1)
        preds = logits.argmax(dim=-1).tolist()
        # find answer zone start
        ans_start = None
        for i in range(len(ids) - 2):
            if ids[i] == 172 and ids[i + 1] == 36 and ids[i + 2] == 29:
                ans_start = i + 3
                break
        if ans_start is None:
            continue
        mask = [i >= ans_start for i in range(len(ids))]

        # loss per zone via HF convention: target at i is ids[i+1]
        def zone_stats(zone_mask):
            tot_loss = 0.0
            tot_acc = 0
            n = 0
            for i in range(len(ids) - 1):
                if not zone_mask[i]:
                    continue
                l = -math.log(probs[i, ids[i + 1]].item() + 1e-12)
                tot_loss += l
                tot_acc += int(preds[i] == ids[i + 1])
                n += 1
            return (
                (tot_loss / max(n, 1), tot_acc / max(n, 1), n) if n else (None, None, 0)
            )

        fl, fa, fn = zone_stats([not m for m in mask])  # format positions
        al, aa, an = zone_stats(mask)  # answer positions
        first_pos = ans_start - 1  # position predicting the FIRST answer token
        first_pred = preds[first_pos] if 0 <= first_pos < len(preds) else None
        first_prob = probs[first_pos].max().item() if first_pos is not None else None
        ent = (
            -float((probs[first_pos] * torch.log(probs[first_pos] + 1e-12)).sum())
            if first_pos is not None
            else None
        )
        top5 = (
            logits[first_pos].topk(5).indices.tolist() if first_pos is not None else []
        )
        results.append(
            {
                "q": q[:60],
                "a": (a or "")[:60],
                "format_loss": fl,
                "format_acc": fa,
                "format_n": fn,
                "answer_loss": al,
                "answer_acc": aa,
                "answer_n": an,
                "first_pred": first_pred,
                "first_target": ids[ans_start] if ans_start < len(ids) else None,
                "first_pred_text": tok.decode([first_pred])
                if first_pred is not None
                else None,
                "first_target_text": tok.decode([ids[ans_start]])
                if ans_start < len(ids)
                else None,
                "first_prob": first_prob,
                "first_entropy": ent,
                "first_top5": [tok.decode([i]) for i in top5],
            }
        )
    agg = {
        "train_format_acc": round(sum(r["format_acc"] for r in results[:24]) / 24, 4),
        "train_answer_acc": round(sum(r["answer_acc"] for r in results[:24]) / 24, 4),
        "probe_format_acc": round(
            sum(r["format_acc"] for r in results[24:]) / len(results[24:]), 4
        ),
        "probe_answer_acc": round(
            sum(r["answer_acc"] for r in results[24:]) / len(results[24:]), 4
        ),
        "train_answer_loss": round(sum(r["answer_loss"] for r in results[:24]) / 24, 4),
        "probe_answer_loss": round(
            sum(r["answer_loss"] for r in results[24:]) / len(results[24:]), 4
        ),
        "first_token_acc": round(
            sum(int(r["first_pred"] == r["first_target"]) for r in results)
            / len(results),
            4,
        ),
    }
    obj = {"tag": args.tag, "agg": agg, "rows": results}
    p = save(f"teacher_forced_{args.tag}.json", obj)
    print(json.dumps(agg, indent=2))
    print("[SAVE]", p)


# ---------------------------------------------------------------------------
def cmd_decode_sweep(args):
    tok, model = load_model("v8")
    results = []
    configs = [
        ("greedy", {}),
        ("temp0.5", {"do_sample": True, "temperature": 0.5}),
        ("temp0.9", {"do_sample": True, "temperature": 0.9}),
        ("topk10", {"do_sample": True, "top_k": 10}),
        ("topk50", {"do_sample": True, "top_k": 50}),
        ("topp0.8", {"do_sample": True, "top_p": 0.8}),
        ("topp0.95", {"do_sample": True, "top_p": 0.95}),
    ]
    for kind, prompt in SWEEP_PROMPTS:
        ids = tok(prompt, return_tensors="pt", truncation=True, max_length=128)
        ids.pop("token_type_ids", None)
        for name, cfg in configs:
            torch.manual_seed(SEED)
            with torch.no_grad():
                kw = {
                    **cfg,
                    "max_new_tokens": 16,
                    "pad_token_id": tok.pad_token_id,
                    "eos_token_id": tok.eos_token_id,
                }
                gen = model.generate(**ids, **kw)
            cont = tok.decode(
                gen[0, ids["input_ids"].size(1) :], skip_special_tokens=True
            )
            results.append(
                {
                    "kind": kind,
                    "prompt": prompt,
                    "cfg": name,
                    "cont": cont[:60],
                    "latch": is_latch(cont),
                }
            )
    rows_sum = {}
    for kind in ("heldout", "fresh"):
        sub = [r for r in results if r["kind"] == kind]
        rows_sum[kind] = {
            "latch_by_cfg": {r["cfg"]: r["latch"] for r in sub},
            "any_clean": any(not r["latch"] for r in sub),
        }
    rows_sum["all_clean_any_cfg"] = any(not r["latch"] for r in results)
    p = save("decode_sweep.json", {"results": results, "summary": rows_sum})
    print(json.dumps(rows_sum, indent=2))
    print("[SAVE]", p)


# ---------------------------------------------------------------------------
def cmd_compare(args):
    rows = []
    for tag in ("base", "v7", "v8"):
        tok, model = load_model(tag)
        for kind, prompt in FIXED_PROMPTS:
            ids = tok(prompt, return_tensors="pt", truncation=True, max_length=128)
            ids.pop("token_type_ids", None)
            steps = []
            cur = {k: v.clone() for k, v in ids.items()}
            with torch.no_grad():
                for _ in range(12):
                    logits = model(**cur).logits[0, -1]
                    top = int(logits.argmax())
                    lp = float(F.log_softmax(logits, dim=-1)[top])
                    steps.append(
                        {"tok": tok.decode([top]), "id": top, "logprob": round(lp, 3)}
                    )
                    cur["input_ids"] = torch.cat(
                        [cur["input_ids"], torch.tensor([[top]])], dim=-1
                    )
                    if "attention_mask" in cur:
                        cur["attention_mask"] = torch.cat(
                            [
                                cur["attention_mask"],
                                torch.ones((1, 1), dtype=torch.long),
                            ],
                            dim=-1,
                        )
                    if top == tok.eos_token_id:
                        break
            cont = "".join(s["tok"] for s in steps)
            rows.append(
                {
                    "tag": tag,
                    "kind": kind,
                    "prompt": prompt[:40],
                    "steps": steps,
                    "cont": cont[:50],
                    "latch": is_latch(cont),
                }
            )
    p = save("compare.json", {"rows": rows})
    for r in rows:
        print(
            f"  {r['tag']:4s} {r['kind']:8s} -> {r['cont'][:50]!r}"
            + ("  [LATCH]" if r["latch"] else "")
        )
    print("[SAVE]", p)


# ---------------------------------------------------------------------------
def build_tiny_rows():
    pairs = [
        ("alpha beta", "zeta eta"),
        ("beta gamma", "eta theta"),
        ("gamma delta", "theta kappa"),
        ("alpha gamma", "zeta theta"),
        ("beta delta", "eta kappa"),
        ("alpha delta", "zeta kappa"),
        ("epsilon alpha", "lambda zeta"),
        ("epsilon gamma", "lambda theta"),
    ]
    return [{"instruction": q, "response": a} for q, a in pairs]


def _find_layers(peft_model):
    """Return the transformer layer list of a PeftModel, tolerant to PEFT version."""
    m = peft_model
    for attr in ("base_model", "model"):
        m = getattr(m, attr, m)
    layers = None
    if hasattr(m, "model") and hasattr(m.model, "layers"):
        layers = m.model.layers
    elif hasattr(m, "layers"):
        layers = m.layers
    elif hasattr(peft_model, "base_model") and hasattr(peft_model.base_model, "model"):
        bm = peft_model.base_model.model
        layers = (
            bm.model.layers
            if hasattr(bm, "model") and hasattr(bm.model, "layers")
            else None
        )
    return layers


def train_control(rows, epochs, tag, max_len=512, gen_rows=None, lr=3e-4):
    """Train a LoRA with the EXACT production code path (pack/loRA/AdamW/clip).

    gen_rows: optional list of dicts (instruction/response) to greedy-generate
    from after training -- exact-match check proves the autoregressive stack.
    """
    from scripts.teacher.distill_train import FORMATS
    from orion_runner.loader import pack_sequences, tokenize_samples
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(BASE, local_files_only=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    base = AutoModelForCausalLM.from_pretrained(
        BASE, dtype=torch.float32, local_files_only=True, low_cpu_mem_usage=True
    )
    lora_cfg = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(base, lora_cfg)
    packed = pack_sequences(
        tokenize_samples(rows, tok, FORMATS["qa"], max_len),
        max_len,
        pad_id=tok.pad_token_id or 0,
        seed=SEED,
        mask_boundaries=True,
    )
    input_ids = torch.tensor([p["input_ids"] for p in packed], dtype=torch.long)
    labels = torch.tensor([p["labels"] for p in packed], dtype=torch.long)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr)

    # activation probe (layer 5) before training
    act_before = {}
    handles = []

    def hook(mod, inp, out):
        if len(act_before) == 0:
            act_before["mean"] = float(out[0].mean())
            act_before["std"] = float(out[0].std())

    # attach to first module of layer 6 (index 5) if exists
    lm = model.base_model.model if hasattr(model, "base_model") else model
    if len(lm.model.layers) > 5:
        handles.append(lm.model.layers[5].register_forward_hook(hook))
        probe = tok("Q: alpha beta\nA: zeta eta", return_tensors="pt").input_ids
        with torch.no_grad():
            model(probe)

    model.train()
    grad_norms = []
    losses = []
    for ep in range(epochs):
        eploss = []
        for xb, yb in zip(input_ids, labels):
            opt.zero_grad()
            out = model(input_ids=xb[None], labels=yb[None])
            out.loss.backward()
            gn = (
                sum(
                    p.grad.norm().item() ** 2
                    for p in model.parameters()
                    if p.grad is not None
                )
                ** 0.5
            )
            torch.nn.utils.clip_grad_norm_(
                [p for p in model.parameters() if p.requires_grad], 1.0
            )
            opt.step()
            grad_norms.append(gn)
            eploss.append(float(out.loss.item()))
        losses.append(sum(eploss) / len(eploss))
    for h in handles:
        h.remove()
    model.eval()

    # activation probe after training (fresh hook)
    act_after = {}
    handles = []

    def hook2(mod, inp, out):
        if len(act_after) == 0:
            act_after["mean"] = float(out[0].mean())
            act_after["std"] = float(out[0].std())

    if len(lm.model.layers) > 5:
        handles.append(lm.model.layers[5].register_forward_hook(hook2))
        with torch.no_grad():
            model(probe)
    for h in handles:
        h.remove()

    # teacher-forced top-1 on every row
    tf_rows = []
    for r in rows:
        text = f"Q: {r['instruction']}\nA: {r['response']}"
        ids = tok(text).input_ids
        x = torch.tensor([ids])
        with torch.no_grad():
            logits = model(x).logits[0]
        pred = logits.argmax(-1).tolist()
        ans_start = next(
            (
                i + 3
                for i in range(len(ids) - 2)
                if ids[i] == 172 and ids[i + 1] == 36 and ids[i + 2] == 29
            ),
            None,
        )
        ok = sum(int(pred[i] == ids[i + 1]) for i in range(len(ids) - 1))
        ans_tokens = len(ids) - ans_start if ans_start else 0
        ans_ok = (
            sum(int(pred[i] == ids[i + 1]) for i in range(ans_start, len(ids) - 1))
            if ans_start
            else 0
        )
        tf_rows.append(
            {
                "q": r["instruction"],
                "a": r["response"],
                "acc": ok / max(len(ids) - 1, 1),
                "answer_acc": ans_ok / max(ans_tokens, 1),
                "answer_n": ans_tokens,
            }
        )
    # greedy generation per prompt (exact autoregressive target check)
    gen_results = []
    for r in gen_rows if gen_rows is not None else rows:
        _, cont = greedy(tok, model, f"Q: {r['instruction']}\nA:", max_new=32)
        want = r["response"]
        got = cont.strip()
        norm = lambda s: " ".join(s.split())
        gen_results.append(
            {
                "q": r["instruction"],
                "want": want,
                "got": got[:60],
                "exact": got == want,
                "exact_norm": norm(got) == norm(want),
                "latch": is_latch(cont),
            }
        )
    exact_n = sum(1 for g in gen_results if g["exact"])
    exact_norm_n = sum(1 for g in gen_results if g["exact_norm"])
    return {
        "tag": tag,
        "n_rows": len(rows),
        "n_gen_rows": len(gen_results),
        "epochs": epochs,
        "lr": lr,
        "losses": [round(x, 4) for x in losses],
        "grad_norms": {
            "mean": round(sum(grad_norms) / len(grad_norms), 5),
            "max": round(max(grad_norms), 5),
            "first": round(grad_norms[0], 5),
            "last": round(grad_norms[-1], 5),
            "nan_or_inf": any(not math.isfinite(g) for g in grad_norms),
        },
        "act_layer5": {"before": act_before, "after": act_after},
        "teacher_forced": tf_rows,
        "generation": gen_results,
        "exact_match_n": exact_n,
        "exact_match_pct": round(100 * exact_n / len(gen_results), 1),
        "exact_norm_n": exact_norm_n,
        "exact_norm_pct": round(100 * exact_norm_n / len(gen_results), 1),
        "train_answer_acc": round(
            sum(t["answer_acc"] for t in tf_rows) / len(tf_rows), 4
        ),
    }


def cmd_tiny_overfit(args):
    rows = build_tiny_rows()
    res = train_control(rows, epochs=args.epochs, tag="tiny_overfit", lr=args.lr)
    ok = res["exact_match_n"] == len(rows) and res["train_answer_acc"] > 0.99
    p = save(f"tiny_overfit_e{args.epochs}_lr{args.lr}.json", res)
    print(json.dumps(res, indent=2, ensure_ascii=False)[:4000])
    print(
        f"\n[VERDICT] tiny_overfit {'PASS' if ok else 'FAIL'} "
        f"(exact {res['exact_match_n']}/{len(rows)}, train-answer-acc {res['train_answer_acc']})"
    )
    print("[SAVE]", p)


# ---------------------------------------------------------------------------
def build_synth_rows():
    """Formal language: 'Q: {op} {x} {y}\nA: {result}' over a small vocab."""
    nums = ["one", "two", "three", "four", "five"]
    results = {"plus": 1, "minus": 1, "times": 4}  # result scales
    op_result = {
        "plus": lambda a, b: a + b,
        "minus": lambda a, b: a - b,
        "times": lambda a, b: a * b,
    }
    name = {
        1: "one",
        2: "two",
        3: "three",
        4: "four",
        5: "five",
        6: "six",
        7: "seven",
        8: "eight",
        9: "nine",
        10: "ten",
        12: "twelve",
        15: "fifteen",
        16: "sixteen",
        20: "twenty",
        25: "twenty five",
    }
    rows = []
    for op in ("plus", "minus", "times"):
        for a in nums:
            for b in nums:
                v = op_result[op](nums.index(a) + 1, nums.index(b) + 1)
                if v <= 0 or v not in name:
                    continue
                rows.append({"instruction": f"{op} {a} {b}", "response": name[v]})
    return rows, name


def cmd_synth_control(args):
    rows, name = build_synth_rows()
    rng = random.Random(SEED)
    rng.shuffle(rows)
    # train on 80%, probe on 20% (unseen pairs, same distribution)
    n_probe = max(1, len(rows) // 5)
    train_rows, probe_rows = rows[n_probe:], rows[:n_probe]
    res = train_control(
        train_rows,
        epochs=args.epochs,
        tag="synth_control",
        gen_rows=probe_rows,
        lr=args.lr,
    )
    res["probe_n"] = len(probe_rows)
    res["probe_train_n"] = len(train_rows)
    res["probe_exact"] = sum(1 for g in res["generation"] if g["exact"])
    res["probe_exact_pct"] = round(
        100 * res["probe_exact"] / max(len(probe_rows), 1), 1
    )
    res["probe_latch"] = sum(1 for g in res["generation"] if g["latch"])
    p = save(f"synth_control_e{args.epochs}_lr{args.lr}.json", res)
    print(json.dumps(res, indent=2, ensure_ascii=False)[:3500])
    print(
        f"\n[VERDICT] synth_control probe exact {res['probe_exact']}/{len(probe_rows)} "
        f"(exact_norm {res['exact_norm_n']}, latch {res['probe_latch']}, "
        f"train-answer-acc {res['train_answer_acc']})"
    )
    print("[SAVE]", p)


def cmd_report(args):
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(BASE, local_files_only=True)
    out = {
        "repro": json.load(open(OUT / "repro_v8.json", encoding="utf-8"))["agg"],
        "static": json.load(open(OUT / "static.json", encoding="utf-8")),
        "tf": {
            t: json.load(open(OUT / f"teacher_forced_{t}.json", encoding="utf-8"))[
                "agg"
            ]
            for t in ("base", "v7", "v8")
        },
        "sweep": json.load(open(OUT / "decode_sweep.json", encoding="utf-8"))[
            "summary"
        ],
        "compare": json.load(open(OUT / "compare.json", encoding="utf-8"))["rows"],
        "tiny_runs": [
            json.load(open(p, encoding="utf-8"))
            for p in sorted(OUT.glob("tiny_overfit_e*.json"))
        ],
        "synth_runs": [
            json.load(open(p, encoding="utf-8"))
            for p in sorted(OUT.glob("synth_control_e*.json"))
        ],
    }
    p = save("report_aggregate.json", out)
    print("[SAVE]", p)


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("repro")
    sub.add_parser("static")
    tf = sub.add_parser("teacher_forced")
    tf.add_argument("--tags", default="base")
    sub.add_parser("decode_sweep")
    sub.add_parser("compare")
    to = sub.add_parser("tiny_overfit")
    to.add_argument("--epochs", type=int, default=40)
    to.add_argument("--lr", type=float, default=3e-4)
    sc = sub.add_parser("synth_control")
    sc.add_argument("--epochs", type=int, default=25)
    sc.add_argument("--lr", type=float, default=3e-4)
    sub.add_parser("report")
    args = ap.parse_args()

    if args.cmd == "repro":
        cmd_repro(args)
    elif args.cmd == "static":
        cmd_static(args)
    elif args.cmd == "teacher_forced":
        for t in args.tags.split(","):
            cmd_teacher_forced(argparse.Namespace(tag=t))
            gc.collect()
    elif args.cmd == "decode_sweep":
        cmd_decode_sweep(args)
    elif args.cmd == "compare":
        cmd_compare(args)
    elif args.cmd == "tiny_overfit":
        cmd_tiny_overfit(args)
    elif args.cmd == "synth_control":
        cmd_synth_control(args)
    elif args.cmd == "report":
        cmd_report(args)


if __name__ == "__main__":
    main()
