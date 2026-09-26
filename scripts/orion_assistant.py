#!/usr/bin/env python3
"""ORION assistant: say what you want in plain words; ORION routes it.

Screen intents (see / open / type / key / click) run through the
whitelisted, confirm-first action loop from orion_runner/actions.py. Any
other text is answered honestly - ORION-100M instruction-following is not
reliable enough to fake free-form reasoning, so the assistant says so
instead of pretending.

    python scripts/orion_assistant.py
    > see
    > open chrome
    > open https://github.com/Team-Auralis/orion
    > type hello world
    > key enter
    > quit
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

SCREEN_VERBS = {"open", "type", "key", "click"}


def main():
    from orion_runner.actions import ACTIONS, execute
    from orion_runner.screen import see

    print(
        "ORION assistant: see | open <app|url> | type <text> | key <name> | "
        "click | help | quit"
    )
    while True:
        try:
            line = input("you> ").strip()
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

        # Route screen intents first (whitelist, confirm-first).
        first = low.split()[0]
        if first in SCREEN_VERBS or low == "see":
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
            continue

        # Everything else: honest answer, no fake free-form reasoning.
        print(
            "[TEXT] I can act on screen commands: see | open | type | key | "
            "click. Free-form reasoning by ORION-100M is not wired yet (its "
            "instruction-following is still in training). Try: open chrome"
        )


if __name__ == "__main__":
    main()
