"""Model construction for the hive sizes.

`tiny`  = vocab 10240, hidden 64, 2 layers -> ~1.44M params (mechanics proof
          and the controlled-work comparisons).
`10m`   = the existing COMP-001 10m architecture (hidden 256, mlp 1024,
         8 layers, 4 heads) at the real 10,240-token BPE vocab -> ~13.6M
         params, ~54 MB fp32 state_dict.
Both are plain dense Qwen2ForCausalLM from random init (CPU).
"""

import torch
from transformers import Qwen2Config, Qwen2ForCausalLM

PAD_ID, BOS_ID, EOS_ID = 0, 1, 2
MAX_LEN = 512

MODEL_CFG = {
    "tiny": dict(
        vocab_size=10240,
        hidden_size=64,
        intermediate_size=256,
        num_hidden_layers=2,
        num_attention_heads=2,
        num_key_value_heads=2,
        max_position_embeddings=MAX_LEN,
        pad_token_id=PAD_ID,
        bos_token_id=BOS_ID,
        eos_token_id=EOS_ID,
        tie_word_embeddings=False,
    ),
    "10m": dict(
        vocab_size=10240,
        hidden_size=256,
        intermediate_size=1024,
        num_hidden_layers=8,
        num_attention_heads=4,
        num_key_value_heads=4,
        max_position_embeddings=MAX_LEN,
        pad_token_id=PAD_ID,
        bos_token_id=BOS_ID,
        eos_token_id=EOS_ID,
        tie_word_embeddings=False,
    ),
}

SIZES = tuple(MODEL_CFG)


def build_model(size: str, seed: int = 42):
    """(model, cfg_dict, n_params). Model is created fresh (random init)."""
    if size not in MODEL_CFG:
        raise ValueError(f"unknown model size {size!r}, choose from {SIZES}")
    cfg = dict(MODEL_CFG[size])
    torch.manual_seed(seed)
    model = Qwen2ForCausalLM(Qwen2Config(**cfg))
    n_params = sum(p.numel() for p in model.parameters())
    return model, cfg, n_params
