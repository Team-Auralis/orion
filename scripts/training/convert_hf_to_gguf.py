#!/usr/bin/env python3
"""Convert a local Qwen2 / Qwen2.5 HF model directory to a GGUF file.

Numpy-only (no torch / transformers import) so it runs on a RAM-starved
7.7 GB laptop: config.json + tokenizer.json are read as plain JSON and
safetensors weights stream via `safe_open` one tensor at a time.

Weights are quantized to GGML Q8_0 blocks (like official Qwen GGUFs);
RMS-norm weights and attention biases stay F32.

Usage:
    python scripts/training/convert_hf_to_gguf.py models/qwen_instruct data/training/orion.gguf
"""

import argparse
import json
import struct
import sys
from pathlib import Path

import numpy as np
from gguf import GGUFWriter, GGMLQuantizationType

_NP_DTYPES = {
    "F64": ("<f8", 8),
    "F32": ("<f4", 4),
    "F16": ("<f2", 2),
    "BF16": ("<u2", 2),
    "I64": ("<i8", 8),
    "I32": ("<i4", 4),
    "I16": ("<i2", 2),
    "I8": ("<i1", 1),
    "U64": ("<u8", 8),
    "U32": ("<u4", 4),
    "U16": ("<u2", 2),
    "U8": ("<u1", 1),
    "BOOL": ("|u1", 1),
}


class STReader:
    """Minimal safetensors reader: header offsets + raw byte reads (numpy).
    No torch import; BF16 streamed chunk-by-chunk to keep peak RAM low."""

    def __init__(self, path: Path):
        self.f = open(path, "rb")
        header_len = struct.unpack("<Q", self.f.read(8))[0]
        header = json.loads(self.f.read(header_len))
        self.data_start = 8 + header_len
        self.meta = {}
        for key, info in header.items():
            if key == "__metadata__":
                continue
            begin, end = info["data_offsets"]
            self.meta[key] = (info["dtype"], tuple(info["shape"]), begin, end)

    def get(self, key: str, row0: int = None, rows: int = None):
        dtype, shape, begin, end = self.meta[key]
        np_dtype, elem = _NP_DTYPES[dtype]
        if row0 is None:
            span = (end - begin) // elem
            self.f.seek(self.data_start + begin)
            buf = self.f.read(end - begin)
            arr = np.frombuffer(buf, dtype=np_dtype).reshape(shape)
        else:
            ncols = shape[-1]
            off = row0 * ncols * elem
            nbytes = rows * ncols * elem
            self.f.seek(self.data_start + begin + off)
            buf = self.f.read(nbytes)
            arr = np.frombuffer(buf, dtype=np_dtype).reshape(rows, ncols)
        if dtype == "BF16":
            arr = ((arr.astype(np.uint32)) << 16).view(np.float32)
        return arr

    def shapes(self):
        return {k: v[1] for k, v in self.meta.items()}

    def close(self):
        self.f.close()


EXPECTED_GLOBAL = {
    "model.embed_tokens.weight": "token_embd.weight",
    "model.norm.weight": "output_norm.weight",
    "lm_head.weight": "output.weight",  # untied models (comp001); skipped if absent
}
PER_LAYER = {
    "input_layernorm.weight": "blk.{i}.attn_norm.weight",
    "self_attn.q_proj.weight": "blk.{i}.attn_q.weight",
    "self_attn.q_proj.bias": "blk.{i}.attn_q.bias",
    "self_attn.k_proj.weight": "blk.{i}.attn_k.weight",
    "self_attn.k_proj.bias": "blk.{i}.attn_k.bias",
    "self_attn.v_proj.weight": "blk.{i}.attn_v.weight",
    "self_attn.v_proj.bias": "blk.{i}.attn_v.bias",
    "self_attn.o_proj.weight": "blk.{i}.attn_output.weight",
    "post_attention_layernorm.weight": "blk.{i}.ffn_norm.weight",
    "mlp.gate_proj.weight": "blk.{i}.ffn_gate.weight",
    "mlp.down_proj.weight": "blk.{i}.ffn_down.weight",
    "mlp.up_proj.weight": "blk.{i}.ffn_up.weight",
}

QWEN2_META = (
    ("block_count", "num_hidden_layers"),
    ("context_length", "max_position_embeddings"),
    ("embedding_length", "hidden_size"),
    ("feed_forward_length", "intermediate_size"),
    ("attention.head_count", "num_attention_heads"),
    ("attention.head_count_kv", "num_key_value_heads"),
    ("attention.layer_norm_rms_epsilon", "rms_norm_eps"),
    ("rope.freq_base", "rope_theta"),
)

F32_KEYS = ("_norm.weight", ".bias")


def _np_roundf(n: np.ndarray) -> np.ndarray:
    """llama.cpp roundf semantics (round half away from zero), mirror of gguf.quants."""
    a = np.abs(n)
    floored = np.floor(a)
    b = floored + np.floor(2 * (a - floored))
    return np.sign(n) * b


def quant_q8_0_along(
    f32data: np.ndarray, block: int = 32, row_chunk: int = 1024
) -> np.ndarray:
    """Pack F32 weights into GGML Q8_0 blocks (f16 scale d + 32 x i8, dequant
    d*qs) along the fastest (last) axis. Streams row chunks for low RAM.

    Bit-exact mirror of gguf.quants.Q8_0 (llama.cpp reference layout)."""
    x = np.ascontiguousarray(f32data, dtype=np.float32)
    rows, cols = x.shape
    if cols % block:
        raise ValueError(f"last dim {cols} not divisible by {block}")
    bytes_per_row = cols // block * (2 + block)
    out = np.empty((rows, bytes_per_row), dtype=np.uint8)
    for r0 in range(0, rows, row_chunk):
        chunk = x[r0 : r0 + row_chunk]
        rows_in = chunk.shape[0]
        groups = chunk.reshape(-1, block)
        with np.errstate(divide="ignore"):
            d = np.abs(groups).max(axis=1, keepdims=True) / 127.0
            id = np.where(d == 0, 0, 1.0 / d)
        qs = _np_roundf(groups * id).astype(np.int8).view(np.uint8)
        d_bytes = d.astype(np.float16).view(np.uint8).reshape(-1, 2)
        packed = np.concatenate([d_bytes, qs], axis=1)  # (rows_in*32, 34)
        out[r0 : r0 + rows_in] = packed.reshape(rows_in, bytes_per_row)
    return out


def quant_q4_0_along(
    f32data: np.ndarray, block: int = 32, row_chunk: int = 4096
) -> np.ndarray:
    """Pack F32 weights into GGML Q4_0 blocks (llama.cpp byte layout).

    Bit-exact mirror of gguf.quants.Q4_0: block 32, f16 scale d = max/-8,
    qs = trunc(x/d + 8.5) in [0,15], low nibble = element j, high nibble =
    element j+16. Scale stays F32 for the id computation (cast to F16 only
    when the 2-byte scale is stored).
    """
    x = np.ascontiguousarray(f32data, dtype=np.float32)
    rows, cols = x.shape
    if cols % block:
        raise ValueError(f"last dim {cols} not divisible by {block}")
    bytes_per_row = cols // block * (2 + block // 2)
    out = np.empty((rows, bytes_per_row), dtype=np.uint8)
    for r0 in range(0, rows, row_chunk):
        chunk = x[r0 : r0 + row_chunk]
        rows_in = chunk.shape[0]
        groups = chunk.reshape(-1, block)
        imax = np.abs(groups).argmax(axis=1, keepdims=True)
        maxv = np.take_along_axis(groups, imax, axis=1)
        d = maxv / -8.0
        with np.errstate(divide="ignore"):
            id = np.where(d == 0, 0, 1.0 / d)
        qs = np.trunc((groups * id) + np.float32(8.5)).astype(np.uint8).clip(0, 15)
        qs = qs.reshape(-1, 2, block // 2)
        packed = (qs[..., 0, :] | (qs[..., 1, :] << np.uint8(4))).view(np.uint8)
        full = np.concatenate(
            [d.astype(np.float16).view(np.uint8).reshape(-1, 2), packed], axis=1
        )
        out[r0 : r0 + rows_in] = full.reshape(rows_in, bytes_per_row)
    return out


_QUANTIZERS = {"q8_0": quant_q8_0_along, "q4_0": quant_q4_0_along}
_FILE_TYPES = {"f16": 1, "q4_0": 2, "q8_0": 7}


def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def word_id(tok: str) -> str:
    # GGUF requires bytes in token strings; JSON has them as unicode chars that
    # are the raw BPE contents (incl. '\u0120'), so keep them as-is.
    return tok


def build_vocab(hf_dir: Path, vocab_size: int):
    tj = load_json(hf_dir / "tokenizer.json")
    full = [""] * vocab_size
    for tok, tid in tj.get("model", {}).get("vocab", {}).items():
        if isinstance(tid, int) and 0 <= tid < vocab_size:
            full[tid] = tok
    special = set()
    for item in tj.get("added_tokens", []):
        tid = item.get("id")
        if isinstance(tid, int) and 0 <= tid < vocab_size:
            if not full[tid]:
                full[tid] = item.get("content", "")
            if item.get("special"):
                special.add(item.get("content", ""))
    for tid in range(vocab_size):
        if not full[tid]:
            full[tid] = f"<|unused_{tid}|>"
    types = [3 if t in special else 1 for t in full]
    merges_src = tj.get("model", {}).get("merges", [])
    merges = []
    for m in merges_src:
        if isinstance(m, (list, tuple)) and len(m) == 2:
            merges.append(f"{m[0]} {m[1]}")
        elif isinstance(m, str):
            merges.append(m)
    return full, types, merges


def convert(hf_dir, out_path, quant: str = "q4_0"):
    if quant not in _QUANTIZERS and quant != "f16":
        raise ValueError(f"quant must be one of q4_0, q8_0, f16 (got {quant!r})")
    hf_dir = Path(hf_dir)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cfg = load_json(hf_dir / "config.json")
    vocab_size = int(cfg.get("vocab_size", 151936))

    writer = GGUFWriter(out_path.as_posix(), "qwen2")
    writer.add_name(cfg.get("_name_or_path", "orion"))
    for gguf_key, hf_key in QWEN2_META:
        val = cfg.get(hf_key, None if hf_key != "rope_theta" else 10000.0)
        if val is None:
            print(f"  [!] config missing {hf_key}")
            continue
        if gguf_key == "attention.layer_norm_rms_epsilon":
            writer.add_layer_norm_rms_eps(float(val))
        elif gguf_key.endswith(".freq_base"):
            writer.add_rope_freq_base(float(val))
        elif gguf_key == "block_count":
            writer.add_block_count(int(val))
        elif gguf_key == "context_length":
            writer.add_context_length(int(val))
        elif gguf_key == "embedding_length":
            writer.add_embedding_length(int(val))
        elif gguf_key == "feed_forward_length":
            writer.add_feed_forward_length(int(val))
        elif gguf_key == "attention.head_count":
            writer.add_head_count(int(val))
        elif gguf_key == "attention.head_count_kv":
            writer.add_head_count_kv(int(val))
    head_dim = int(cfg.get("head_dim", 0)) or (
        int(cfg["hidden_size"]) // int(cfg["num_attention_heads"])
    )
    writer.add_rope_dimension_count(head_dim)

    tokens, token_types, merges = build_vocab(hf_dir, vocab_size)
    writer.add_tokenizer_model("gpt2")
    writer.add_token_list(tokens)
    writer.add_token_scores([0.0] * len(tokens))
    writer.add_token_types(token_types)
    if merges:
        writer.add_array("tokenizer.ggml.merges", merges)
    tcfg = load_json(hf_dir / "tokenizer_config.json")
    writer.add_bos_token_id(int(tcfg.get("bos_token_id", 0) or 0))
    writer.add_eos_token_id(int(tcfg.get("eos_token_id", 0) or 0))
    writer.add_uint32(
        "tokenizer.ggml.padding_token_id", int(tcfg.get("pad_token_id", 0) or 0)
    )
    writer.add_add_bos_token(False)
    writer.add_add_eos_token(True)

    n_layers = int(cfg["num_hidden_layers"])
    st = hf_dir / "model.safetensors"
    st = STReader(st)
    shapes = st.shapes()

    def emit_quant(name: str, key: str, shape, quant):
        rows, cols = shape
        bpr = cols // 32 * (34 if quant == "q8_0" else 18)
        out = np.empty((rows, bpr), dtype=np.uint8)
        for r0 in range(0, rows, 512):
            data = st.get(key, row0=r0, rows=min(512, rows - r0))
            if not data.flags["C_CONTIGUOUS"]:
                data = np.ascontiguousarray(data)
            out[r0 : r0 + data.shape[0]] = _QUANTIZERS[quant](data)
        return out

    def emit(name: str, key: str, quant):
        shape = shapes[key]
        if (
            quant != "f16"
            and len(shape) == 2
            and not key.endswith(F32_KEYS)
            and shape[-1] % 32 == 0
        ):
            u8 = emit_quant(name, key, shape, quant)
            writer.add_tensor(
                name,
                u8,
                raw_dtype=GGMLQuantizationType.Q4_0
                if quant == "q4_0"
                else GGMLQuantizationType.Q8_0,
            )
            return
        data = st.get(key)
        if quant == "f16" and len(shape) == 2:
            data = data.astype(np.float16)  # weights -> F16 (HF export is F32)
        elif data.dtype == np.float32 or data.dtype == np.float16:
            pass
        elif len(shape) < 2:
            data = data.astype(np.float32)  # norms stay F32
        else:
            data = data.astype(np.float16)
        writer.add_tensor(name, np.ascontiguousarray(data))

    for layer in range(n_layers):
        for hf_suffix, gguf_dst in PER_LAYER.items():
            key = f"model.layers.{layer}.{hf_suffix}"
            if key not in shapes:
                print(f"  [!] missing {key}")
                continue
            emit(gguf_dst.format(i=layer), key, quant)
    for hf_key, gguf_key in EXPECTED_GLOBAL.items():
        if hf_key in shapes:
            emit(gguf_key, hf_key, quant)
        elif gguf_key not in ("output_norm.weight", "output.weight"):
            print(f"  [!] missing {hf_key}")
    st.close()

    writer.add_file_type(_FILE_TYPES[quant])
    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_tensors_to_file()
    writer.close()
    size = out_path.stat().st_size / (1024**3)
    print(f"[convert] wrote {out_path} ({size:.2f} GB)")


if __name__ == "__main__":
    import argparse as _ap

    ap = _ap.ArgumentParser(description="Qwen2 HF -> GGUF converter (numpy-only)")
    ap.add_argument("hf_dir", type=str)
    ap.add_argument("out", type=str)
    ap.add_argument(
        "--q4",
        action="store_true",
        default=True,
        help="quantize linear weights to Q4_0 (default; fits small VRAM)",
    )
    ap.add_argument("--q8", action="store_true", help="quantize linear weights to Q8_0")
    ap.add_argument("--f16", action="store_true", help="keep weights F16")
    args = ap.parse_args()
    quant = "q8_0" if args.q8 else "f16" if args.f16 else "q4_0"
    try:
        convert(args.hf_dir, args.out, quant=quant)
    except Exception as e:
        import traceback

        traceback.print_exc()
        sys.exit(2)
