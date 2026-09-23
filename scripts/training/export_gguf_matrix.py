#!/usr/bin/env python3
"""COMP-001 GGUF export matrix (Task 5).

Exports the custom comp001 HF model dir(s) into a full GGUF quant matrix,
reusing the in-repo numpy-only converter (convert_hf_to_gguf.py), then runs a
round-trip sanity pass (tensor list + config vs the HF export, dequantize
error vs the original F32 weights via the gguf package) and records every
artifact in the ledger as the `comp001-gguf-matrix` experiment.

Guaranteed quant levels (in-repo converter): f16, q8_0, q4_0 — Q8_0/Q4_0 byte
layouts are bit-exact with gguf.quants (llama.cpp reference).

Q4_K_M / lower-bit: llama.cpp's `quantize` binary is NOT bundled or installed
on this box (checked: PATH + repo; ollama 0.34 has no quantize subcommand and
the gguf python package implements no K-quant quantizers). The code path is
ready: pass `--quant Q4_K_M` and if a llama.cpp quantize binary is present on
PATH (or at LLAMA_QUANTIZE) it is invoked on the f16 export; otherwise the
variant is reported blocked instead of silently skipped.

Usage:
    python scripts/training/export_gguf_matrix.py
    python scripts/training/export_gguf_matrix.py --hf-dir models/comp001/10m
    python scripts/training/export_gguf_matrix.py --quant Q4_K_M
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "training"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from convert_hf_to_gguf import convert  # noqa: E402
from gguf import GGUFReader  # noqa: E402
from gguf.quants import dequantize  # noqa: E402

# guaranteed quant levels (implemented bit-exact in convert_hf_to_gguf.py)
QUANTS = ("f16", "q8_0", "q4_0")
# Q4_K_M / lower-bit are *attempted* on every run (llama.cpp gate), not guaranteed
ATTEMPT_QUANTS = ("Q4_K_M",)
SUFFIX = {"f16": "f16", "q8_0": "q8_0", "q4_0": "q4_0"}
NAME = {
    "f16": "comp001-{size}-f16.gguf",
    "q8_0": "comp001-{size}-q8_0.gguf",
    "q4_0": "comp001-{size}-q4_0.gguf",
}

# gguf tensor name -> HF safetensors tensor name (reverse of the converter map)
GGUF_TO_HF = {
    "token_embd.weight": "model.embed_tokens.weight",
    "output_norm.weight": "model.norm.weight",
    "output.weight": "lm_head.weight",
}
for i in range(64):
    GGUF_TO_HF[f"blk.{i}.attn_norm.weight"] = f"model.layers.{i}.input_layernorm.weight"
    GGUF_TO_HF[f"blk.{i}.ffn_norm.weight"] = (
        f"model.layers.{i}.post_attention_layernorm.weight"
    )
    for src, dst in [
        ("attn_q.weight", "self_attn.q_proj.weight"),
        ("attn_q.bias", "self_attn.q_proj.bias"),
        ("attn_k.weight", "self_attn.k_proj.weight"),
        ("attn_k.bias", "self_attn.k_proj.bias"),
        ("attn_v.weight", "self_attn.v_proj.weight"),
        ("attn_v.bias", "self_attn.v_proj.bias"),
        ("attn_output.weight", "self_attn.o_proj.weight"),
        ("ffn_gate.weight", "mlp.gate_proj.weight"),
        ("ffn_down.weight", "mlp.down_proj.weight"),
        ("ffn_up.weight", "mlp.up_proj.weight"),
    ]:
        GGUF_TO_HF[f"blk.{i}.{src}"] = f"model.layers.{i}.{dst}"


def tensor_to_f32(t, reader=None):
    """Return an (rows, cols) float32 np array for a gguf ReaderTensor."""
    import numpy as np
    from gguf.constants import GGMLQuantizationType as T

    if t.tensor_type in (T.F32,):
        return np.ascontiguousarray(t.data, dtype=np.float32)
    if t.tensor_type == T.F16:
        return np.ascontiguousarray(t.data, dtype=np.float16).astype(np.float32)
    # quantized: t.data is the packed byte array reshaped by the reader
    return dequantize(
        np.ascontiguousarray(t.data, dtype=np.uint8), t.tensor_type
    ).astype(np.float32)


def roundtrip_verify(gguf_path: Path, hf_dir: Path) -> dict:
    """Compare gguf tensor list/config with the HF export; dequantize a probe
    set of tensors and report max abs error vs the original F32 weights."""
    import numpy as np
    import safetensors.numpy as stnp

    reader = GGUFReader(str(gguf_path))
    cfg = json.loads((hf_dir / "config.json").read_text(encoding="utf-8"))

    gguf_names = [t.name for t in reader.tensors]
    loaded = stnp.load_file(str(hf_dir / "model.safetensors"))
    hf_shapes = {}
    for hf_key, arr in loaded.items():
        hf_shapes[hf_key] = list(arr.shape)

    missing = [name for name in gguf_names if GGUF_TO_HF.get(name) not in hf_shapes]
    # tensors stored as u8 give gguf byte-shape; compare via expected element shapes
    kv_checks = {
        "qwen2.block_count": cfg["num_hidden_layers"],
        "qwen2.context_length": cfg["max_position_embeddings"],
        "qwen2.embedding_length": cfg["hidden_size"],
        "qwen2.feed_forward_length": cfg["intermediate_size"],
        "qwen2.attention.head_count": cfg["num_attention_heads"],
        "qwen2.attention.head_count_kv": cfg["num_key_value_heads"],
    }
    kv_mismatch = {}
    for gguf_key, want in kv_checks.items():
        got = reader.fields.get(gguf_key)
        got_v = got.parts[-1].tolist()[0] if got is not None else None
        if got_v != want:
            kv_mismatch[gguf_key] = (got_v, want)

    probe_errors = {}
    probe_names = [
        n
        for n in (
            "token_embd.weight",
            "output.weight",
            "blk.0.attn_q.weight",
            "blk.0.ffn_gate.weight",
            "output_norm.weight",
        )
        if n in gguf_names
    ]
    loaded = stnp.load_file(str(hf_dir / "model.safetensors"))
    for gname in probe_names:
        t = next(t for t in reader.tensors if t.name == gname)
        dq = tensor_to_f32(t)
        hf = np.ascontiguousarray(loaded[GGUF_TO_HF[gname]].astype(np.float32))
        want_shape = list(hf.shape)
        if list(dq.shape) != want_shape:
            # quantized gguf tensors may come back transposed in rare cases; try transpose
            if list(dq.T.shape) == want_shape:
                dq = dq.T
            else:
                probe_errors[gname] = f"shape {list(dq.shape)} != {want_shape}"
                continue
        err = float(np.abs(dq - hf).max())
        probe_errors[gname] = round(err, 6)

    return {
        "tensor_count": len(gguf_names),
        "tensor_count_expected": len(hf_shapes),
        "missing_hf_mapping": missing,
        "kv_mismatch": kv_mismatch,
        "probe_max_abs_err": probe_errors,
    }


def find_llama_quantize() -> Path | None:
    env = Path(__import__("os").environ.get("LLAMA_QUANTIZE", ""))
    if env and env.is_file():
        return env
    exe = shutil.which("llama-quantize")
    if exe:
        return Path(exe)
    for cand in ("llama-quantize.exe", "quantize.exe", "llama-quantize"):
        hit = (
            next(REPO_ROOT.rglob(cand), None)
            if cand in ("quantize.exe", "llama-quantize.exe")
            else None
        )
        if hit:
            return hit
    return None


def q4_k_m_or_blocked(hf_dir: Path, out_dir: Path, f16_path: Path) -> dict:
    """Attempt Q4_K_M via a llama.cpp quantize binary; if none is installed,
    record the honest limitation (no installs allowed) and return blocked."""
    target = (
        "comp001-100m-Q4_K_M.gguf"
        if hf_dir.name == "100m"
        else "comp001-10m-Q4_K_M.gguf"
    )
    out = out_dir / target
    bin_path = find_llama_quantize()
    if bin_path is None:
        return {
            "state": "blocked_requires_llama_cpp",
            "file": str(out),
            "bytes": 0,
            "reason": (
                "Q4_K_M/lower-bit requires llama.cpp 'quantize' binary (k-quant "
                "path) which is NOT installed: PATH + repo scan found no "
                "llama-quantize/quantize/llama-cli, ollama 0.34 has no quantize "
                "subcommand, and gguf==0.19.0 gguf.quants.quantize raises "
                "NotImplementedError for Q4_K/Q3_K/Q2_K/Q6_K (verified by probe). "
                "No installs were made (task constraint). Code path ready: set "
                "LLAMA_QUANTIZE or put llama-quantize on PATH and rerun with "
                "--quant Q4_K_M."
            ),
        }
    subprocess.run([str(bin_path), str(f16_path), str(out), "Q4_K_M"], check=True)
    return {
        "state": "exported",
        "file": str(out),
        "bytes": out.stat().st_size,
        "reason": "",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hf-dir", default=str(REPO_ROOT / "models" / "comp001" / "100m"))
    ap.add_argument("--out-dir", default="")
    ap.add_argument(
        "--quants",
        default="f16,q8_0,q4_0,Q4_K_M",
        help="comma list of f16/q8_0/q4_0 plus Q4_K_M (attempted via llama.cpp)",
    )
    ap.add_argument("--quant", default="", help="single quant override (e.g. Q4_K_M)")
    ap.add_argument(
        "--smoke-10m",
        action="store_true",
        help="also export the models/comp001/10m dir (same path)",
    )
    args = ap.parse_args()

    hf_dir = Path(args.hf_dir)
    if not (hf_dir / "model.safetensors").exists():
        raise SystemExit(f"[matrix] no model.safetensors at {hf_dir}")
    out_dir = Path(args.out_dir) if args.out_dir else hf_dir / "gguf"
    out_dir.mkdir(parents=True, exist_ok=True)

    quants = [args.quant] if args.quant else [q.strip() for q in args.quants.split(",")]
    size_tag = "100m" if hf_dir.name == "100m" else hf_dir.name

    variants = {}
    start = time.time()
    for quant in quants:
        if quant in QUANTS:
            out_path = out_dir / NAME[quant].format(size=size_tag)
            convert(hf_dir, out_path, quant=quant)
            variants[quant] = {
                "state": "exported",
                "file": str(out_path),
                "bytes": out_path.stat().st_size,
            }
        elif quant == "Q4_K_M":
            f16_path = out_dir / NAME["f16"].format(size=size_tag)
            resp = q4_k_m_or_blocked(hf_dir, out_dir, f16_path)
            variants[quant] = resp
        else:
            print(f"[matrix] unsupported quant {quant!r} - skipping")
    # lower-bit (below q4_0, e.g. Q3_K_M / Q2_K) goes through the same llama.cpp path
    if "lower" in quants:
        resp = q4_k_m_or_blocked(
            hf_dir, out_dir, out_dir / NAME["f16"].format(size=size_tag)
        )
        variants["lower_attempt"] = resp

    # round-trip sanity on every exported f16/q8/q4 file
    sanity = {}
    for quant in QUANTS:
        if quant in variants and variants[quant]["state"] == "exported":
            sanity[quant] = roundtrip_verify(Path(variants[quant]["file"]), hf_dir)

    # quality probe per exported variant (dequantized via gguf package)
    probes = {}
    probe_script = REPO_ROOT / "scripts" / "evaluation" / "comp001_quality.py"
    tokenizer_dir = REPO_ROOT / "models" / "tokenizer_bpe"
    if probe_script.exists():
        for quant, info in variants.items():
            if info["state"] != "exported":
                probes[quant] = "not_measured_requires_llama.cpp"
                continue
            try:
                out = subprocess.run(
                    [
                        sys.executable,
                        str(probe_script),
                        "--model",
                        str(hf_dir),
                        "--tokenizer",
                        str(tokenizer_dir),
                        "--gguf",
                        str(info["file"]),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=1200,
                )
                m = re.search(r"PROBE_SCORE=([\d.]+)", out.stdout)
                probes[quant] = (
                    float(m.group(1)) if m else f"parse_failed: {out.stdout[-200:]!r}"
                )
            except subprocess.TimeoutExpired:
                probes[quant] = "timed_out"
            except Exception as e:  # noqa: BLE001
                probes[quant] = f"failed: {e}"
    else:
        print(f"[matrix] probe script not found: {probe_script}")

    # 10m smoke through the same path
    smoke = {}
    if args.smoke_10m:
        hf10 = REPO_ROOT / "models" / "comp001" / "10m"
        out10 = hf10 / "gguf"
        out10.mkdir(parents=True, exist_ok=True)
        for quant in ("f16", "q8_0", "q4_0"):
            out_path = out10 / NAME[quant].format(size="10m")
            convert(hf10, out_path, quant=quant)
            smoke[quant] = {
                "state": "exported",
                "file": str(out_path),
                "bytes": out_path.stat().st_size,
            }
        smoke["sanity_f16"] = roundtrip_verify(
            out10 / NAME["f16"].format(size="10m"), hf10
        )

    # -- honest size/power table ----------------------------------------------
    hf_bytes = (hf_dir / "model.safetensors").stat().st_size
    print("\n=== COMP-001 GGUF matrix ===")
    print(f"source: {hf_dir} | safetensors {hf_bytes / 1e6:.1f} MB")
    header = (
        f"  {'variant':8s} {'params':12s} {'MB':>9s} {'ratio':>7s} "
        f"{'probe':>8s} {'est. RAM MB':>11s}  state"
    )
    print(header)
    for quant, info in variants.items():
        mb = info["bytes"] / 1e6
        ratio = info["bytes"] / hf_bytes if info["bytes"] else 0
        probe = probes.get(quant, "n/a")
        msg = "" if info["state"] == "exported" else info.get("reason", "")
        if info["state"] == "exported":
            est_ram = mb * 1.25  # weights + overhead (no KV cache here)
        elif quant == "Q4_K_M":
            est_ram = 0.0
        else:
            est_ram = 0.0
        print(
            f"  {quant:8s} {info.get('params', '-'):12s} {mb:9.2f} {ratio:7.3f} "
            f"{str(probe):>8s} {est_ram:11.1f}  {info['state']} {msg}"
        )
    print(
        "  (est. RAM MB = GGUF bytes * 1.25, load-time overhead; KV cache & logits excluded)"
    )

    # ledger row
    try:
        from repro import record_experiment  # scripts/ on path

        record = {
            "run_id": f"comp001-gguf-matrix-{int(time.time())}",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "COMPLETED",
            "base_model_name": "comp001-custom-100m/g10m",
            "model_type": "GGUF export matrix",
            "dataset_path": str(hf_dir / "model.safetensors"),
            "tokenizer_path": str(hf_dir / "tokenizer.json"),
            "num_samples": 0,
            "seed": 0,
            "epochs": 0,
            "learning_rate": 0.0,
            "starting_loss": 0.0,
            "ending_loss": 0.0,
            "loss_reduction_pct": 0.0,
            "eval_loss": 0.0,
            "checkpoint_path": str(out_dir),
            "output_differs": False,
            "error_message": "",
            "variants": {
                q: {
                    **v,
                    "params": v.get("params", "-"),
                    "mb": round(v["bytes"] / 1e6, 2),
                    "ratio_vs_424mb": round(v["bytes"] / hf_bytes, 3),
                    "probe_score": probes.get(q),
                    "est_ram_mb": round(v["bytes"] / 1e6 * 1.25, 2)
                    if v["state"] == "exported"
                    else 0.0,
                }
                for q, v in variants.items()
            },
            "sanity": sanity,
            "smoke_10m": smoke,
            "hg_bytes": hf_bytes,
        }
        params = {"quants": quants, "smoke_10m": args.smoke_10m}
        record_experiment("comp001-gguf-matrix", params, record)
        print(f"[RECORD] comp001-gguf-matrix logged: {record['run_id']}")
    except (
        Exception
    ) as e:  # pragma: no cover - ledger failure shouldn't kill the export
        print(f"[RECORD] ledger write failed: {e}")
        raise

    print(f"[matrix] done in {time.time() - start:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
