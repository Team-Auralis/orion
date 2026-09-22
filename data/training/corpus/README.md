# ORION training corpus

The training harnesses load data through `scripts/training/orion_corpus.py`.
This directory holds the *real* training corpus shards; a smoke fallback
(`data/training/orion_dataset.jsonl`, 9 KB / 31 rows) is used only when no
shard exists here.

## Format

Each shard is one of two plain-text encodings (UTF-8):

- **`.jsonl`** — one JSON object per line:
  - SFT rows: `{"instruction": ..., "response": ...}`
  - Pre-training rows: `{"text": ...}`
- **`.txt`** — raw pre-training text; each file is one document.

## Intake rules

- `resolve_corpus()` prefers the shards in this directory for serious runs
  (`.txt` + `.jsonl`, sorted, non-hidden files) and falls back to
  `data/training/orion_dataset.jsonl` for smoke validation.
- `scripts/training/bpe_tokenizer.py` trains the BPE tokenizer
  (`models/tokenizer_bpe/`) over every shard here.
- The training harnesses use the real BPE tokenizer only when
  `models/tokenizer_bpe/tokenizer.json` exists **and** this directory
  resolves to real shards; otherwise they keep the crc32 surrogate path.

## Adequacy gate

`bpe_tokenizer.py` (and `--gate-only`) records a `corpus-adequacy-gate` row
into `logs/training_runs.jsonl` with the real corpus token count and a
verdict: `ADEQUATE` when `actual_tokens >= 50_000_000` (the documented
floor for a meaningful 100M-parameter run), else `SMOKE_ONLY`.