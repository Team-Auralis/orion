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

import json
import random
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = REPO_ROOT / "data" / "training" / "vision_actions.jsonl"
EVAL_OUT = REPO_ROOT / "data" / "training" / "vision_actions_eval.jsonl"
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

# command -> (verb, full action)
INTENTS = [
    ("see what's on my screen", "see"),
    ("look at the screen", "see"),
    ("describe the screen", "see"),
    ("what can you see", "see"),
    ("open chrome", "open chrome"),
    ("open the browser", "open chrome"),
    ("open notepad", "open notepad"),
    ("open my documents folder", "open documents"),
    ("open the project", "open d: orion"),
    ("open https://github.com", "open https://github.com"),
    ("open the settings", "open settings"),
    ("launch the terminal", "open terminal"),
    ("open the calculator", "open calculator"),
    ("type hello", "type hello"),
    ("write my name", "type my name"),
    ("enter the code", "type the code"),
    ("press enter", "key enter"),
    ("hit escape", "key esc"),
    ("press the tab key", "key tab"),
    ("hit ctrl and s", "key ctrl+s"),
    ("click", "click"),
    ("click the mouse", "click"),
    ("left click", "click"),
    ("click here", "click"),
]


def main() -> int:
    rng = random.Random(SEED)
    rows = []
    for idx, (caption, (cmd, action)) in enumerate(
        (c, pair) for c in CAPTIONS for pair in INTENTS
    ):
        instruction = f"Screen: {caption} | User wants: {cmd} | What should ORION do?"
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

    with open(OUT, "w", encoding="utf-8") as f:
        for r in train_rows:
            f.write(json.dumps(r) + "\n")
    with open(EVAL_OUT, "w", encoding="utf-8") as f:
        for r in eval_rows:
            f.write(json.dumps(r) + "\n")

    verbs = {}
    for r in rows:
        v = r["response"].split()[0]
        verbs[v] = verbs.get(v, 0) + 1
    print(f"[BUILD] {len(rows)} rows (train {len(train_rows)} / eval {len(eval_rows)})")
    print(f"[BUILD] verb distribution: {verbs}")
    print(f"[BUILD] -> {OUT.name}, {EVAL_OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
