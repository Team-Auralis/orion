#!/usr/bin/env python3
"""Deploy the trained ORION HF model into Ollama as "orion:0.5b".

Pipeline: merged HF dir --GGUF(Q4_0, default)--> ollama create --smoke--> app-ready.

Run AFTER orion_train.py --merge has produced data/training/orion_merged:
    python scripts/training/deploy_orion.py
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "training"))
from convert_hf_to_gguf import convert  # noqa: E402

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

DEFAULT_HF_DIR = REPO_ROOT / "data" / "training" / "orion_merged"
DEFAULT_GGUF = DEFAULT_HF_DIR / "orion-0.5b-q4.gguf"
DEFAULT_NAME = os.environ.get("ORION_MODEL", "orion:0.5b")

TEMPLATE = (
    "{{- if .System }}<|im_start|>system\n{{ .System }}<|im_end|>\n{{ end }}"
    "{{- range $i, $_ := .Messages }}<|im_start|>{{ .Role }}\n{{ .Content }}<|im_end|>\n"
    "{{ end }}<|im_start|>assistant\n"
)


def write_modelfile(gguf: Path, name: str) -> Path:
    mf = gguf.parent / "Modelfile"
    mf.write_text(f'FROM "{gguf.resolve().as_posix()}"\n'
                  f"TEMPLATE \"\"\"{TEMPLATE}\"\"\"\n",
                  encoding="utf-8")
    return mf


def run(cmd: list) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {r.stderr or r.stdout}")
    return (r.stdout or "").strip()


def smoke_test(name: str, prompt: str = "What is ORION?") -> bool:
    try:
        import ctypes
        class MS(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("l2", ctypes.c_ulong),
                        ("t", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong)] + \
                       [("p", ctypes.c_ulonglong)] * 5
        m = MS(); m.l = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        if m.a // 1048576 < 750:
            print("[smoke] skipped - free RAM below 750 MB to load the model")
            return False
    except Exception:
        pass
    try:
        import httpx
        r = httpx.post(f"{OLLAMA_URL}/api/generate",
                       json={"model": name, "prompt": prompt, "stream": False,
                             "options": {"num_predict": 32, "temperature": 0.2}},
                       timeout=180)
        if r.status_code != 200:
            print(f"[smoke] fail: HTTP {r.status_code} {r.text[:200]}")
            return False
        out = r.json().get("response", "")
        print(f"[smoke] {name} -> \"{out[:120]}\"")
        return bool(out.strip())
    except Exception as e:
        print(f"[smoke] fail: {e}")
        return False


def deploy(hf_dir: Path, gguf_path: Path, name: str, do_smoke: bool) -> bool:
    if not (hf_dir / "pytorch_model.bin").exists() and not (hf_dir / "model.safetensors").exists():
        if hf_dir.exists():
            matches = list(hf_dir.rglob("model.safetensors"))
            if matches:
                hf_dir = matches[0].parent
            else:
                print(f"[deploy] no model found in {hf_dir} - train with --merge first")
                return False
        else:
            print(f"[deploy] no model found in {hf_dir} - train with --merge first")
            return False
    print(f"[deploy] hf: {hf_dir}")
    convert(hf_dir, gguf_path)
    modelfile = write_modelfile(gguf_path, name)
    run(["ollama", "create", name, "-f", str(modelfile)])
    print(f"[deploy] ollama model created: {name}")
    if do_smoke:
        smoke_test(name)
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Deploy ORION model to Ollama")
    ap.add_argument("--hf-dir", type=str, default=str(DEFAULT_HF_DIR))
    ap.add_argument("--gguf", type=str, default=str(DEFAULT_GGUF))
    ap.add_argument("--name", type=str, default=DEFAULT_NAME)
    ap.add_argument("--no-smoke", action="store_true")
    args = ap.parse_args()
    ok = deploy(Path(args.hf_dir), Path(args.gguf), args.name, not args.no_smoke)
    sys.exit(0 if ok else 2)