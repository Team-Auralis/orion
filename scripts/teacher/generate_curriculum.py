#!/usr/bin/env python3
"""Generate a teacher curriculum with the local Ollama model (qwen2.5:3b).

The teacher answers a fixed, seedable list of questions across general
knowledge, arithmetic, reasoning, and brief explanations. The output JSONL
(data/training/teacher_curriculum.jsonl) is what ORION is later distilled on:
one row per (instruction, response) pair, in a simple chat format that ORION's
BPE tokenizer can represent.

Honest guardrail: each answer is pulled live from the teacher (never hand
written) and the file keeps the teacher name + temperature + question id so the
dataset is fully reproducible.
"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import requests


# Windows consoles default to cp1252; teacher answers can contain unicode
# (subscripts, quotes). Printing must not crash even if the console can't
# encode a glyph.
def safe_print(s: str) -> None:
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("ascii", "replace").decode("ascii"))


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "data" / "training" / "teacher_curriculum.jsonl"
OLLAMA = "http://localhost:11434/api/generate"

QUESTIONS = [
    "What is 12 * 9?",
    "What is 17 * 43?",
    "What is 156 / 4?",
    "What is 7% of 240?",
    "Explain in one sentence what photosynthesis is.",
    "Explain in one sentence what a black hole is.",
    "What is the capital of Japan?",
    "What is the capital of Australia?",
    "Which planet is known as the Red Planet?",
    "What is the largest ocean on Earth?",
    "Name the first three prime numbers.",
    "Is 97 a prime number?",
    "What is the square root of 144?",
    "Convert 2.5 hours into minutes.",
    "If apples cost 30 cents each, how much do 12 apples cost?",
    "What is water made of?",
    "Which gas do plants absorb from the air?",
    "What is the main ingredient in most bread?",
    "Which organ pumps blood in the human body?",
    "Explain what an algorithm is in one sentence.",
    "Explain what a variable is in programming.",
    "What does CPU stand for?",
    "What does RAM stand for?",
    "Translate 'good morning' into French.",
    "Translate 'thank you' into Spanish.",
    "What is the freezing point of water in Celsius?",
    "What is the boiling point of water in Celsius?",
    "About how far is the Earth from the Moon in kilometers?",
    "Which country grows the most coffee?",
    "What is the tallest mountain in the world?",
    "What is a habitat?",
    "Which animal is known as man's best friend?",
    "What continent is Egypt in?",
    "What is the currency of the United States?",
    "How many sides does a hexagon have?",
    "What is the sum of angles in a triangle?",
    "What is 8 to the power of 2?",
    "If you have 100 cookies and share them equally among 4 friends, how many does each friend get?",
    "What is the opposite of hot?",
]


def teacher_answer(
    question: str, model: str, temperature: float, timeout: int = 180
) -> str:
    """Pull one answer from the local Ollama model (no streaming)."""
    resp = requests.post(
        OLLAMA,
        json={
            "model": model,
            "prompt": question,
            "stream": False,
            "temperature": temperature,
            "options": {"num_predict": 120},
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json().get("response", "").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen2.5:3b")
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--out", type=str, default=str(DEFAULT_OUT))
    ap.add_argument(
        "--every", type=int, default=1, help="only ask every Nth question (1=all)"
    )
    args = ap.parse_args()

    rows = []
    run_id = uuid.uuid4().hex[:8]
    t0 = time.time()
    for idx, q in enumerate(QUESTIONS):
        if idx % args.every != 0:
            continue
        try:
            a = teacher_answer(q, args.model, args.temperature)
        except Exception as e:
            print(f"[WARN] q{idx} failed: {e}")
            continue
        row = {
            "id": f"cur-{run_id}-{idx}",
            "teacher": args.model,
            "temperature": args.temperature,
            "instruction": q,
            "response": a,
        }
        rows.append(row)
        safe_print(f"  [{idx}] {q} -> {a[:60]}")
        time.sleep(0.05)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    manifest = {
        "run_id": run_id,
        "model": args.model,
        "temperature": args.temperature,
        "count": len(rows),
        "duration_s": round(time.time() - t0, 1),
        "out": str(out),
        "git_commit": None,
    }
    meta = out.with_suffix(".meta.json")
    with open(meta, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"\n[OUT] {len(rows)} rows -> {out}")
    print(f"[META] {meta}")


if __name__ == "__main__":
    main()
