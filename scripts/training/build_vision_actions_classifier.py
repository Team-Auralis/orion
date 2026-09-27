#!/usr/bin/env python3
"""Build the vision-action CLASSIFIER dataset (replaces the generation recipe).

The generation approach failed 3x (0/10 held-out verb accuracy, 3 formats).
This builder emits rows for a classification head instead: input =
screen caption + user intent as plain text, label = whitelisted verb.
ORION never has to *generate*; its encoder + a small head just scores the
5 verbs. Synthetic, deterministic (seed 907), zero teacher calls.

    python scripts/training/build_vision_actions_classifier.py
    -> data/training/vision_actions_cls.jsonl       (train)
    -> data/training/vision_actions_cls_eval.jsonl  (held-out, 2/verb)
"""

import argparse
import json
import random
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED = 907
VERBS = ["see", "open", "type", "key", "click"]

CAPTIONS = [
    "a desktop with a terminal window and a code editor",
    "a browser window with a search bar",
    "a notes application with white text on a dark background",
    "a file explorer with several folders",
    "an empty desktop with a wallpaper",
    "a chat application with a message input box",
    "a settings window with several toggles",
    "a computer screen with a code on it",
    "a web browser showing a news homepage",
    "a terminal window with monospaced text",
    "a video call interface with a camera preview",
    "a music player with a play button",
    "a spreadsheet application with rows of cells",
    "an image viewer showing a photo",
    "a messaging app with a list of conversations",
    "a login page with username and password fields",
    "a pdf reader with a document open",
    "a game window with graphics",
    "a calendar application with a monthly view",
    "an email client with an inbox",
    "a desktop with a clock and a taskbar",
    "a slideshow presentation with a title slide",
    "a map application with a highlighted route",
    "a shopping website with product images",
    "a video player with playback controls",
    "a folder window with documents",
]

# intent text -> verb (lexical cues are deliberately varied)
INTENTS = [
    ("see what's on my screen", "see"),
    ("look at the screen", "see"),
    ("describe the screen", "see"),
    ("what can you see", "see"),
    ("tell me what is displayed", "see"),
    ("open chrome", "open"),
    ("open the browser", "open"),
    ("open notepad", "open"),
    ("open my documents folder", "open"),
    ("open the project", "open"),
    ("open https://github.com", "open"),
    ("open the settings", "open"),
    ("launch the terminal", "open"),
    ("open the calculator", "open"),
    ("start the email app", "open"),
    ("open the calendar", "open"),
    ("type hello", "type"),
    ("write my name", "type"),
    ("enter the code", "type"),
    ("type your message", "type"),
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
    ap.add_argument("--out", type=str, default=str(REPO_ROOT / "data" / "training"))
    args = ap.parse_args()

    rng = random.Random(SEED)
    rows = []
    for idx, (caption, (intent, verb)) in enumerate(
        (c, pair) for c in CAPTIONS for pair in INTENTS
    ):
        rows.append(
            {
                "id": f"vacls-{idx:04d}",
                "prompt": f"screen: {caption}\nuser: {intent}\naction:",
                "caption": caption,
                "intent": intent,
                "verb": verb,
            }
        )
    rng.shuffle(rows)

    # Held-out: 4 per verb (balanced, never seen in train).
    per_verb: dict[str, list] = {v: [] for v in VERBS}
    for r in rows:
        per_verb[r["verb"]].append(r)
    eval_rows: list[dict] = []
    train_pool: list[dict] = []
    for v in VERBS:
        bucket = per_verb[v]
        rng.shuffle(bucket)
        eval_rows.extend(bucket[:4])
        train_pool.extend(bucket[4:])
    rng.shuffle(train_pool)

    out_dir = Path(args.out)
    with open(out_dir / "vision_actions_cls.jsonl", "w", encoding="utf-8") as f:
        for r in train_pool:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(out_dir / "vision_actions_cls_eval.jsonl", "w", encoding="utf-8") as f:
        for r in eval_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    dist = {v: sum(1 for r in train_pool if r["verb"] == v) for v in VERBS}
    print(
        f"[BUILD] {len(rows)} rows total | train {len(train_pool)} / eval {len(eval_rows)}"
    )
    print(f"[BUILD] train verb dist: {dist}")
    print(f"[BUILD] eval verb dist: { {v: 4 for v in VERBS} }")
    print(f"[BUILD] -> vision_actions_cls.jsonl, vision_actions_cls_eval.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
