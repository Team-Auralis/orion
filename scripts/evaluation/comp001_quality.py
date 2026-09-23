#!/usr/bin/env python3
"""COMP-001 offline quality probe (Task 4).

A deliberately boring, fully offline probe for any COMP-001 from-scratch
export: a fixed list of 20 simple reasoning/language items (10 next-token
completions + 10 short generations) with canonical answers, scored by greedy
completion match (exact, normalized) and by top-1 token match. No dataset
download, no external corpus - the items are hardcoded below.

CLI:
    python scripts/evaluation/comp001_quality.py --model models/comp001/100m/
        [--tokenizer models/tokenizer_bpe]

Prints per-item results and a summary, then a parseable PROBE_SCORE=<frac>
line (completion accuracy, 0-1). The training harness records that fraction
as `quality_probe_score` in the experiment ledger.

Scoring is exact-match only. A from-scratch smoke model trained on ~2k tokens
is expected to score low; that is the honest signal for a SMOKE_RUN, not a
quality claim.
"""

import argparse
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "training"))

import numpy as np  # noqa: E402
import torch  # noqa: E402
from transformers import Qwen2Config, Qwen2ForCausalLM  # noqa: E402

import orion_corpus  # noqa: E402

MAX_NEW_TOKENS = 12

# (prompt, canonical answer) - fixed, boring, exact-match scored.
PROBE_ITEMS = [
    # --- 10 next-token completions -----------------------------------------
    (
        "INSTRUCTION: What is the capital of France?\nRESPONSE: The capital of France is",
        "paris",
    ),
    (
        "INSTRUCTION: What does two plus two equal?\nRESPONSE: Two plus two equals",
        "four",
    ),
    (
        "INSTRUCTION: What color is the sky on a clear day?\nRESPONSE: The sky is",
        "blue",
    ),
    (
        "INSTRUCTION: At what temperature does water freeze?\nRESPONSE: Water freezes at zero degrees",
        "celsius",
    ),
    (
        "INSTRUCTION: What is the largest planet in our solar system?\nRESPONSE: The largest planet is",
        "jupiter",
    ),
    (
        "INSTRUCTION: What is the opposite of hot?\nRESPONSE: The opposite of hot is",
        "cold",
    ),
    (
        "INSTRUCTION: What animal says meow?\nRESPONSE: The animal that says meow is a",
        "cat",
    ),
    (
        "INSTRUCTION: What month comes after January?\nRESPONSE: The month after January is",
        "february",
    ),
    ("INSTRUCTION: Where does the sun rise?\nRESPONSE: The sun rises in the", "east"),
    (
        "INSTRUCTION: What does one plus one equal?\nRESPONSE: One plus one equals",
        "two",
    ),
    # --- 10 held-out generations --------------------------------------------
    (
        "INSTRUCTION: What is the opposite of up?\nRESPONSE: The opposite of up is",
        "down",
    ),
    (
        "INSTRUCTION: What is the largest ocean on Earth?\nRESPONSE: The largest ocean is the",
        "pacific",
    ),
    (
        "INSTRUCTION: How many sides does a triangle have?\nRESPONSE: A triangle has three",
        "sides",
    ),
    (
        "INSTRUCTION: What planet do we live on?\nRESPONSE: The planet we live on is called",
        "earth",
    ),
    (
        "INSTRUCTION: What is the first letter of the alphabet?\nRESPONSE: The first letter is",
        "a",
    ),
    (
        "INSTRUCTION: What season follows winter?\nRESPONSE: The season after winter is",
        "spring",
    ),
    (
        "INSTRUCTION: How many corners does a square have?\nRESPONSE: A square has four",
        "corners",
    ),
    (
        "INSTRUCTION: What is the opposite of left?\nRESPONSE: The opposite of left is",
        "right",
    ),
    ("INSTRUCTION: How many days are in a week?\nRESPONSE: A week has", "seven"),
    ("INSTRUCTION: What color is grass?\nRESPONSE: The color of grass is", "green"),
]


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def safe(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


# GGUF tensor name -> HF state-dict key (reverse of the in-repo converter map).
_GGUF_TO_HF = {
    "token_embd.weight": "model.embed_tokens.weight",
    "output_norm.weight": "model.norm.weight",
    "output.weight": "lm_head.weight",
}
for _i in range(64):
    _GGUF_TO_HF[f"blk.{_i}.attn_norm.weight"] = (
        f"model.layers.{_i}.input_layernorm.weight"
    )
    _GGUF_TO_HF[f"blk.{_i}.ffn_norm.weight"] = (
        f"model.layers.{_i}.post_attention_layernorm.weight"
    )
    for _src, _dst in (
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
    ):
        _GGUF_TO_HF[f"blk.{_i}.{_src}"] = f"model.layers.{_i}.{_dst}"

SUPPORTED_GGUF_QTYPES = ("F16", "F32", "Q4_0", "Q8_0")


def _gguf_tensor_to_np(t) -> np.ndarray:
    """Dequantize one gguf ReaderTensor back to an fp32 numpy array."""
    from gguf.constants import GGMLQuantizationType as T
    from gguf.quants import dequantize

    if t.tensor_type == T.F32:
        return np.ascontiguousarray(t.data, dtype=np.float32)
    if t.tensor_type == T.F16:
        return np.ascontiguousarray(t.data, dtype=np.float16).astype(np.float32)
    if t.tensor_type in (T.Q4_0, T.Q8_0):
        packed = np.ascontiguousarray(t.data, dtype=np.uint8)
        return dequantize(packed, t.tensor_type).astype(np.float32)
    raise ValueError(f"unsupported gguf quant type {t.tensor_type} for probe")


def load_gguf_state_dict(gguf_path: Path) -> dict:
    """Load a GGUF file (f16/q8_0/q4_0) into an HF state-dict via the gguf
    python package dequantization path -- no llama.cpp runtime required."""
    from gguf import GGUFReader

    reader = GGUFReader(str(gguf_path))
    missing = []
    state = {}
    for t in reader.tensors:
        key = _GGUF_TO_HF.get(t.name)
        if key is None:
            missing.append(t.name)
            continue
        arr = _gguf_tensor_to_np(t)
        state[key] = torch.from_numpy(arr)
    return state, missing


def build_gguf_model(gguf_path: Path, hf_dir: Path):
    """Qwen2ForCausalLM restored from a GGUF (weights dequantized to fp32).

    GGUF linear/embed tensors are stored in the same (out, in) / (vocab, dim)
    layouts as the HF model, so state-dict keys load 1:1 (verified by the
    converter's round-trip probe_max_abs_err.)
    """
    cfg = Qwen2Config.from_pretrained(str(hf_dir))
    model = Qwen2ForCausalLM(cfg)
    state, missing = load_gguf_state_dict(gguf_path)
    model.load_state_dict(state, strict=True)
    model.eval()
    return model, missing


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--model", required=True, help="HF export dir (config.json + model.safetensors)"
    )
    ap.add_argument(
        "--gguf",
        default=None,
        help="optional .gguf file to probe instead of the HF dir; dequantized "
        "to fp32 via the gguf python package (f16/q8_0/q4_0 only)",
    )
    ap.add_argument(
        "--tokenizer",
        default=str(REPO_ROOT / "models" / "tokenizer_bpe"),
        help="BPE tokenizer dir (default: models/tokenizer_bpe)",
    )
    args = ap.parse_args()

    model_dir = Path(args.model)
    if args.gguf:
        gguf_path = Path(args.gguf)
        if re.search(r"q[1-6]_k(_[sm])?|iq[1-4]_", gguf_path.name, re.I):
            # K-quant / lower-bit gguf: only llama.cpp can produce these, and
            # the gguf python package cannot dequantize them -> not measurable.
            print(
                "[PROBE] lower-bit / K-quant gguf: quality not measurable "
                "without llama.cpp; not_measured_requires_llama.cpp"
            )
            return 0
        if not gguf_path.is_file():
            raise SystemExit(f"[PROBE] no gguf file at {gguf_path}")
        tokenizer = orion_corpus.load_bpe_compat()
        model, missing = build_gguf_model(gguf_path, model_dir)
        if missing:
            print(
                f"[PROBE] warning: {len(missing)} gguf tensors unmapped: {missing[:5]}"
            )
        model_dir = gguf_path  # keep a human-readable label below
    else:
        if not (model_dir / "config.json").exists():
            raise SystemExit(
                f"[PROBE] no HF export found at {model_dir} (need config.json)"
            )
        tokenizer = orion_corpus.load_bpe_compat()
        model = Qwen2ForCausalLM.from_pretrained(str(model_dir))
    model.eval()

    n_items = len(PROBE_ITEMS)
    top1_hits = 0
    comp_hits = 0
    rows = []
    t0 = time.time()
    with torch.no_grad():
        for i, (prompt, answer) in enumerate(PROBE_ITEMS, 1):
            input_ids = torch.tensor([tokenizer.encode(prompt).ids], dtype=torch.long)
            out_ids = model.generate(
                input_ids=input_ids,
                max_new_tokens=MAX_NEW_TOKENS,
                do_sample=False,
                pad_token_id=orion_corpus.PAD_ID,
                eos_token_id=orion_corpus.EOS_ID,
            )
            completion = tokenizer.decode(
                out_ids[0, input_ids.shape[1] :].tolist(),
                skip_special_tokens=True,
            )
            nc, na = norm(completion), norm(answer)
            words = nc.split()
            first_token = words[0] if words else ""
            top1_hit = bool(na and first_token == na)
            comp_hit = bool(na and (na in nc or nc == na))
            top1_hits += top1_hit
            comp_hits += comp_hit
            mark = "OK " if comp_hit else "XX "
            rows.append(
                (
                    i,
                    mark,
                    prompt.replace("\n", " ")[:60],
                    safe(completion),
                    answer,
                    top1_hit,
                    comp_hit,
                )
            )
            print(
                f"  [{i:2d}] {mark} prompt={rows[-1][2]}... "
                f"completion={rows[-1][3]!r} answer={answer} "
                f"(top1={'Y' if top1_hit else 'N'}, comp={'Y' if comp_hit else 'N'})"
            )

    elapsed = time.time() - t0
    top1_acc = top1_hits / n_items
    comp_acc = comp_hits / n_items
    print(
        f"\n[PROBE] items={n_items} | top-1 token accuracy={top1_acc:.2f} "
        f"({top1_hits}/{n_items}) | completion accuracy={comp_acc:.2f} "
        f"({comp_hits}/{n_items}) | {elapsed:.1f}s"
    )
    print(f"PROBE_SCORE={comp_acc:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
