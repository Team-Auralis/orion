# ORION-COMP-001 — Capability per GB benchmark, v1 (measurement scaffold)

_Generated 2026-09-23T08:03:01Z from `logs/training_runs.jsonl` by `scripts/report/comp001_report.py`. Regenerable; re-running overwrites this file and appends NO ledger row._

> **Verdict: NOT READY / SCAFFOLD** — every arm has probe score 0.0 (a real, measured 0/20), so every capability-per-GB number in this edition is 0. This report is a **measurement methodology + honest baseline**, not a capability claim.

## 1. Purpose & method

Capability per gigabyte is defined as the quality probe score divided by the estimated loaded-RAM footprint (in GB):

```text
cap_per_gb = probe_score / (est_load_ram_mb / 1024)
```

- `probe_score` = completion accuracy (0–1) from `scripts/evaluation/comp001_quality.py` (20 fixed items, exact-match, greedy decoding).
- `est_load_ram_mb` = 1.25 × checkpoint bytes (fp16 file → resident fp32-ish load, +25 %), matching the load-overhead factor used by the GGUF matrix and the BitNet arm.
- A higher number means more measured capability per unit of memory. A 0 probe score is a real measurement and is reported as-is: **0.0 (measured)**.

> `ponytail:` probe_score = 0 for all arms today, so cap_per_gb is 0 everywhere — v1 is a *measurement scaffold*, not a benchmark. v2 (real corpus + real training + bitnet.cpp) is where the numbers become nonzero and comparable.

## 2. Table 1 — Measured runs (from the ledger)

| run | params | peak RSS MB | train tok/s | inference tok/s | eval loss / ppl | probe | cap_per_gb | status |
|---|---|---|---|---|---|---|---|---|
| comp001-10m | 9.15M | 814.7 | 1130.2 |  | 6.81 | n/a | n/a | COMPLETED |
| comp001-100m | 106.10M | 1792.1 | 167.4 | 18.8 | 1819.77 | 0.0 (measured) | 0.000000 | SMOKE_RUN |

Notes: `eval loss / ppl` — comp001-100m row carries ledger `perplexity` 1819.77; comp001-10m has no probe run and no perplexity field, so its cell shows eval loss only. Both runs trained on the 2098-token smoke corpus (see §5).

## 3. Table 2 — Quantized exports (recorded by comp001-gguf-matrix)

| variant | MB (ledger) | ratio vs safetensors (424.4 MB) | probe | state |
|---|---|---|---|---|
| f16 | 212.34 | 0.500 | 0.000 | exported |
| q8_0 | 112.90 | 0.266 | 0.000 | exported |
| q4_0 | 59.86 | 0.141 | 0.000 | exported |
| Q4_K_M | blocked | Q4_K_M/lower-bit requires llama.cpp 'quantize' binary (k-qua | not_measured_requires_llama.cpp | blocked_requires_llama_cpp |

Q4_K_M is **blocked**: it requires llama.cpp's `quantize` binary (k-quant path), which is not installed; the GGUF python package cannot dequantize K-quants. No installs were made. Unblock by putting llama-quantize on PATH and re-running export_gguf_matrix.py.

## 4. Table 3 — Reference comparison (BitNet b1.58-2B-4T est. vs COMP-001)

Output of `python scripts/reference/bitnet_vs_comp001.py` (embedded verbatim):

```text
=========================================================================================================================================================
ORION-COMP-001 comparison scaffold (T7): custom COMP-001 arms vs BitNet 2.4B reference arm
=========================================================================================================================================================
model            params  weights_file_mb                  est_load_ram_mb  est_tok_per_s            quality_probe_score         status       
---------------------------------------------------------------------------------------------------------------------------------------------------------
comp001-10m      9.2M    34.92                            43.7             109.3-2185.2 (ESTIMATE)  not_recorded                COMPLETED    
comp001-100m     106.1M  404.77                           506.0            9.4-188.5 (ESTIMATE)     0.0                         SMOKE_RUN    
bitnet-2b4t-est  2.4B    400 (ESTIMATE; no file on disk)  1075 (ESTIMATE)  0.4-8.3 (ESTIMATE)       NOT_MEASURED_NEEDS_RUNTIME  NEEDS_RUNTIME
---------------------------------------------------------------------------------------------------------------------------------------------------------
COMP-001 params/weights are REAL (ledger + model.safetensors on disk).
BitNet row is ESTIMATE (model not downloaded; bitnet.cpp not installed).
est_tok_per_s heuristic cited from memory: 1-20 tok/s per 1B params on CPU.

[LEDGER] bitnet-vs-comp001 already recorded (1 row(s)); skipping
```

Reference-arm readiness (`bitnet-2b4t-readiness`, ledger): est resident 1075.2 MB (range [922, 1229] MB), headroom 303.9 MB, verdict **NEEDS_RUNTIME** — install_blocked_by: missing bitnet.cpp binaries (checked bitnet, bitnet.exe, llama-b1.58-run, llama-b1.58-run.exe on PATH + third_party).

## 5. Corpus-adequacy gate & honesty box

The corpus-adequacy gate (`corpus-adequacy-gate`) measured **2,098 tokens** vs **50,000,000 required** for a 100M training run (49,997,902 tokens short) → verdict **SMOKE_ONLY**.

What this means: nothing trained on this corpus can claim capability. 2098 tokens is a sentence or two of smoke data; the models above (loss 7.40→5.38 at 9.15M params, 106.1M at SMOKE_RUN) learned *format noise*, not language. **This report therefore explicitly states NOT READY / SCAFFOLD.** The rows in Tables 1–3 are measured baselines that become meaningful only after v2 replaces the corpus and re-runs the pipeline.

## 6. How to reproduce

The five runs that produced every row above (same order as the ledger), then this report:

```text
python scripts/training/bpe_tokenizer.py --vocab-size 1471
python scripts/training/train_comp001.py --model-size 10m --epochs 10
python scripts/training/train_comp001.py --model-size 100m --epochs 15
python scripts/training/export_gguf_matrix.py --quants f16,q8_0,q4_0,Q4_K_M --smoke-10m
python scripts/reference/bitnet_vs_comp001.py
python scripts/evaluation/comp001_quality.py --model models/comp001/100m/
python scripts/report/comp001_report.py
```

Ledger: `logs/training_runs.jsonl` (experiments `corpus-adequacy-gate`, `comp-001-10m`, `comp-001-custom-100m`, `comp001-gguf-matrix`, `bitnet-2b4t-readiness`, `bitnet-vs-comp001`).

## 7. Next steps for v2

1. **Real corpus** — ≥50 M tokens in `data/training/corpus/` (gate must return ADEQUATE).
2. **Re-train** — 10m → 100m dense with epoch/step counts that now pass the gate (100m will no longer be SMOKE_RUN).
3. **BitNet runtime** — install bitnet.cpp and pull `microsoft/BitNet-b1.58-2B-4T` i2_s GGUF; confirm the est 1075 MB resident on this box.
4. **Re-measure** — re-run the probe + tok/s on every arm (fp32, f16, q8, q4, BitNet).
5. **Re-generate** — `python scripts/report/comp001_report.py`; nonzero probe scores turn this scaffold into a real capability-per-GB table.
