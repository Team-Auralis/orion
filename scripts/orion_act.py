#!/usr/bin/env python3
"""ORION screen-actions: confirm-first, whitelisted actions on your screen.

Only commands in the whitelist run, and ONLY after you type `y` at the prompt.
ORION never derives an action from text found on screen on its own - you type
the intent, ORION executes the whitelisted verb on your confirmation, then
re-captures the screen so it can describe what changed.

    python scripts/orion_act.py

    > see
    > open https://github.com/Team-Auralis/orion
      plan: open https://github.com/Team-Auralis/orion
      confirm? [y/N] y
      ...
    > quit
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

LOG_PATH = REPO_ROOT / "logs" / "orion_actions.jsonl"


def _log(command: str, confirmed: bool, result: str = "", error: str = "") -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": command,
        "confirmed": confirmed,
        "result": result,
        "error": error,
    }
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _pyautogui_available() -> bool:
    try:
        import pyautogui  # noqa: F401

        return True
    except ImportError:
        return False


def _capture_and_describe() -> str:
    from orion_runner.screen import see

    return see()


def _open_os(target: str) -> str:
    """Open an app/URL/file with the OS default (zero dependencies)."""
    os.startfile(target.strip())
    return f"os.startfile({target.strip()!r})"


def _type_text(text: str) -> str:
    import pyautogui

    pyautogui.write(text, interval=0.05)
    return f"typed {text[:40]!r}"


def _press_key(key: str) -> str:
    import pyautogui

    pyautogui.press(key.strip())
    return f"pressed {key.strip()!r}"


def _click() -> str:
    import pyautogui

    pyautogui.click()
    return "clicked at current mouse position"


# verb -> (handler, needs_pyautogui, blurb)
ACTIONS = {
    "open": (_open_os, False, "open <app|url|file> (os.startfile, zero deps)"),
    "type": (_type_text, True, "type <text> into the focused window"),
    "key": (_press_key, True, "key <name> (enter, esc, tab, ...)"),
    "click": (_click, True, "click (at current mouse position)"),
}


def main():
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
            for verb, (_, _needs, blurb) in ACTIONS.items():
                print(f"  {verb}: {blurb}")
            print("  see: capture + describe the current screen")
            continue
        if low == "see":
            print(_capture_and_describe())
            continue

        verb, _, rest = line.partition(" ")
        verb = verb.lower()
        if verb not in ACTIONS:
            print(f"[SKIP] '{verb}' is not a whitelisted action; try: help")
            _log(line, False, result="", error="not in whitelist")
            continue

        handler, needs_pyautogui, _blurb = ACTIONS[verb]
        if needs_pyautogui and not _pyautogui_available():
            print("[BLOCKED] this action needs pyautogui (pip install pyautogui)")
            _log(line, False, error="pyautogui not installed")
            continue

        plan = f"{verb} {rest}".strip()
        confirm = input(f"  plan: {plan}\n  confirm? [y/N] ").strip().lower()
        if confirm != "y":
            print("  [ABORTED]")
            _log(line, False, error="user aborted")
            continue

        try:
            result = handler(rest) if verb != "click" else handler()
            time.sleep(1)
            post = _capture_and_describe()
            caption = post.splitlines()[-1] if post else ""
            _log(line, True, result=result)
            print(f"  [DONE] {result}")
            print(post)
        except Exception as exc:  # noqa: BLE001 - report and keep the loop alive
            _log(line, True, error=str(exc))
            print(f"  [ERROR] {exc}")


if __name__ == "__main__":
    main()
