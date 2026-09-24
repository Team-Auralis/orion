#!/usr/bin/env python3
"""F6 GGUF quantization quality-retention for COMP-001 100m-real.

Measures quality retention of the q8_0/q4_0 GGUF exports vs the fp32/f16
references WITHOUT a llama.cpp runtime, using the `gguf` lib (0.19.0) real
block-dequantization (gguf.quants.dequantize) for the weight tensors.

All four states evaluated on the SAME fixed 64-token held-out slice (first 64
tokens of data/training/corpus/test-wiki-part-00000.jsonl, never trained on):
    fp32@1919 checkpoint-1919 (TRUE latest trained state, fp32 CPU weights)
    fp32@1869 f16 GGUF export (1869-state; weights stored F16 in the file)
    q8@1869   q8_0 GGUF export (same 1869-state, block-dequantized to fp32)
    q4@1869   q4_0 GGUF export (same 1869-state, block-dequantized to fp32)
Per-tensor SNR of dequantized weights vs the f16-GGUF reference is reported
for the 79 quantized weight tensors in each quant file.

Q4_K_M is classified BLOCKED: no llama-quantize/quantize binary exists on this
box (third_party/BitNet/build/bin contains only llama-cli.exe; PATH searched),
gguf 0.19.0 cannot K-quant (verified previously, recorded in training_runs),
and no Q4_K_M file exists on disk -> no number is invented.

Output: logs/forensic/profiling/quality_retention.json (+ printed table).
"""

from __future__ import annotations

import gc
import json
import math
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "training"))

import numpy as np  # noqa: E402
import psutil  # noqa: E402
import torch  # noqa: E402
from gguf import GGUFReader, quants  # noqa: E402
from transformers import Qwen2Config, Qwen2ForCausalLM  # noqa: E402

import orion_corpus  # noqa: E402
from scripts.forensic.eval_suite import (  # noqa: E402
    free_ram_mb,
    load_model_from_checkpoint,
    load_tokenizer,
    peak_rss_mb,
    ramp_guard,
)

CKPT_DIR = REPO_ROOT / "models" / "comp001" / "100m-real" / "checkpoint-1919"
GGUF_DIR = REPO_ROOT / "models" / "comp001" / "100m-real" / "gguf"
TEST_SHARD = REPO_ROOT / "data" / "training" / "corpus" / "test-wiki-part-00000.jsonl"
OUT_DIR = REPO_ROOT / "logs" / "forensic" / "profiling"
SLICE_TOKENS = 64

# GGUF tensor name -> HF Qwen2 state_dict key
_MAP = {
    "token_embd.weight": "model.embed_tokens.weight",
    "output.weight": "lm_head.weight",
    "output_norm.weight": "model.norm.weight",
}
for i in range(32):
    _MAP[f"blk.{i}.attn_norm.weight"] = f"model.layers.{i}.input_layernorm.weight"
    _MAP[f"blk.{i}.ffn_norm.weight"] = (
        f"model.layers.{i}.post_attention_layernorm.weight"
    )
    _MAP[f"blk.{i}.attn_q.weight"] = f"model.layers.{i}.self_attn.q_proj.weight"
    _MAP[f"blk.{i}.attn_q.bias"] = f"model.layers.{i}.self_attn.q_proj.bias"
    _MAP[f"blk.{i}.attn_k.weight"] = f"model.layers.{i}.self_attn.k_proj.weight"
    _MAP[f"blk.{i}.attn_k.bias"] = f"model.layers.{i}.self_attn.k_proj.bias"
    _MAP[f"blk.{i}.attn_v.weight"] = f"model.layers.{i}.self_attn.v_proj.weight"
    _MAP[f"blk.{i}.attn_v.bias"] = f"model.layers.{i}.self_attn.v_proj.bias"
    _MAP[f"blk.{i}.attn_output.weight"] = f"model.layers.{i}.self_attn.o_proj.weight"
    _MAP[f"blk.{i}.ffn_gate.weight"] = f"model.layers.{i}.mlp.gate_proj.weight"
    _MAP[f"blk.{i}.ffn_up.weight"] = f"model.layers.{i}.mlp.up_proj.weight"
    _MAP[f"blk.{i}.ffn_down.weight"] = f"model.layers.{i}.mlp.down_proj.weight"


def build_model() -> tuple[Qwen2ForCausalLM, dict]:
    """Fresh 11-layer 10240-vocab model from checkpoint.json config (same arch
    for every state; strict load verifies the state covers it fully)."""
    ckj = json.loads((CKPT_DIR / "checkpoint.json").read_text(encoding="utf-8"))
    cfg = ckj["config"]
    model = Qwen2ForCausalLM(
        Qwen2Config(
            vocab_size=cfg["vocab_size"],
            hidden_size=cfg["hidden_size"],
            intermediate_size=cfg["intermediate_size"],
            num_hidden_layers=cfg["num_hidden_layers"],
            num_attention_heads=cfg["num_attention_heads"],
            num_key_value_heads=cfg["num_key_value_heads"],
            max_position_embeddings=cfg["max_position_embeddings"],
            pad_token_id=cfg["pad_token_id"],
            bos_token_id=cfg["bos_token_id"],
            eos_token_id=cfg["eos_token_id"],
            tie_word_embeddings=cfg["tie_word_embeddings"],
        )
    )
    model.eval()
    return model, cfg


def ppl_ids(model, ids) -> dict:
    """Per-token NLL / ppl over an exact token-id sequence."""
    with torch.no_grad():
        logits = model(input_ids=torch.tensor([ids], dtype=torch.long)).logits[0]
        logp = torch.log_softmax(logits[:-1].float(), dim=-1)
        tgt = torch.as_tensor(ids[1:], dtype=torch.long)
        nll = float(-logp[torch.arange(len(ids) - 1), tgt].sum().item())
    loss = nll / max(len(ids) - 1, 1)
    return {
        "loss": round(loss, 6),
        "ppl": round(math.exp(loss), 4),
        "tokens": len(ids) - 1,
    }


def gguf_tensor(reader: GGUFReader, name: str) -> np.ndarray:
    t = next(x for x in reader.tensors if x.name == name)
    return np.asarray(t.data)


def load_state_from_gguf(model, reader: GGUFReader) -> tuple[int, list]:
    """Copy every mapped tensor into the model state (dequantizing when the
    file is quantized). Returns (loaded, missed) counts."""
    sd = model.state_dict()
    expected = set(sd.keys())
    got = set()
    for t in reader.tensors:
        hf = _MAP.get(t.name)
        if hf is None or hf not in sd:
            continue
        arr = gguf_tensor(reader, t.name)
        if t.tensor_type.name in (
            "Q8_0",
            "Q4_0",
            "Q4_1",
            "Q5_0",
            "Q5_1",
            "Q6_K",
            "Q2_K",
            "Q3_K",
            "Q4_K",
        ):
            arr = quants.dequantize(arr, qtype=t.tensor_type)
        elif arr.dtype != np.float32:
            arr = arr.astype(np.float32)
        arr = np.ascontiguousarray(arr)
        arr = np.array(arr, dtype=np.float32, order="C", copy=True)
        got.add(hf)
        sd[hf].copy_(torch.from_numpy(arr))
    missed = sorted(expected - got)
    return len(got), missed


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ramp_guard("quality retention start")
    out: dict = {
        "method": (
            "gguf lib 0.19.0 real block-dequantization (gguf.quants.dequantize) of the q8_0/q4_0 "
            "GGUF weight tensors -> fp32 -> run through the 11-layer Qwen2 torch model on CPU. "
            "ppl computed on one fixed 64-token held-out slice (first 64 BPE tokens of "
            "test-wiki-part-00000; same ids for all four states). f16 GGUF reference is the "
            "1869-state export (weight tensors stored F16)."
        ),
    }

    # ---- fixed 64-token slice from the held-out test shard ----
    tok = load_tokenizer()
    rows = orion_corpus.load_samples([TEST_SHARD])
    first_text = orion_corpus.row_text(rows[0])
    enc = tok.encode(first_text).ids
    slice_ids = enc[:SLICE_TOKENS]
    out["slice"] = {
        "source": str(TEST_SHARD),
        "row0_text_prefix": first_text[:120],
        "token_ids": [int(x) for x in slice_ids],
        "n_tokens": len(slice_ids),
        "note": "first 64 BPE ids of row 0; ppl over the 63 next-token predictions.",
    }
    print(
        "[SLICE]",
        len(slice_ids),
        "ids from",
        rows[0].get("id", "row0") if isinstance(rows[0], dict) else "row0",
    )

    # ---- GGUF inventory (actual on-disk bytes + dtype distribution) ----
    out["gguf_files"] = {}
    for q in ("f16", "q8_0", "q4_0"):
        p = GGUF_DIR / f"comp001-100m-real-{q}.gguf"
        r = GGUFReader(str(p))
        from collections import Counter

        dcount = Counter(t.tensor_type.name for t in r.tensors)
        out["gguf_files"][q] = {
            "path": str(p),
            "bytes_mb": round(p.stat().st_size / 1024**2, 1),
            "n_tensors": len(r.tensors),
            "dtype_counts": dict(dcount),
            "quantized_weight_tensors": sorted(
                t.name for t in r.tensors if t.tensor_type.name not in ("F16", "F32")
            )[:3],
            "embedding_output_dtype": {
                "token_embd.weight": next(
                    x.tensor_type.name
                    for x in r.tensors
                    if x.name == "token_embd.weight"
                ),
                "output.weight": next(
                    x.tensor_type.name for x in r.tensors if x.name == "output.weight"
                ),
            },
        }
        print(f"[GGUF {q}] {dict(dcount)}")
    out["embedding_output_quant_note"] = (
        "Even in the f16 file token_embd.weight and output.weight are stored F16 (not F32); "
        "in q8_0/q4_0 files they are block-quantized Q8_0/Q4_0 like all other weight tensors. "
        "Norm/bias tensors (56 per file) are always F32."
    )

    # ---- per-state ppl (one model in RAM at a time) ----
    out["ppl"] = {}
    states = [
        ("fp32_1919", None),
        ("fp32_1869", "f16"),
        ("q8_1869", "q8_0"),
        ("q4_1869", "q4_0"),
    ]
    for label, qfile in states:
        t0 = time.perf_counter()
        if qfile is None:
            model, cfgd, step, losses, _, note = load_model_from_checkpoint(CKPT_DIR)
            src = f"checkpoint-{step} checkpoint.pt ({note})"
        else:
            model, _cfg = build_model()
            r = GGUFReader(str(GGUF_DIR / f"comp001-100m-real-{qfile}.gguf"))
            n_loaded, missed = load_state_from_gguf(model, r)
            src = f"GGUF {qfile} (1869-state export)"
            if missed:
                print(f"[WARN {label}] missing HF keys: {missed}")
        res = ppl_ids(model, slice_ids)
        res["rss_after_load_mb"] = round(peak_rss_mb(), 1)
        res["load_s"] = round(time.perf_counter() - t0, 2)
        res["source"] = src
        out["ppl"][label] = res
        print(
            f"[PPL {label}] loss={res['loss']} ppl={res['ppl']} ({src}) rss={res['rss_after_load_mb']} MB"
        )
        del model
        gc.collect()

    # ---- per-tensor SNR of quantized weights vs f16 reference ----
    ref = GGUFReader(str(GGUF_DIR / "comp001-100m-real-f16.gguf"))
    ref_name2t = {t.name: t for t in ref.tensors}
    out["snr"] = {}
    for q in ("q8_0", "q4_0"):
        r = GGUFReader(str(GGUF_DIR / f"comp001-100m-real-{q}.gguf"))
        rows_out = []
        for t in r.tensors:
            if t.tensor_type.name not in ("Q8_0", "Q4_0"):
                continue  # F32 norm/bias tensors are lossless
            ref_t = ref_name2t[t.name]
            dq = quants.dequantize(np.asarray(t.data), qtype=t.tensor_type)
            rv = np.asarray(ref_t.data).astype(np.float32)
            snr = 10.0 * math.log10(
                float((rv**2).sum()) / float(((rv - dq) ** 2).sum() + 1e-12)
            )
            rows_out.append({"name": t.name, "snr_db": round(snr, 2)})
        snrs = np.array([x["snr_db"] for x in rows_out])
        out["snr"][q] = {
            "n_weight_tensors": len(rows_out),
            "global_mean_snr_db": round(float(snrs.mean()), 2),
            "global_min_snr_db": round(float(snrs.min()), 2),
            "worst_tensor": min(rows_out, key=lambda x: x["snr_db"])["name"],
            "per_tensor": rows_out,
        }
        print(
            f"[SNR {q}] mean={snrs.mean():.2f} dB min={snrs.min():.2f} dB worst={min(rows_out, key=lambda x: x['snr_db'])['name']}"
        )

    # ---- Q4_K_M: BLOCKED (no quantize toolchain) ----
    out["q4_k_m"] = {
        "classification": "BLOCKED",
        "reason": (
            "No llama-quantize.exe / quantize binary on this box: third_party/BitNet/build/bin "
            "contains only llama-cli.exe; PATH search found none. gguf 0.19.0 K-quant quantize "
            "raises NotImplementedError (verified in earlier runs, recorded in "
            "logs/training_runs.jsonl comp001-100m-real-gguf-matrix runs). No Q4_K_M .gguf file "
            "exists on disk. NO Q4_K_M quality number is reported because none was measured."
        ),
    }
    out["meta"] = {
        "gguf_version": "0.19.0",
        "torch": torch.__version__,
        "cpu_count": psutil.cpu_count(),
        "free_ram_mb_end": round(free_ram_mb(), 1),
    }
    (OUT_DIR / "quality_retention.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )
    print(f"\n[DONE] wrote {OUT_DIR / 'quality_retention.json'}")


if __name__ == "__main__":
    main()
