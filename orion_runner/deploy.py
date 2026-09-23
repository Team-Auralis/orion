"""ORION Runner - deploy bridge.

Turns a merged HF checkpoint directory into an Ollama model by reusing the
proven deploy pipeline in scripts/training/deploy_orion.py
(convert -> Modelfile -> ollama create -> smoke test).
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAG = os.environ.get("ORION_MODEL", "orion:0.5b")


def deploy(merged_dir, name: str = None, quant: str = "q4_0",
           smoke: bool = True) -> tuple:
    """Deploy a merged HF directory into Ollama.

    Returns (ok, gguf_path, tag). `merged_dir` must contain a HF model
    (pytorch_model.bin or model.safetensors) produced with --merge; the
    GGUF file is written next to it.
    """
    hf_dir = Path(merged_dir)
    tag = name or DEFAULT_TAG
    if not ((hf_dir / "pytorch_model.bin").exists()
            or (hf_dir / "model.safetensors").exists()):
        matches = list(hf_dir.rglob("model.safetensors"))
        if not matches:
            raise FileNotFoundError(
                f"no HF model found in {hf_dir} - train with --merge first"
            )
        hf_dir = matches[0].parent

    sys.path.insert(0, str(REPO_ROOT / "scripts" / "training"))
    from deploy_orion import deploy as _deploy

    gguf = hf_dir / f"orion-0.5b-{quant}.gguf"
    ok = _deploy(hf_dir, gguf, tag, smoke)
    return ok, gguf, tag


def run_id_to_checkpoint(run_id: str) -> Path:
    """Resolve a training run_id to its LoRA checkpoint directory."""
    candidates = (REPO_ROOT / "models" / "checkpoints").glob(f"{run_id}")
    for c in candidates:
        if c.is_dir():
            return c
    raise FileNotFoundError(f"no checkpoint found for run {run_id!r}")