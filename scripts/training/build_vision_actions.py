#!/usr/bin/env python3
"""Build the small ORION vision-action SFT dataset.

Synthetic, deterministic rows: a screen *caption* (what Florence-2 would
say) plus a user request, mapping to a whitelisted action verb. This trains
the 100M ORION to pick a valid action from the whitelist given a screen
description + intent - exactly the routing the assistant needs. All rows are
rule-built (no teacher calls), so the experiment is reproducible and cheap.

    python scripts/training/build_vision_actions.py
    -> data/training/vision_actions.jsonl (train+eval, seed 907)
"""

import argparse
import json
import random
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = REPO_ROOT / "data" / "training" / "vision_actions2.jsonl"
EVAL_OUT = REPO_ROOT / "data" / "training" / "vision_actions_eval2.jsonl"
SEED = 907

CAPTIONS = [
    "a desktop with a terminal window and a code editor",
    "a browser window with a search bar",
    "a notes application with white text on a dark background",
    "a file explorer with several folders",
    "an empty desktop with a wallpaper",
    "a chat application with a message input box",
    "a settings window with several toggles",
    "a computer screen with a code on it",
]

# command -> verb (verb-only responses: the whole task is picking the verb)
INTENTS = [
    ("see what's on my screen", "see"),
    ("look at the screen", "see"),
    ("describe the screen", "see"),
    ("what can you see", "see"),
    ("open chrome", "open"),
    ("open the browser", "open"),
    ("open notepad", "open"),
    ("open my documents folder", "open"),
    ("open the project", "open"),
    ("open https://github.com", "open"),
    ("open the settings", "open"),
    ("launch the terminal", "open"),
    ("open the calculator", "open"),
    ("type hello", "type"),
    ("write my name", "type"),
    ("enter the code", "type"),
    ("press enter", "key"),
    ("hit escape", "key"),
    ("press the tab key", "key"),
    ("hit ctrl and s", "key"),
    ("click", "click"),
    ("click the mouse", "click"),
    ("left click", "click"),
    ("click here", "click"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--format3",
        action="store_true",
        help="emit the plain no-scaffold format (screen:/user:/action:)",
    )
    args = ap.parse_args()

    rng = random.Random(SEED)
    rows = []
    for idx, (caption, (cmd, action)) in enumerate(
        (c, pair) for c in CAPTIONS for pair in INTENTS
    ):
        if args.format3:
            # Format #3: no "Q:/A:" scaffolding anywhere. The prompt ends
            # with "action: " and the target IS the verb appended directly.
            instruction = f"screen: {caption}\nuser: {cmd}\naction: "
        else:
            instruction = (
                f"Screen: {caption} | User wants: {cmd} | What should ORION do?"
            )
        rows.append(
            {
                "id": f"va-{idx:03d}",
                "teacher": "template",
                "temperature": 0.0,
                "instruction": instruction,
                "response": action,
            }
        )
    rng.shuffle(rows)

    n_eval = 10
    eval_rows, train_rows = rows[:n_eval], rows[n_eval:]

    out = (
        REPO_ROOT
        / "data"
        / "training"
        / ("vision_actions3.jsonl" if args.format3 else "vision_actions2.jsonl")
    )
    eval_out = (
        REPO_ROOT
        / "data"
        / "training"
        / (
            "vision_actions_eval3.jsonl"
            if args.format3
            else "vision_actions_eval2.jsonl"
        )
    )

    with open(out, "w", encoding="utf-8") as f:
        for r in train_rows:
            f.write(json.dumps(r) + "\n")
    with open(eval_out, "w", encoding="utf-8") as f:
        for r in eval_rows:
            f.write(json.dumps(r) + "\n")

    verbs = {}
    for r in rows:
        v = r["response"].split()[0]
        verbs[v] = verbs.get(v, 0) + 1
    print(
        f"[BUILD] {len(rows)} rows (train {len(train_rows)} / eval {len(eval_rows)}) fmt3={args.format3}"
    )
    print(f"[BUILD] verb distribution: {verbs}")
    print(f"[BUILD] -> {out.name}, {eval_out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
