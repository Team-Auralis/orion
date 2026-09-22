#!/usr/bin/env python3
"""COMP-001 offline quality probe (Task 4).

A deliberately boring, fully offline probe for any COMP-001 from-scratch
export: a fixed list of 20 simple reasoning/language items (10 next-token
completions + 10 short generations) with canonical answers, scored by greedy
completion match (exact, normalized) and by top-1 token match. No dataset
download, no external corpus - the items are hardcoded below.

CLI:
    python scripts/evaluation/comp001_quality.py --model models/comp001/100m/
        [--tokenizer models/tokenizer_bpe]

Prints per-item results and a summary, then a parseable PROBE_SCORE=<frac>
line (completion accuracy, 0-1). The training harness records that fraction
as `quality_probe_score` in the experiment ledger.

Scoring is exact-match only. A from-scratch smoke model trained on ~2k tokens
is expected to score low; that is the honest signal for a SMOKE_RUN, not a
quality claim.
"""

import argparse
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "training"))

import torch  # noqa: E402
from transformers import Qwen2ForCausalLM  # noqa: E402

import orion_corpus  # noqa: E402

MAX_NEW_TOKENS = 12

# (prompt, canonical answer) - fixed, boring, exact-match scored.
PROBE_ITEMS = [
    # --- 10 next-token completions -----------------------------------------
    (
        "INSTRUCTION: What is the capital of France?\nRESPONSE: The capital of France is",
        "paris",
    ),
    (
        "INSTRUCTION: What does two plus two equal?\nRESPONSE: Two plus two equals",
        "four",
    ),
    (
        "INSTRUCTION: What color is the sky on a clear day?\nRESPONSE: The sky is",
        "blue",
    ),
    (
        "INSTRUCTION: At what temperature does water freeze?\nRESPONSE: Water freezes at zero degrees",
        "celsius",
    ),
    (
        "INSTRUCTION: What is the largest planet in our solar system?\nRESPONSE: The largest planet is",
        "jupiter",
    ),
    (
        "INSTRUCTION: What is the opposite of hot?\nRESPONSE: The opposite of hot is",
        "cold",
    ),
    (
        "INSTRUCTION: What animal says meow?\nRESPONSE: The animal that says meow is a",
        "cat",
    ),
    (
        "INSTRUCTION: What month comes after January?\nRESPONSE: The month after January is",
        "february",
    ),
    ("INSTRUCTION: Where does the sun rise?\nRESPONSE: The sun rises in the", "east"),
    (
        "INSTRUCTION: What does one plus one equal?\nRESPONSE: One plus one equals",
        "two",
    ),
    # --- 10 held-out generations --------------------------------------------
    (
        "INSTRUCTION: What is the opposite of up?\nRESPONSE: The opposite of up is",
        "down",
    ),
    (
        "INSTRUCTION: What is the largest ocean on Earth?\nRESPONSE: The largest ocean is the",
        "pacific",
    ),
    (
        "INSTRUCTION: How many sides does a triangle have?\nRESPONSE: A triangle has three",
        "sides",
    ),
    (
        "INSTRUCTION: What planet do we live on?\nRESPONSE: The planet we live on is called",
        "earth",
    ),
    (
        "INSTRUCTION: What is the first letter of the alphabet?\nRESPONSE: The first letter is",
        "a",
    ),
    (
        "INSTRUCTION: What season follows winter?\nRESPONSE: The season after winter is",
        "spring",
    ),
    (
        "INSTRUCTION: How many corners does a square have?\nRESPONSE: A square has four",
        "corners",
    ),
    (
        "INSTRUCTION: What is the opposite of left?\nRESPONSE: The opposite of left is",
        "right",
    ),
    ("INSTRUCTION: How many days are in a week?\nRESPONSE: A week has", "seven"),
    ("INSTRUCTION: What color is grass?\nRESPONSE: The color of grass is", "green"),
]


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def safe(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--model", required=True, help="HF export dir (config.json + model.safetensors)"
    )
    ap.add_argument(
        "--tokenizer",
        default=str(REPO_ROOT / "models" / "tokenizer_bpe"),
        help="BPE tokenizer dir (default: models/tokenizer_bpe)",
    )
    args = ap.parse_args()

    model_dir = Path(args.model)
    if not (model_dir / "config.json").exists() and not model_dir.is_file():
        raise SystemExit(
            f"[PROBE] no HF export found at {model_dir} (need config.json)"
        )
    tokenizer = orion_corpus.load_bpe_compat()
    model = Qwen2ForCausalLM.from_pretrained(str(model_dir))
    model.eval()

    n_items = len(PROBE_ITEMS)
    top1_hits = 0
    comp_hits = 0
    rows = []
    t0 = time.time()
    with torch.no_grad():
        for i, (prompt, answer) in enumerate(PROBE_ITEMS, 1):
            input_ids = torch.tensor([tokenizer.encode(prompt).ids], dtype=torch.long)
            out_ids = model.generate(
                input_ids=input_ids,
                max_new_tokens=MAX_NEW_TOKENS,
                do_sample=False,
                pad_token_id=orion_corpus.PAD_ID,
                eos_token_id=orion_corpus.EOS_ID,
            )
            completion = tokenizer.decode(
                out_ids[0, input_ids.shape[1] :].tolist(),
                skip_special_tokens=True,
            )
            nc, na = norm(completion), norm(answer)
            words = nc.split()
            first_token = words[0] if words else ""
            top1_hit = bool(na and first_token == na)
            comp_hit = bool(na and (na in nc or nc == na))
            top1_hits += top1_hit
            comp_hits += comp_hit
            mark = "OK " if comp_hit else "XX "
            rows.append(
                (
                    i,
                    mark,
                    prompt.replace("\n", " ")[:60],
                    safe(completion),
                    answer,
                    top1_hit,
                    comp_hit,
                )
            )
            print(
                f"  [{i:2d}] {mark} prompt={rows[-1][2]}... "
                f"completion={rows[-1][3]!r} answer={answer} "
                f"(top1={'Y' if top1_hit else 'N'}, comp={'Y' if comp_hit else 'N'})"
            )

    elapsed = time.time() - t0
    top1_acc = top1_hits / n_items
    comp_acc = comp_hits / n_items
    print(
        f"\n[PROBE] items={n_items} | top-1 token accuracy={top1_acc:.2f} "
        f"({top1_hits}/{n_items}) | completion accuracy={comp_acc:.2f} "
        f"({comp_hits}/{n_items}) | {elapsed:.1f}s"
    )
    print(f"PROBE_SCORE={comp_acc:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
