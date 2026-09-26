"""ORION Runner - vision bridge.

Lets ORION "see" an image by routing it through a tiny local vision-language
model (Florence-2-base, ~0.23B, CPU-friendly) and returning a caption /
description that ORION (a text-only model) can then actually use. This is an
honest pipeline: ORION reads the *description* produced by the vision encoder.

Deliberately small: only what is needed. Florence-2 is loaded lazily and only
when an image is actually processed, so it never pins RAM while ORION trains.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional, Union

_IMAGE_INPUTS = None  # lazy import guard
_TRANSFORMERS = None
_MODEL = None
_TOKENIZER = None


def _import_backend():
    global _IMAGE_INPUTS, _TRANSFORMERS, _MODEL, _TOKENIZER
    if _MODEL is not None:
        return
    from transformers import AutoModelForCausalLM, AutoProcessor
    from transformers.image_utils import load_image

    model_id = "microsoft/Florence-2-base"
    print(f"[VISION] loading {model_id} (first time downloads ~0.5 GB)...")
    _TOKENIZER = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
    _MODEL = AutoModelForCausalLM.from_pretrained(
        model_id,
        trust_remote_code=True,
        low_cpu_mem_usage=True,
        local_files_only=False,
        attn_implementation="eager",
    )
    _MODEL.eval()
    _IMAGE_INPUTS = load_image
    print("[VISION] Florence-2-base ready")


def describe(image: Union[str, Path]) -> str:
    """Describe an image file with '<CAPTION>' task. Returns plain text."""
    _import_backend()
    import torch

    img = _IMAGE_INPUTS(str(image))
    prompt = "<CAPTION>"
    inputs = _TOKENIZER(text=prompt, images=img, return_tensors="pt")
    with torch.no_grad():
        generated_ids = _MODEL.generate(
            **inputs,
            max_new_tokens=64,
            num_beams=3,
            use_cache=False,  # Florence-2 remote code predates HF cache API
        )
    generated_text = _TOKENIZER.batch_decode(generated_ids, skip_special_tokens=False)[
        0
    ]
    parsed = _TOKENIZER.post_process_generation(
        generated_text, task="<CAPTION>", image_size=(img.size[1], img.size[0])
    )
    return parsed["<CAPTION>"].strip()


def describe_backend_available() -> bool:
    return _MODEL is not None or "transformers" in sys.modules


if __name__ == "__main__":  # self-check on a real image
    img = r"C:/Users/shaur/AppData/Local/Temp/opencode/orion_tt/test_image.png"
    cap = describe(img)
    print(f"SELF-CHECK ok: caption = {cap}")
