#!/usr/bin/env python3
"""Eval the ORION vision-action SFT: does ORION pick a whitelisted verb?

Loads the base 100M + the trained LoRA adapter, generates an answer for each
held-out row, and checks the FIRST token against the whitelist and against
the expected action's head verb.

    python scripts/training/eval_vision_actions.py --adapter models/comp001/100m-vision-actions
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

WHITELIST = {"see", "open", "type", "key", "click"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", required=True)
    ap.add_argument(
        "--eval",
        default=str(REPO_ROOT / "data" / "training" / "vision_actions_eval.jsonl"),
    )
    ap.add_argument("--max-new-tokens", type=int, default=12)
    ap.add_argument("--do-sample", action="store_true")
    args = ap.parse_args()

    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    base_dir = REPO_ROOT / "models" / "comp001" / "100m-real"
    tokenizer = AutoTokenizer.from_pretrained(base_dir, local_files_only=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    base = AutoModelForCausalLM.from_pretrained(
        base_dir, dtype="float32", local_files_only=True, low_cpu_mem_usage=True
    )
    model = PeftModel.from_pretrained(base, Path(args.adapter))
    model.eval()

    import torch

    rows = [
        json.loads(l)
        for l in Path(args.eval).read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    correct = 0
    in_whitelist = 0
    for r in rows:
        prompt = f"Q: {r['instruction']}\nA: "
        expected = r["response"].split()[0]
        inputs = tokenizer(prompt, return_tensors="pt")
        inputs.pop("token_type_ids", None)
        with torch.no_grad():
            out = model.generate(
                **inputs,
                max_new_tokens=args.max_new_tokens,
                do_sample=args.do_sample,
            )
        text = tokenizer.decode(
            out[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True
        )
        first = text.strip().split()[0].lower() if text.strip() else "(empty)"
        ok_verb = first in WHITELIST
        ok_exact = first == expected
        in_whitelist += int(ok_verb)
        correct += int(ok_exact)
        print(
            f"  expected={expected:6s} got={first:12s} whitelist={ok_verb} exact={ok_exact}"
            f" raw={text.strip()[:40]!r}"
        )

    n = len(rows)
    print(
        f"[EVAL] {correct}/{n} head-verb exact ({correct / n:.0%}) | "
        f"{in_whitelist}/{n} whitelisted ({in_whitelist / n:.0%})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
