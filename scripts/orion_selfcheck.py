#!/usr/bin/env python3
"""ORION runner self-check (honest): exercises classifier + router layers.

Same pattern as orion_runner/vision.py and gen.py self-checks: run it and
read PASS/FAIL lines. Nothing here fires a real action (confirm_fn always
returns False, so every action attempt is recorded ABORTED) and nothing
captures the screen (see-verbs are checked at classifier level only).

    python scripts/orion_selfcheck.py
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

FAILED = []


def check(label: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    if not cond:
        FAILED.append(label)
    print(f"  [{tag}] {label}" + (f" | {detail}" if detail else ""))


def no_confirm(plan: str) -> bool:
    return False


def main() -> int:
    from orion_runner.actions import match_by_prefix
    from orion_runner.vision_actions import classify
    from scripts.orion_assistant import route_once

    print("== classifier layer (vision_actions.classify) ==")
    cases = [
        ("open the browser", "open"),
        ("what's on my screen", "see"),
        ("type hello world", "type"),
        ("show me the browser", "open"),
    ]
    for phrase, want in cases:
        v = classify("", phrase, min_conf=0.55)
        check(
            f"classify {phrase!r}",
            v["verb"] == want,
            f"got {v['verb']} conf={v['confidence']:.2f}",
        )

    print("== prefix rule layer (actions.match_by_prefix) ==")
    for phrase, want in [
        ("launch notepad", "open"),
        ("press enter", "key"),
        ("click", "click"),
        ("what's on my screen", "see"),
        ("start the calculator", "open"),
    ]:
        got = match_by_prefix(phrase)
        check(f"rule {phrase!r}", got is not None and got[0] == want, f"got {got}")

    print("== router layer (assistant.route_once, no-confirm) ==")
    for phrase, want_sub in [
        ("launch notepad", "[RULE:open]"),
        ("press enter", "[RULE:key]"),
        ("click", "[RULE:click]"),
        ("show me the browser", "[CLASSIFY:open"),
        ("open https://example.com", "[ABORTED]"),
        ("tell me a joke", "[TEXT]"),
    ]:
        msg = route_once(phrase, no_confirm)
        check(f"route {phrase!r}", want_sub in msg, f"-> {msg[:70]}")

    print("==")
    if FAILED:
        print(f"RESULT: {len(FAILED)} FAILED -> {FAILED}")
        return 1
    print("RESULT: all checks PASSED (classifier 4/4, rules 5/5, router 6/6)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
