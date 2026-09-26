#!/usr/bin/env python3
"""Give ORION a voice: speak any text with edge-tts (natural) or SAPI fallback.

    python scripts/orion_speak.py "Hello, I am ORION." [--play] [--voice en-US-JennyNeural]

Output audio is written to logs/orion_speak.mp3 (edge) or .wav (SAPI).
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def main():
    ap = argparse.ArgumentParser(description="ORION voice (TTS) — speak text aloud")
    ap.add_argument("text", help="text to speak")
    ap.add_argument(
        "--play", action="store_true", help="also open the OS default player"
    )
    ap.add_argument(
        "--voice",
        default="en-US-JennyNeural",
        help="edge-tts voice id (see edge-tts --list-voices)",
    )
    ap.add_argument("--backend", default="auto", choices=["auto", "edge", "sapi"])
    ap.add_argument(
        "--out", default=None, help="output audio path (default logs/orion_speak)"
    )
    args = ap.parse_args()

    from orion_runner.voice import speak

    out = Path(args.out) if args.out else REPO_ROOT / "logs" / "orion_speak"
    path = speak(args.text, out, backend=args.backend, voice=args.voice, play=args.play)
    print(f"[OK] audio -> {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
