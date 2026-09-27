"""ORION Runner - screen awareness (capture + describe).

Honest bridge, same design as vision.py: ORION never sees pixels; it reads the
Florence-2 caption of whatever is on the primary display at the moment of
capture. capture() takes the screenshot, see() returns the caption.
"""

from __future__ import annotations

import time
from pathlib import Path

from PIL import ImageGrab

from orion_runner.vision import describe

SCREENSHOT_DIR = Path(__file__).resolve().parents[1] / "data" / "screenshots"

# Last successful caption, so the classifier can reuse a REAL screen
# description instead of the neutral placeholder when available.
_last_caption = ""


def last_caption() -> str:
    """Caption of the most recent successful see(); '' if none yet."""
    return _last_caption


def capture(path: Path | str | None = None) -> Path:
    """Grab the primary display to a PNG and return the saved path."""
    shot = (
        Path(path)
        if path
        else (SCREENSHOT_DIR / f"screen_{time.strftime('%Y%m%d_%H%M%S')}.png")
    )
    shot.parent.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab().save(shot)
    return shot


def see(path: Path | str | None = None) -> str:
    """Capture the screen (or reuse an existing image) and describe it."""
    global _last_caption
    shot = capture(path)
    try:
        caption = describe(shot)  # lazy-loads Florence-2 on first use
    except Exception as exc:  # noqa: BLE001 - honest BLOCKED, not a crash
        return (
            f"[VISION BLOCKED] capture saved to {shot}; Florence-2 unavailable: {exc}"
        )
    _last_caption = caption
    return f"shot={shot}\ncaption: {caption}"


if __name__ == "__main__":  # self-check: capture + describe this display
    print(see())
