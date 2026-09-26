#!/usr/bin/env python3
"""ORION, what's on my screen? Capture + Florence-2 caption.

    python scripts/orion_see.py [--path path.png]

Without --path it grabs the live primary display (1920x1080 here) and prints
the caption, e.g. "a Windows desktop with a terminal window open".
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def main():
    ap = argparse.ArgumentParser(description="ORION screen vision - capture + describe")
    ap.add_argument(
        "--path", default=None, help="optional existing image instead of live capture"
    )
    args = ap.parse_args()

    from orion_runner.screen import see

    print(see(args.path))


if __name__ == "__main__":
    main()
