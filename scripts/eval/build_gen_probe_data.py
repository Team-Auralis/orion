#!/usr/bin/env python3
"""Build the generation-probe eval file (held-out + fresh-domain + fluency).

Held-out-same rows are NEW questions in categories the curriculum already
covers (so the model saw the category, never this exact question).
Fresh-domain rows are categories the curriculum never touches (pure
generalization). Fluency prompts have no reference answer - they only
measure whether text comes out clean (no A: latch, no repetition loop).

Honest guardrail: reference answers are pulled LIVE from the Ollama teacher
at build time (never hand-written), matching generate_curriculum.py.

    python scripts/eval/build_gen_probe_data.py
    -> data/eval/gen_probe_questions.jsonl
"""

import json
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
OLLAMA = "http://localhost:11434/api/generate"
OUT = REPO_ROOT / "data" / "eval" / "gen_probe_questions.jsonl"

HELD_OUT_SAME = [
    ("arithmetic", "What is 13 * 7?"),
    ("arithmetic", "What is 288 / 6?"),
    ("arithmetic", "What is 8% of 125?"),
    ("arithmetic", "What is 5 to the power of 3?"),
    ("arithmetic", "What is 7/8 as a decimal?"),
    ("geography", "What is the capital of Spain?"),
    ("geography", "What is the capital of Portugal?"),
    ("geography", "Which country is the Sahara Desert mostly in?"),
    ("geography", "What is the longest river in the United States?"),
    ("science", "What is the chemical symbol for sodium?"),
    ("science", "Which planet is the third from the Sun?"),
    ("science", "How many legs does an insect have?"),
    ("history", "In which year did World War I begin?"),
    ("history", "Who was the first woman to win a Nobel Prize?"),
    ("language", "Translate 'goodbye' into Spanish."),
    ("everyday", "How many hours are in a week?"),
]

FRESH_DOMAIN = [
    ("programming", "What is an API?"),
    ("programming", "What does recursion mean in programming?"),
    ("programming", "What is the difference between a list and a tuple in Python?"),
    ("physics", "What is the chemical formula for carbon dioxide?"),
    ("physics", "What unit is electric current measured in?"),
    ("literature", "Who wrote 'Pride and Prejudice'?"),
    ("health", "What vitamin is produced by sunlight on the skin?"),
    ("sports", "Which country has won the most FIFA World Cup titles?"),
    ("conversion", "What is the boiling point of water in Fahrenheit?"),
]

FLUENCY = [
    "Hello, how are you?",
    "What can you do?",
    "Tell me about yourself.",
    "What is your name?",
    "Describe a sunny day.",
]


def teacher_answer(question: str, timeout: int = 120) -> str:
    resp = requests.post(
        OLLAMA,
        json={
            "model": "qwen2.5:3b",
            "prompt": question,
            "stream": False,
            "temperature": 0.3,
            "options": {"num_predict": 120},
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json().get("response", "").strip()


def safe_print(s: str) -> None:
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("ascii", "replace").decode("ascii"))


def main() -> int:
    rows = []
    for category, q in HELD_OUT_SAME + FRESH_DOMAIN:
        a = teacher_answer(q)
        rows.append(
            {
                "set": "heldout_same"
                if (category, q) in HELD_OUT_SAME
                else "fresh_domain",
                "category": category,
                "question": q,
                "teacher_answer": a,
            }
        )
        safe_print(f"  [{category}] {q} -> {a[:60]}")
        time.sleep(0.05)
    for q in FLUENCY:
        rows.append(
            {
                "set": "fluency",
                "category": "fluency",
                "question": q,
                "teacher_answer": None,
            }
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    counts = {}
    for r in rows:
        counts[r["set"]] = counts.get(r["set"], 0) + 1
    print(f"[OUT] {len(rows)} rows -> {OUT} | {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
