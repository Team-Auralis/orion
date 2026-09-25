"""ORION Runner - voice / TTS.

Two backends:
  * edge-tts (natural neural voices, needs internet) - default
  * Windows SAPI (System.Speech, offline, zero dependencies) - fallback

Deliberately tiny: text in -> .wav/.mp3 file out -> optional playback via the
OS default player. No model download, no GPU, no framework.
"""

import asyncio
import subprocess
import sys
from pathlib import Path

try:
    import edge_tts
except Exception:  # pragma: no cover - import guard
    edge_tts = None

DEFAULT_VOICE = "en-US-JennyNeural"
DEFAULT_RATE = "+0%"


def _ffmpeg() -> bool:
    """edge-tts emits mp3; playback needs an mp3-capable player. On Windows the
    default media player handles it, so we just hand the path to os.startfile."""
    return True


def synthesize_edge(
    text: str, out_path: Path, voice: str = DEFAULT_VOICE, rate: str = DEFAULT_RATE
) -> Path:
    """Synthesize using Microsoft Edge neural TTS (natural voice, needs net)."""
    if edge_tts is None:
        raise RuntimeError("edge-tts not installed (pip install edge-tts)")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    async def _run():
        comm = edge_tts.Communicate(text, voice=voice, rate=rate)
        await comm.save(str(out_path))

    asyncio.run(_run())
    if not out_path.exists():
        raise RuntimeError(f"edge-tts produced no file at {out_path}")
    return out_path


def synthesize_sapi(text: str, out_path: Path, rate: int = 0) -> Path:
    """Windows SAPI fallback (offline, zero deps, robotic but real)."""
    import win32com.client  # pywin32

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wav = out_path.with_suffix(".wav")
    speaker = win32com.client.Dispatch("SAPI.SpVoice")
    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    stream.Format.Type = 44  # SFT_WAVE_FORMAT=native (44)
    stream.Open(str(wav), 3)  # SSFMCreateForWrite
    speaker.AudioOutputStream = stream
    speaker.Rate = rate
    speaker.Speak(text)
    stream.Close()
    return wav


def speak(
    text: str,
    out_path: Path,
    backend: str = "auto",
    voice: str = DEFAULT_VOICE,
    play: bool = False,
) -> Path:
    """Top-level: auto tries edge-tts, falls back to SAPI. Returns audio path."""
    errors = []
    if backend in ("auto", "edge"):
        try:
            p = synthesize_edge(text, out_path, voice=voice)
            if play and sys.platform == "win32":
                subprocess.Popen(["cmd", "/c", "start", "", str(p)], shell=False)
            if backend == "edge":
                return p
            return p
        except Exception as e:  # pragma: no cover
            errors.append(f"edge: {e}")
            if backend == "edge":
                raise
    if backend in ("auto", "sapi"):
        try:
            p = synthesize_sapi(text, out_path)
            if play and sys.platform == "win32":
                subprocess.Popen(["cmd", "/c", "start", "", str(p)], shell=False)
            return p
        except Exception as e:
            errors.append(f"sapi: {e}")
            raise RuntimeError("voice synthesis failed: " + " | ".join(errors))
    raise ValueError(f"unknown backend {backend!r}")


if __name__ == "__main__":  # quick self-check
    out = Path(__file__).resolve().parents[1] / "logs" / "voice_selfcheck.wav"
    p = speak(
        "Hello, I am ORION. Context window, teacher, vision, and voice "
        "modules are now integrated.",
        out,
        play=False,
    )
    print(f"SELF-CHECK ok: {p} ({p.stat().st_size} bytes)")
