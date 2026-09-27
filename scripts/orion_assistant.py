#!/usr/bin/env python3
"""ORION assistant: say what you want in plain words; ORION routes it.

Screen intents (see / open / type / key / click) run through the
whitelisted, confirm-first action loop from orion_runner/actions.py.
Since 2026-09-27 the router also uses the vision-action classifier
(orion_runner/vision_actions.py, VERIFIED 19/20 held-out) so plain-phrase
intents like "launch the browser" or "what's on my screen" route to the
right whitelisted verb instead of bouncing to a dead end.

Any other text is answered honestly - ORION-100M instruction-following is
not reliable enough to fake free-form reasoning.

    python scripts/orion_assistant.py
    > see
    > open chrome
    > launch the browser          # classifier: open
    > what's on my screen         # classifier: see
    > quit

    python scripts/orion_assistant.py --once "launch notepad" --no-confirm
    # non-interactive single phrase (used by smoke tests)
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

SCREEN_VERBS = {"open", "type", "key", "click"}


def route_once(line: str, confirm_fn, last_caption: str = "") -> str:
    """Route ONE user line to an action or an honest answer."""
    from orion_runner.actions import ACTIONS, execute, match_by_prefix, strip_target
    from orion_runner.screen import see
    from orion_runner.vision_actions import classify

    low = line.strip().lower()
    if not low:
        return ""
    if low in ("quit", "q", "exit"):
        return "__QUIT__"
    if low in ("help", "?"):
        out = [f"{verb}: {blurb}" for verb, (_h, _n, blurb) in ACTIONS.items()]
        out.append("see: capture + describe the current screen")
        return "\n".join(out)

    # 1) Explicit whitelist verb first word -> fast path.
    first = low.split()[0]
    if first in SCREEN_VERBS and first != low:
        verb, _, rest = line.partition(" ")
        ok, message = execute(verb, rest, confirm_fn)
        return message
    if low == "see":
        return see()

    # 2) Deterministic prefix layer (launch/start/run -> open, press/hit -> key,
    #    click/select -> click, what/look/describe -> see, ...).
    matched = match_by_prefix(line)
    if matched is not None:
        verb, rest = matched
        if verb == "see":
            return see()
        if verb in ACTIONS and not (verb in ("open", "type", "key") and not rest):
            ok, message = execute(verb, rest, confirm_fn)
            return f"[RULE:{verb}] {message}"
        if verb in ("open", "type", "key"):
            return (
                f"[RULE:{verb}] which {verb} target? I need the app/url/text/key name."
            )

    # 3) Classifier path: plain phrase -> whitelisted verb + target. Uses the
    #    last real screen caption when available (classifier was trained on
    #    real caption distributions), else the neutral placeholder.
    from orion_runner.screen import last_caption as cached_caption

    verdict = classify(last_caption or cached_caption() or "", low, min_conf=0.55)
    if verdict["verb"] is not None:
        verb = verdict["verb"]
        conf = verdict["confidence"]
        if verb == "see":
            return see()
        if verb in ACTIONS:
            rest = strip_target(line)
            if verb in ("open", "type", "key") and not rest:
                return (
                    f"[CLASSIFY:{verb}@{conf:.0%}] which {verb} target? "
                    "I need the app/url/text/key name."
                )
            ok, message = execute(verb, rest, confirm_fn)
            return f"[CLASSIFY:{verb}@{conf:.0%}] {message}"
        return (
            f"[CLASSIFY:{verb}@{conf:.0%}] unsupported verb - whitelist: "
            "see/open/type/key/click"
        )

    # 4) Honest fallback: no confident verb.
    return (
        "[TEXT] I couldn't route that confidently. I can act on screen "
        "commands: see | open | type | key | click | help. "
        "Free-form reasoning by ORION-100M is still in training (honest: "
        "instruction-following UNPROVEN). Try: open chrome"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", help="process a single phrase and exit")
    ap.add_argument(
        "--no-confirm",
        action="store_true",
        help="never confirm actions (auto-abort; used by smoke tests)",
    )
    args = ap.parse_args()

    def confirm_fn(plan: str) -> bool:
        if args.no_confirm:
            return False
        return input(f"  plan: {plan}\n  confirm? [y/N] ").strip().lower() == "y"

    if args.once:
        msg = route_once(args.once, confirm_fn)
        if msg != "__QUIT__":
            print(msg)
        return 0

    from orion_runner.vision_actions import verb_info

    print(verb_info())
    print(
        "ORION assistant: see | open <app|url> | type <text> | key <name> | "
        "click | help | quit (plain phrases routed by classifier)"
    )
    last_caption = ""
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        msg = route_once(line, confirm_fn, last_caption)
        if msg == "__QUIT__":
            break
        print(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
