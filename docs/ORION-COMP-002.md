# ORION-COMP-002 — held-out generalization + reasoning benchmark (v2)

_Generated 2026-09-23T12:08:09Z from `logs/training_runs.jsonl` + `logs/comp002_eval_raw.jsonl` by `scripts/report/comp002_report.py`. Regenerable; re-running overwrites this file and appends NO ledger row._

> **Honesty box:** the MEASUREMENTS below (loss, perplexity, HellaSwag accuracy) are **VERIFIED** — they were reproduced by this box from the ledger and the eval suite. The CAPABILITY claims are **UNPROVEN at this training budget**: 563,626 tokens seen of a 63,827,053-token corpus (0.9%), so the model is a bounded first pass, not a trained language model. HellaSwag accuracy is at/below the 25% random baseline — explicitly **UNPROVEN**.

## 1. Status

- Corpus gate: **ADEQUATE** (`corpus-gate-29e0bb76`) — 63,827,053 train tokens vs 50,000,000 required (0 short).
- Model: **PARTIAL_FIRST_PASS** (`comp-001-custom-100m-real-0d9808ff`) — 110,918,656 params, 563,626 tokens_seen of 63,827,053 corpus_total (0.88%). Why bounded: the 700k-token train-token budget on this CPU box (6 threads, fp32 full-batch AdamW; the run was resumed once and ended resume-verified at the budget).

## 2. Table 1 — Measured run (from the ledger + T5 eval)

| metric | value |
|---|---|
| params | 110,918,656 (110.92M) |
| train throughput | 117.6 tok/s aggregate (tokens 563,626 / 4794s, both legs) |
| ending loss | 5.8770 (loss history 9.46 → 5.88 across both legs) |
| val ppl (held-out) | 2,652.40 (T5 measured) / 2,802.1 (in-training val, ledger) |
| test ppl (held-out) | 2,578.69 (T5 measured) |
| peak RSS | 1949.3 MB (max over legs) |
| total duration | 4794s (79.9 min, both legs) |
| resume | verified (second leg resumed from checkpoint-623) |

Leg detail (both ledger rows are the same final checkpoint path):

| leg | run_id | tokens_seen | ending loss | eval_loss | ppl (ledger) | tok/s | RSS MB | dur s |
|---|---|---|---|---|---|---|---|---|
| first | `e08d7bb7` | 281,813 | 6.5626 | 7.6228 | 2044.2 | 231.8 | 1949.3 | 1357 |
| resumed | `0d9808ff` | 563,626 | 5.8770 | 7.9381 | 2802.1 | 85.8 | 1935.1 | 3437 |

Notes: val/test ppl above are T5 token-weighted measurements over the corpus val-*/test-* shards (per-shard packing, sum-nll / sum-loss-tokens). The ledger's in-training val number used the harness's mean-of-blocks packing — same order of magnitude, different aggregation; both are reported so the comparison is honest. val ppl and test ppl are close, consistent with one corpus distribution and no test-set inflation.

## 3. Table 2 — Reasoning benchmark (HellaSwag)

| item | value |
|---|---|
| benchmark | hellaswag |
| dataset | Rowan/hellaswag (validation split) |
| N (slice) | 100 |
| accuracy (top-1) | 0.2100 (21/100) |
| random baseline | 0.2500 |
| contamination hits (dropped) | 0 (0) |
| slice rule | seed=42: shuffled full-dataset order, first 100 clean items (check_leak drops+refills on hits) |
| scoring | mean log-prob of continuation tokens given context; argmax over choices |

**Honest label:** accuracy 0.2100 is at/below the random baseline 0.2500 — the model shows **no measurable reasoning capability on this slice**. The MEASUREMENT is VERIFIED (reproducible suite, raw per-item log kept); the CAPABILITY claim is **UNPROVEN** at this training budget.

## 4. Table 3 — Probe + held-out ppl context

| item | value |
|---|---|
| offline quality probe (20 items, ledger) | 0.05 (1/20 exact-match completion) |
| val held-out ppl | 2,652.40 (T5) / 2,802.1 (val-shards ledger) |
| test held-out ppl | 2,578.69 (T5, not part of training eval) |
| token context | 563,626 / 63,827,053 tokens seen (0.88%) |

## 5. Classification

| result | class | one-line reason |
|---|---|---|
| corpus-adequacy gate (ADEQUATE, 63,827,053 tokens) | **VERIFIED** | measured by the gate from the real BPE tokenizer; recorded in the ledger (`corpus-gate-29e0bb76`). |
| held-out val/test ppl measurement | **VERIFIED** | reproduced by `comp002_eval.py` from the trained checkpoint + corpus shards; per-shard raw log kept. |
| HellaSwag accuracy measurement (0.2100) | **VERIFIED** | reproducible slice (seed 42, N=100) and scoring; per-item raw log kept. |
| HellaSwag capability claim (0.2100 vs random 0.2500) | **UNPROVEN** | at/below random baseline at 0.9% of the corpus; no capability evidence at this budget. |
| training run + resume | **REPRODUCED** | two ledger legs, continuum loss trajectory, resume_verified=true, tokens_seen=563,626 recorded. |
| offline quality probe (0.05) | **VERIFIED** measurement / **UNPROVEN** capability | probe is a real 1/20 exact-match score; a 0.05 score supports no capability claim. |

## 6. Reproduce

```text
python scripts/training/train_comp001.py --model-size 100m --train-token-budget 700000 --epochs 1 --ckpt-every 200 --threads 6
python scripts/training/train_comp001.py --model-size 100m --train-token-budget 700000 --epochs 2 --resume auto --ckpt-every 300 --threads 6
python scripts/evaluation/comp001_quality.py --model models/comp001/100m-real/
python scripts/evaluation/comp002_eval.py --model models/comp001/100m-real/ --benchmark hellaswag --n 100
python scripts/report/comp002_report.py
```

## 7. Limitations

- **Bounded first pass**: 563,626 / 63,827,053 corpus tokens (0.9%) with a 700k train-token budget; status PARTIAL_FIRST_PASS is the honest scope label.
- **CPU throughput**: ~117.6 tok/s aggregate for training; the eval suite is also fp32 CPU.
- **Tokenizer**: 10,240-id byte-level BPE trained on the Wikipedia + FineWeb-Edu mix; low vocab vs a 50k-token model.
- **Random-init model**: from-scratch Qwen2-ish 110.9M-budget architecture, no pretrained knowledge.
- **Eval slice**: N=100 HellaSwag items, seed-42 slice; the slice rule is fixed and stated. Contamination check (`check_leak`) is a 13-token-ngram/full-text screen against the corpus shards.
- **Benchmark scoring**: raw-text mean log-prob of continuation tokens (no prompt normalization); standard for 4-choice scoring but a simplification.

## 8. Next highest-information experiment

Resume training with a much larger budget (e.g. 5–10M of the 63.8M corpus tokens) and re-run this suite — the HellaSwag accuracy-vs-tokens curve decides whether a capability signal exists at all.

> Alternative: the Hive experiment (multi-worker throughput on this box) is orthogonal — it measures *throughput scaling*, not *capability*; run it only after the capability question above.
