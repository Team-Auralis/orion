#!/usr/bin/env python3
"""ORION screen-actions: confirm-first, whitelisted actions on your screen.

Thin CLI over orion_runner/actions.py. Only whitelisted verbs run, and only
after you type `y` at the confirm prompt. Sessions log to
logs/orion_actions.jsonl.

    python scripts/orion_act.py
    > see
    > open https://github.com/Team-Auralis/orion
    > quit
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def main():
    from orion_runner.actions import ACTIONS, execute
    from orion_runner.screen import see

    print(
        "ORION screen-actions (confirm-first). see | open <app|url> | "
        "type <text> | key <name> | click | help | quit"
    )
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        low = line.lower()
        if low in ("quit", "q", "exit"):
            break
        if low in ("help", "?"):
            for verb, (_handler, _needs, blurb) in ACTIONS.items():
                print(f"  {verb}: {blurb}")
            print("  see: capture + describe the current screen")
            continue
        if low == "see":
            print(see())
            continue

        verb, _, rest = line.partition(" ")
        ok, message = execute(
            verb,
            rest,
            confirm_fn=lambda plan: (
                input(f"  plan: {plan}\n  confirm? [y/N] ").strip().lower() == "y"
            ),
        )
        print(message)


if __name__ == "__main__":
    main()
