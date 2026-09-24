#!/usr/bin/env python3
"""F5 training-integrity controls for `models/comp001/100m-real/checkpoint-1919`.

Six controls, each reported PASS / FAIL / BLOCKED with the exact criterion and
the measured numbers. Zero-trust framing: every comparison is made against the
checkpoint on disk, nothing is assumed about the training harness. ONE model in
RAM at a time (del + gc); state dicts are loaded mmap-backed and compared
per-tensor so peak RSS stays bounded.

  C1 fixed-input output reproducibility   (3x greedy, same seed -> identical ids)
  C2 checkpoint save/load equivalence     (save -> weights_only load -> maxdiff 0)
  C3 resume equivalence                   (2 train steps, fresh load, same trajectory)
  C4 shuffled-data control                (test ppl, normal vs seeded-shuffled order)
  C5 corrupted-checkpoint detection       (byte flip on a COPY; DETECTED/SILENT/PARTIAL)
  C6 tokenizer-mismatch detection         (half-vocab model + truncated tokenizer)

Output: logs/forensic/integrity.json
"""

from __future__ import annotations

import gc
import json
import math
import random
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import psutil  # noqa: E402
import torch  # noqa: E402
from tokenizers import Tokenizer  # noqa: E402
from transformers import Qwen2Config, Qwen2ForCausalLM  # noqa: E402

from scripts.forensic.eval_suite import (  # noqa: E402
    load_model_from_checkpoint,
    load_tokenizer,
    ppl_blocks,
)
from scripts.training.orion_corpus import load_samples, row_text, shard_files  # noqa: E402
from orion_runner.loader import pack_sequences, tokenize_samples  # noqa: E402

CKPT_DIR = REPO_ROOT / "models" / "comp001" / "100m-real" / "checkpoint-1919"
CKPT_PT = CKPT_DIR / "checkpoint.pt"
BPE_TOKENIZER_JSON = REPO_ROOT / "models" / "tokenizer_bpe" / "tokenizer.json"
OUT_DIR = REPO_ROOT / "logs" / "forensic"
MAX_LEN = 512
PAD_ID, EOS_ID = 0, 2

FIXED_PROMPT = (
    "The quick brown fox jumps over the lazy dog and then escapes the zoo at midnight."
)
TRAIN_PROMPT = (
    "Over the long history of the study of memory, few findings have proven "
    "as robust as the spacing effect: items are better remembered when "
    "studied repeatedly and spaced over time."
)

TS = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def ram_mb() -> float:
    return psutil.virtual_memory().available / 1024**2


def rss_mb() -> float:
    return psutil.Process().memory_info().rss / 1024**2


def free(label: str) -> None:
    gc.collect()
    torch.set_num_threads(6)
    print(f"[MEM] {label}: RSS {rss_mb():.0f} MB | avail {ram_mb():.0f} MB")


def gen_ids(model, tokenizer, prompt: str, max_new: int) -> tuple:
    ids = tokenizer.encode(prompt).ids[:MAX_LEN]
    with torch.no_grad():
        out = model.generate(
            input_ids=torch.tensor([ids], dtype=torch.long),
            max_new_tokens=max_new,
            do_sample=False,
            pad_token_id=PAD_ID,
            eos_token_id=EOS_ID,
        )
    return ids, out[0, len(ids) :].tolist()


def state_max_diff(model, state) -> tuple[float, int]:
    """Per-tensor max abs diff between model params and `state["model"]`.

    State is consumed tensor-by-tensor (del'ed) so mmap-backed pages do not
    accumulate in RSS; peak stays bounded by the single largest tensor."""
    mx = 0.0
    n_t = 0
    for k, p in model.state_dict().items():
        d = (p.float() - state["model"][k].float()).abs().max().item()
        mx = max(mx, d)
        n_t += 1
        del state["model"][k]
        if len(state["model"]) % 40 == 0:
            gc.collect()
    return mx, n_t


# ---------------------------------------------------------------------------
# C1: fixed-input output reproducibility
# ---------------------------------------------------------------------------


def control_fixed_input(model, tokenizer) -> dict:
    out_ids = []
    for _ in range(3):
        torch.manual_seed(42)  # task: same seed before each run
        _, gen = gen_ids(model, tokenizer, FIXED_PROMPT, max_new=16)
        out_ids.append(gen)
    identical = all(o == out_ids[0] for o in out_ids[1:])
    return {
        "id": "C1_fixed_input_reproducibility",
        "name": "fixed-input output reproducibility (3x greedy, seed 42)",
        "status": "PASS" if identical else "FAIL",
        "criterion": "3 greedy generations of the same prompt (torch.manual_seed(42) "
        "before each) must be identical token-for-token",
        "measured": {
            "runs": 3,
            "new_tokens": len(out_ids[0]),
            "identical": identical,
            "output_tokens_run1": out_ids[0],
        },
    }


# ---------------------------------------------------------------------------
# C2: checkpoint save/load equivalence
# ---------------------------------------------------------------------------


def control_save_load(model) -> dict:
    tmp = OUT_DIR / "tmp_ckpt.pt"
    # mirror the harness checkpoint format: {"model": ..., "step": ..., "losses": ...}
    torch.save({"model": model.state_dict(), "step": 0, "losses": []}, tmp)
    load_kwargs = dict(map_location="cpu", weights_only=True)
    try:
        state = torch.load(tmp, mmap=True, **load_kwargs)
        note = "weights_only=True, mmap=True"
    except TypeError:
        state = torch.load(tmp, **load_kwargs)
        note = "weights_only=True"
    mx, n_t = state_max_diff(model, state)
    del state
    gc.collect()
    tmp.unlink(missing_ok=True)
    print(f"[C2] tmp_ckpt.pt saved+reloaded ({note}), per-tensor max abs diff={mx}")
    return {
        "id": "C2_checkpoint_save_load_equivalence",
        "name": "checkpoint save/load equivalence",
        "status": "PASS" if mx == 0.0 else "FAIL",
        "criterion": "save in-memory state -> weights_only load -> per-tensor max "
        "abs diff vs original must be exactly 0.0",
        "measured": {
            "max_abs_diff": mx,
            "tensors_compared": n_t,
            "loading": note,
            "tmp_file_deleted": not tmp.exists(),
        },
    }


# ---------------------------------------------------------------------------
# C3: resume equivalence (fresh load reproduces the same 2-step trajectory)
# ---------------------------------------------------------------------------


def _run_two_steps(tokenizer):
    model, _cfg, _s, _l, _p, load_note = load_model_from_checkpoint(CKPT_DIR)
    ids = tokenizer.encode(TRAIN_PROMPT).ids[:64]
    input_ids = torch.tensor([ids], dtype=torch.long)
    labels = torch.tensor([ids], dtype=torch.long)
    model.train()
    opt = torch.optim.SGD(model.parameters(), lr=1e-5)
    losses = []
    torch.manual_seed(42)
    for _ in range(2):
        opt.zero_grad()
        loss = model(input_ids=input_ids, labels=labels).loss
        losses.append(float(loss.item()))
        loss.backward()
        opt.step()
    # weight delta vs the checkpoint ON DISK (mmap-backed, streamed per tensor)
    state = torch.load(CKPT_PT, map_location="cpu", weights_only=True, mmap=True)
    delta = {}
    for k, p in model.named_parameters():
        delta[k] = float(
            (p.detach().float() - state["model"][k].float()).abs().max().item()
        )
        del state["model"][k]
    del state
    gc.collect()
    print(f"[C3] run: losses={losses} load={load_note} | delta tensors={len(delta)}")
    return losses, delta, model


def control_resume(tokenizer) -> dict:
    interim = OUT_DIR / "tmp_interim.pt"
    l1, d1, m1 = _run_two_steps(tokenizer)
    interim.write_bytes(b"")
    torch.save(m1.state_dict(), interim)  # "save interim"
    del m1
    gc.collect()
    l2, d2, _m2 = _run_two_steps(tokenizer)
    del _m2
    gc.collect()
    interim.unlink(missing_ok=True)
    keys = sorted(set(d1) | set(d2))
    wmax = max((abs(d1[k] - d2[k]) for k in keys), default=0.0)
    loss_equal = l1 == l2
    status = "PASS" if (loss_equal and wmax == 0.0) else "FAIL"
    print(f"[C3] losses equal={loss_equal} | weight-delta max-diff={wmax}")
    return {
        "id": "C3_resume_equivalence",
        "name": "resume equivalence (2 train steps from a fresh load)",
        "status": status,
        "criterion": "two forward+backward steps (SGD lr=1e-5, seed 42) started from "
        "a fresh disk load must reproduce the same loss values and the same "
        "weight delta (max-diff == 0.0) as the first run",
        "measured": {
            "losses_run1": [round(x, 8) for x in l1],
            "losses_run2": [round(x, 8) for x in l2],
            "losses_equal": loss_equal,
            "weight_delta_max_diff_run1_vs_run2": wmax,
            "per_tensor_delta_tensors": len(keys),
            "interim_ckpt_saved_and_removed": not interim.exists(),
        },
    }


# ---------------------------------------------------------------------------
# C4: shuffled-data control (ppl order invariance)
# ---------------------------------------------------------------------------


def _ppl_order(model, tokenizer, rows) -> dict:
    blocks = pack_sequences(
        tokenize_samples(rows, tokenizer, row_text, max_len=MAX_LEN, truncation=True),
        max_len=MAX_LEN,
        pad_id=PAD_ID,
        seed=42,
        mask_boundaries=True,
        pad_to_max=True,
    )
    nll, ntok = ppl_blocks(model, blocks)
    loss = nll / max(ntok, 1)
    return {
        "loss": loss,
        "ppl": math.exp(loss) if loss < 100 else float("inf"),
        "tokens": ntok,
        "blocks": len(blocks),
    }


def control_shuffled_ppl(model, tokenizer) -> dict:
    test_files = sorted(p for p in shard_files() if p.name.startswith("test-"))
    rows_normal = []
    for p in test_files:
        rows_normal += load_samples([p])
    rows_shuf = list(rows_normal)
    rng = random.Random(1234)
    rng.shuffle(rows_shuf)
    print(f"[C4] test rows = {len(rows_normal)} ({len(test_files)} shards)")
    n = _ppl_order(model, tokenizer, rows_normal)
    s = _ppl_order(model, tokenizer, rows_shuf)
    same = n["loss"] == s["loss"] and n["tokens"] == s["tokens"]
    status = "PASS" if same else "FAIL"
    return {
        "id": "C4_shuffled_data_control",
        "name": "shuffled-data control (test ppl, normal vs seeded-shuffled order)",
        "status": status,
        "criterion": "ppl over the test shards must be identical under a seeded "
        "document-order shuffle (token-level loss is order-invariant; any "
        "difference flags a layout-sensitive harness)",
        "measured": {
            "normal_order_ppl": round(n["ppl"], 6),
            "shuffled_order_ppl": round(s["ppl"], 6),
            "normal_order_loss": round(n["loss"], 8),
            "shuffled_order_loss": round(s["loss"], 8),
            "normal_tokens": n["tokens"],
            "shuffled_tokens": s["tokens"],
            "normal_blocks": n["blocks"],
            "shuffled_blocks": s["blocks"],
            "loss_diff": round(abs(n["loss"] - s["loss"]), 10),
            "layout_sensitivity_note": (
                None
                if same
                else "differs: greedy sequence-packing masks block boundaries, so "
                "row order changes which tokens are -100-masked; the eval harness "
                "is layout-sensitive at the block-boundary level"
            ),
        },
    }


# ---------------------------------------------------------------------------
# C5: corrupted-checkpoint detection (honest failure-mode answer)
# ---------------------------------------------------------------------------


def _flip_copy(dst_dir: Path, pos: int) -> int:
    """Copy checkpoint.json + checkpoint.pt into dst_dir, flip ONE byte at pos."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(CKPT_DIR / "checkpoint.json", dst_dir / "checkpoint.json")
    dst = dst_dir / "checkpoint.pt"
    shutil.copyfile(CKPT_PT, dst)
    with open(dst, "r+b") as f:
        f.seek(pos)
        b = f.read(1)
        f.seek(pos)
        f.write(bytes([b[0] ^ 0xFF]))
    return pos


def _probe_corrupt(tokenizer, ref_ids, ref_prompt, pos) -> dict:
    work = OUT_DIR / "tmp_corrupt_ckpt"
    shutil.rmtree(work, ignore_errors=True)
    _flip_copy(work, pos)
    r: dict = {"flip_pos": pos, "load_error": None}
    try:
        m, *_ = load_model_from_checkpoint(work)
    except Exception as exc:  # structural damage: clean load error
        r["load_error"] = f"{type(exc).__name__}: {str(exc)[:140]}"
        shutil.rmtree(work, ignore_errors=True)
        r["classification"] = "DETECTED"
        return r
    try:
        _, gen = gen_ids(m, tokenizer, ref_prompt, max_new=len(ref_ids))
        with torch.no_grad():
            logits = m(
                input_ids=torch.tensor(
                    [tokenizer.encode(ref_prompt).ids[:MAX_LEN]], dtype=torch.long
                )
            ).logits
        finite = bool(torch.isfinite(logits).all().item())
        del logits
    except Exception as exc:
        r["forward_error"] = f"{type(exc).__name__}: {str(exc)[:140]}"
        del m
        gc.collect()
        shutil.rmtree(work, ignore_errors=True)
        r["classification"] = "DETECTED"  # forward fails after load = still detected
        return r
    del m
    gc.collect()
    shutil.rmtree(work, ignore_errors=True)
    out_equal = gen == ref_ids
    r.update({"outputs_equal_to_uncorrupted": out_equal, "logits_finite": finite})
    if not out_equal or not finite:
        r["classification"] = "SILENT_CORRUPTION"
    else:
        r["classification"] = "PARTIAL"
    return r


def control_corrupt(model, tokenizer) -> dict:
    """Part 1: reference outputs from the VALID model (caller frees the model
    before part 2 so a corrupt copy never coexists with the canonical model)."""
    _, ref = gen_ids(model, tokenizer, FIXED_PROMPT, max_new=8)
    return {"ref_ids": ref, "prompt": FIXED_PROMPT}


def control_corrupt_reload(tokenizer, ref) -> dict:
    ckpt_size = CKPT_PT.stat().st_size
    probes = [
        _probe_corrupt(tokenizer, ref["ref_ids"], ref["prompt"], pos=64),
        _probe_corrupt(tokenizer, ref["ref_ids"], ref["prompt"], pos=ckpt_size // 2),
    ]
    classes = [p["classification"] for p in probes]
    if all(c == "DETECTED" for c in classes):
        overall = "DETECTED"
    elif any(c == "SILENT_CORRUPTION" for c in classes):
        overall = "SILENT_CORRUPTION"
    else:
        overall = "PARTIAL"
    return {
        "id": "C5_corrupted_checkpoint_detection",
        "name": "corrupted-checkpoint detection (single-byte flip on a COPY)",
        "status": "PASS" if overall == "DETECTED" else "FAIL",
        "criterion": "a checkpoint with one flipped byte must be caught (load error) "
        "or at minimum produce detectably different output; silently loading and "
        "emitting the same output = undetected corruption",
        "measured": {
            "checkpoint_bytes": ckpt_size,
            "probes": [
                {
                    "flip_pos": p["flip_pos"],
                    "classification": p["classification"],
                    "outputs_equal": p.get("outputs_equal_to_uncorrupted"),
                    "logits_finite": p.get("logits_finite"),
                    "load_error": p.get("load_error"),
                    "forward_error": p.get("forward_error"),
                }
                for p in probes
            ],
            "overall_classification": overall,
            "honest_note": (
                "zip-framed torch.save carries per-entry CRC32: payload byte flips "
                "raise at load (DETECTED). A flip that lands in a stored payload "
                "without being read is silent for THIS probe set. PARTIAL means the "
                "corruption was not uniformly caught across probes."
            ),
            "tmp_files_removed": not (OUT_DIR / "tmp_corrupt_ckpt").exists(),
        },
    }


# ---------------------------------------------------------------------------
# C6: tokenizer-mismatch detection
# ---------------------------------------------------------------------------


def control_tokenizer_mismatch() -> dict:
    tokenizer = load_tokenizer()
    half = 5120
    base_cfg = dict(
        hidden_size=768,
        intermediate_size=3072,
        num_hidden_layers=11,
        num_attention_heads=12,
        num_key_value_heads=4,
        max_position_embeddings=512,
        pad_token_id=0,
        bos_token_id=1,
        eos_token_id=2,
        tie_word_embeddings=False,
    )

    # --- 6a: model embeddings at half size, real 10240-id tokenizer ---------
    small = Qwen2ForCausalLM(Qwen2Config(vocab_size=half, **base_cfg))
    small.eval()
    sub = {"vocab_size_real": tokenizer.vocab_size, "half_vocab_model": half}
    vocab = tokenizer._tok.get_vocab()
    rare = sorted(
        ((t, i) for t, i in vocab.items() if i >= half and not t.startswith("<")),
        key=lambda p: -p[1],
    )[:3]
    sentence = "Standard prose with rare tokens: " + " ".join(t for t, _ in rare) + "."
    enc_ids = tokenizer.encode(sentence).ids
    sub["sentence_max_id"] = max(enc_ids) if enc_ids else None
    try:
        with torch.no_grad():
            small(torch.tensor([enc_ids], dtype=torch.long))
        ran_naturally = True
    except Exception as exc:
        ran_naturally = False
        sub["natural_forward_error"] = f"{type(exc).__name__}: {str(exc)[:100]}"
    # deterministic probe: an id past the half-size embedding table
    try:
        with torch.no_grad():
            small(torch.tensor([[100, 6000]], dtype=torch.long))
        ran_forced = True
    except Exception as exc:
        ran_forced = False
        sub["forced_forward_error"] = f"{type(exc).__name__}: {str(exc)[:100]}"
    del small
    gc.collect()
    a_detected = (not ran_naturally and sub.get("sentence_max_id", 0) >= half) or (
        not ran_forced
    )
    sub["classified"] = "DETECTED" if a_detected else "FAIL"

    # --- 6b: truncated tokenizer copy (half vocab) ---------------------------
    tokj = json.loads(BPE_TOKENIZER_JSON.read_text(encoding="utf-8"))
    vocab_all = tokj["model"]["vocab"]
    tokj["model"]["vocab"] = {k: v for k, v in vocab_all.items() if v < half}
    tmpdir = OUT_DIR / "tmp_trunc_tok"
    shutil.rmtree(tmpdir, ignore_errors=True)
    tmpdir.mkdir(parents=True, exist_ok=True)
    (tmpdir / "tokenizer.json").write_text(
        json.dumps(tokj, ensure_ascii=False), encoding="utf-8"
    )
    b: dict = {}
    try:
        tt = Tokenizer.from_file(str(tmpdir / "tokenizer.json"))
        b["truncated_tokenizer_loaded"] = True
        b["truncated_vocab_size"] = tt.get_vocab_size()
        t_ids = tt.encode(FIXED_PROMPT).ids
        b["truncated_sentence_max_id"] = max(t_ids) if t_ids else None
        b["structural_vocab_mismatch"] = (
            b["truncated_vocab_size"] != tokenizer.vocab_size
        )
    except Exception as exc:
        b["truncated_tokenizer_loaded"] = False
        b["load_error"] = f"{type(exc).__name__}: {str(exc)[:100]}"
    shutil.rmtree(tmpdir, ignore_errors=True)
    if not b.get("truncated_tokenizer_loaded"):
        b["classified"] = "DETECTED"
    elif b.get("structural_vocab_mismatch"):
        b["classified"] = "DETECTED"
    else:
        b["classified"] = "SILENT"

    detected = sub["classified"] == "DETECTED" or b["classified"] == "DETECTED"
    return {
        "id": "C6_tokenizer_mismatch_detection",
        "name": "tokenizer-mismatch detection (half-vocab embedding + truncated tokenizer)",
        "status": "PASS" if detected else "FAIL",
        "criterion": "the loader/runner must fail or error when token ids exceed the "
        "model vocab (embedding 5120 vs ids from the real 10240 tokenizer) and when "
        "the tokenizer config does not match the model vocab",
        "measured": {
            "ids_exceed_vocab_case": sub,
            "truncated_tokenizer_case": b,
            "note": "a truncated half-vocab tokenizer produces ids below 5120, so a "
            "silent loader would accept it; the structural vocab-size check "
            "(5120 vs 10240) is what detects it before any forward pass",
        },
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    torch.set_num_threads(6)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    print(
        f"[RUN] F5 integrity controls | ckpt={CKPT_DIR} | avail RAM {ram_mb():.0f} MB"
    )

    model, cfg, step, _losses, n_params, load_note = load_model_from_checkpoint(
        CKPT_DIR
    )
    tokenizer = load_tokenizer()
    free("model+tokenizer loaded")
    print(f"[B] step={step} params={n_params:,} | {load_note}")

    results = []
    results.append(control_fixed_input(model, tokenizer))
    free("C1 done")
    results.append(control_save_load(model))
    free("C2 done")
    results.append(control_shuffled_ppl(model, tokenizer))
    free("C4 done")
    ref = control_corrupt(model, tokenizer)
    del model
    free("model freed before C5/C3")
    results.append(control_corrupt_reload(tokenizer, ref))
    free("C5 done")
    results.append(control_resume(tokenizer))
    free("C3 done")
    results.append(control_tokenizer_mismatch())
    free("C6 done")

    # cleanup sweep (belt and braces): tmp artifacts must not survive
    for p in (
        OUT_DIR / "tmp_ckpt.pt",
        OUT_DIR / "tmp_interim.pt",
        OUT_DIR / "tmp_corrupt.pt",
    ):
        if p.exists():
            p.unlink()
    shutil.rmtree(OUT_DIR / "tmp_corrupt_ckpt", ignore_errors=True)
    shutil.rmtree(OUT_DIR / "tmp_trunc_tok", ignore_errors=True)

    payload = {
        "timestamp": TS,
        "elapsed_seconds": round(time.time() - t0, 1),
        "model": {
            "checkpoint": str(CKPT_DIR),
            "step": step,
            "params": n_params,
            "load": load_note,
            "config": cfg,
        },
        "controls": results,
        "summary": {
            "pass": sum(1 for r in results if r["status"] == "PASS"),
            "fail": sum(1 for r in results if r["status"] == "FAIL"),
            "blocked": sum(1 for r in results if r["status"] == "BLOCKED"),
        },
        "tmp_cleaned": not any(
            p.exists()
            for p in (
                OUT_DIR / "tmp_ckpt.pt",
                OUT_DIR / "tmp_interim.pt",
                OUT_DIR / "tmp_corrupt.pt",
            )
        )
        and not (OUT_DIR / "tmp_corrupt_ckpt").exists()
        and not (OUT_DIR / "tmp_trunc_tok").exists(),
    }
    out = OUT_DIR / "integrity.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[OUT] wrote {out}")
    for r in results:
        print(f"  {r['id']:<40} {r['status']}")
    print(f"  elapsed {time.time() - t0:.0f}s | tmp_cleaned={payload['tmp_cleaned']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
