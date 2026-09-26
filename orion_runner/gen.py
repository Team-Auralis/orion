"""ORION Runner - image generation bridge.

Generates images from a text prompt using a tiny Stable Diffusion variant
(segmind/tiny-sd, ~1 GB) that fits this laptop's CPU/RAM budget. Loads lazily,
generates 512x512 at 8 inference steps, returns the output PNG path.

Honest note for THIS box: no GPU, so each image takes a few minutes on CPU.
There is no claim of photorealistic quality; tiny-sd is a distilled model that
makes serviceable 512x512 images quickly.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Union

_PIPE = None
try:
    import torch
except Exception:  # pragma: no cover
    torch = None


def _import_pipe():
    global _PIPE
    if _PIPE is not None:
        return
    from diffusers import StableDiffusionPipeline

    model_id = "segmind/tiny-sd"
    print(f"[GEN] loading {model_id} (first time downloads ~1 GB)...")
    _PIPE = StableDiffusionPipeline.from_pretrained(
        model_id,
        torch_dtype=torch.float32,
        safety_checker=None,
        requires_safety_checker=False,
        use_safetensors=False,  # tiny-sd ships pytorch_model.bin
    )
    _PIPE.set_progress_bar_config(disable=True)
    print("[GEN] tiny-sd ready")


def generate(
    prompt: str, out_path: Union[str, Path], steps: int = 8, seed: int = 0
) -> Path:
    """Generate a 512x512 image from prompt. Returns output path (PNG)."""
    if torch is None:
        raise RuntimeError("torch not importable")
    _import_pipe()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    g = torch.Generator().manual_seed(seed)
    img = _PIPE(prompt, num_inference_steps=steps, generator=g).images[0]
    img.save(str(out_path))
    return out_path


if __name__ == "__main__":  # self-check: real image on CPU
    out = r"C:/Users/shaur/AppData/Local/Temp/opencode/orion_tt/orion_gen.png"
    p = generate("a small cute robot waving hello, flat vector style", out, steps=8)
    print(f"SELF-CHECK ok: {p} ({p.stat().st_size} bytes)")
