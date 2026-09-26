"""ORION Runner - screen actions (whitelist, confirm-first).

Single source of truth for the action whitelist used by both
scripts/orion_act.py and scripts/orion_assistant.py. Nothing here ever
acts without the caller's confirm_fn() returning True, and every attempt is
logged to logs/orion_actions.jsonl with its confirmed/aborted/error state.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = REPO_ROOT / "logs" / "orion_actions.jsonl"


def log_action(
    command: str, confirmed: bool, result: str = "", error: str = ""
) -> None:
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


def pyautogui_available() -> bool:
    try:
        import pyautogui  # noqa: F401

        return True
    except ImportError:
        return False


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


def execute(verb: str, rest: str, confirm_fn) -> tuple[bool, str]:
    """Run a whitelisted action after confirm_fn(plan) returns True.

    Returns (ok, message). On success the screen is re-captured and
    described so the caller can report what visibly changed.
    """
    verb = verb.lower()
    if verb not in ACTIONS:
        log_action(f"{verb} {rest}".strip(), False, error="not in whitelist")
        return (
            False,
            f"[SKIP] '{verb}' is not a whitelisted action; try: see/open/type/key/click",
        )

    handler, needs_pyautogui, _blurb = ACTIONS[verb]
    if needs_pyautogui and not pyautogui_available():
        log_action(f"{verb} {rest}".strip(), False, error="pyautogui not installed")
        return False, "[BLOCKED] this action needs pyautogui (pip install pyautogui)"

    plan = f"{verb} {rest}".strip()
    if not confirm_fn(plan):
        log_action(plan, False, error="user aborted")
        return False, "[ABORTED]"

    try:
        result = handler(rest) if verb != "click" else handler()
        time.sleep(1)
        from orion_runner.screen import see

        post = see()
        log_action(plan, True, result=result)
        return True, f"[DONE] {result}\n{post}"
    except Exception as exc:  # noqa: BLE001 - keep the loop alive, log the failure
        log_action(plan, True, error=str(exc))
        return False, f"[ERROR] {exc}"
