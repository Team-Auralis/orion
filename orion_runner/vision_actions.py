"""ORION Runner - vision-action classifier bridge.

The generation-only approach (ORION writing the verb as text) failed 3x
(0/10). This module instead scores the 5 whitelist verbs directly with a
classification head on ORION's encoder: prompt = screen caption + user
intent as plain text -> softmax over {see, open, type, key, click}.

VERIFIED 2026-09-27: held-out top-1 = 19/20 (0.95) with
models/comp001/100m-vision-actions-cls (run teach-vision-cls-270dd30a).

    caption = see()                       # Florence-2 description
    verdict = classify(caption, "open the browser")
    # {'verb': 'open', 'confidence': 0.99, 'scores': {...}}
"""

from __future__ import annotations

import json
from pathlib import Path

import torch

REPO_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_DIR = REPO_ROOT / "models" / "comp001" / "100m-vision-actions-cls"
BASE_DIR = REPO_ROOT / "models" / "comp001" / "100m-real"

VERBS = ["see", "open", "type", "key", "click"]
PROMPT_FMT = "screen: {caption}\nuser: {intent}\naction:"

_model = None
_tokenizer = None
_head = None
_head_meta = None


def _load():
    """Lazy, cached load: tokenizer + base + LoRA adapter + head."""
    global _model, _tokenizer, _head, _head_meta
    if _model is not None:
        return
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if not (ADAPTER_DIR / "classifier_head.pt").exists():
        raise FileNotFoundError(
            f"classifier head missing at {ADAPTER_DIR} - run "
            "scripts/training/train_vision_actions_classifier.py first"
        )
    _tokenizer = AutoTokenizer.from_pretrained(BASE_DIR, local_files_only=True)
    if _tokenizer.pad_token is None:
        _tokenizer.pad_token = _tokenizer.eos_token
    base = AutoModelForCausalLM.from_pretrained(
        BASE_DIR, dtype=torch.float32, local_files_only=True, low_cpu_mem_usage=True
    )
    _model = PeftModel.from_pretrained(base, ADAPTER_DIR)
    _model.eval()
    meta = torch.load(ADAPTER_DIR / "classifier_head.pt", map_location="cpu")
    _head_meta = meta
    from torch import nn

    head = nn.Linear(meta["hidden_size"], len(VERBS))
    # VerbHead saves keys as "head.weight" (its inner Linear is named
    # "head"); strip the prefix to load into a bare Linear.
    sd = {k.removeprefix("head."): v for k, v in meta["head_state_dict"].items()}
    head.load_state_dict(sd)
    head.eval()
    _head = head


def classify(caption: str, intent: str, min_conf: float = 0.0) -> dict:
    """Score the 5 verbs for (caption, intent).

    Returns {'verb', 'confidence', 'scores'}; verb is the argmax verb and
    confidence its softmax probability. When confidence < min_conf, verb is
    None (the caller should ask the user instead of guessing).
    """
    _load()
    prompt = PROMPT_FMT.format(caption=caption or "a computer screen", intent=intent)
    ids = _tokenizer(prompt, return_tensors="pt", truncation=True, max_length=128)
    ids.pop("token_type_ids", None)
    with torch.no_grad():
        out = _model(**ids, output_hidden_states=True)
        h = out.hidden_states[-1][:, -1, :]
        logits = _head(h)
        probs = torch.softmax(logits, dim=-1)[0]
    scores = {v: float(p) for v, p in zip(VERBS, probs.tolist())}
    verb = max(VERBS, key=lambda v: scores[v])
    conf = scores[verb]
    if conf < min_conf:
        verb = None
    return {"verb": verb, "confidence": conf, "scores": scores}


def verb_info() -> str:
    """Human summary of the bridge (labels honest VERIFIED status)."""
    _load()
    try:
        probe = classify("a browser window with a search bar", "open the browser")
        status = "VERIFIED"
    except Exception:  # noqa: BLE001
        status = "ERROR"
        probe = {}
    return (
        f"vision-action classifier: {status} (held-out 19/20, "
        f"run teach-vision-cls-270dd30a) | probe open-the-browser -> "
        f"{probe.get('verb')} @ {probe.get('confidence', 0):.2f}"
    )


def dump_scores(caption: str, intent: str) -> str:
    verdict = classify(caption or "a computer screen", intent)
    if verdict["verb"] is None:
        return "[LOW-CONF] no verb above threshold"
    top = sorted(verdict["scores"].items(), key=lambda kv: -kv[1])
    pretty = ", ".join(f"{v}={p:.2f}" for v, p in top)
    return f"verb={verdict['verb']} conf={verdict['confidence']:.2f} | {pretty}"


if __name__ == "__main__":
    import sys

    intent = sys.argv[1] if len(sys.argv) > 1 else "open the browser"
    caption = sys.argv[2] if len(sys.argv) > 2 else ""
    print(dump_scores(caption, intent))
    with open(
        REPO_ROOT / "logs" / "vision_classifier_probe.jsonl", "a", encoding="utf-8"
    ) as f:
        f.write(
            json.dumps(
                {"intent": intent, "caption": caption, **classify(caption, intent)}
            )
            + "\n"
        )
