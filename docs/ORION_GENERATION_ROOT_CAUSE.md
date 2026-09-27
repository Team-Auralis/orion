# ORION_GENERATION_ROOT_CAUSE.md

**Date:** 2026-09-27
**Scope:** ORION 110.9M (`models/comp001/100m-real`, PARTIAL_FIRST_PASS) — why Q/A
teacher-distillation (v7/v8 LoRA adapters) drops eval loss but generation latches
onto `\nA:\nA:\nA:` and never reproduces an answer.
**Harness:** `scripts/eval/root_cause.py` — all raw outputs preserved in
`logs/gen_root_cause/*.json` (aggregate: `report_aggregate.json`).
**Honesty labels:** everything below is VERIFIED by measurement unless marked
UNPROVEN. No hidden-eval tuning was performed; the probe dataset is the same
public 30-row set used by the committed generation-probe matrix.

---

## 0. The failure being explained

Frozen v8 (14 epochs, same 687-row `teacher_curriculum_merged6.jsonl`, seed 42 —
identical split to v7) reproduces the committed matrix exactly
(`logs/gen_root_cause/repro_v8.json`):

| metric | value (v8, this investigation) | committed matrix |
|---|---|---|
| held-out same-category latch rate | **0.9375** (15/16) | latch 80–100% |
| fresh-domain latch rate | **1.0** (9/9) | latch 80–100% |
| teacher-reference matches (heldout/fresh/fluency) | **0 / 0 / 0** | 0/25 |
| EOS stop rate (80-token budget) | **0.0** (0/30) | ~0% |

"Latch" = generated text begins with `A:`/`Q:` (the format prefix) and never
leaves it.

---

## 1. Reproduction conditions (frozen, exact)

- Checkpoint: `models/comp001/100m-teacher-distill-v8` (gitignored adapter,
  frozen since training ended 2026-09-27).
- Dataset: `data/training/teacher_curriculum_merged6.jsonl` — 687 unique rows
  (SHA-256 pinned in `distill_manifest.json` of the run).
- Split: identical `pack_sequences(seed=42)` blocks; train = first 80% of the
  137 packed blocks (≈109), eval = last 20% (≈28) — reproduced in `static`
  (`label_alignment.n_blocks = 137`).
- Decoding: greedy, `max_new_tokens=80`, `eos_token_id=2`, `pad_token_id=0`
  (identical to the production `gen()` in `distill_train.py`).

VERIFIED: reproduction matches the committed numbers on all four rows of the
matrix table above.

---

## 2. Implementation checklist — was anything broken?

Every item the investigation was asked to isolate was measured; **none of the
string-and-mask mechanics is broken**. Full tables in `static.json` and the
per-zone teacher-forced files.

| check | result | artifact |
|---|---|---|
| tokenizer round-trip (10 random + 6 adversarial: emoji, empty answer, broken format, 300×z, newline soup) | **16/16 OK** | `static.json.roundtrip` |
| label alignment: `labels[i] == input_ids[i]` (HF shift ⇒ target at i is ids[i+1]) | **61,119 positions, 0 mismatches** | `static.json.label_alignment` |
| boundary loss masking (`mask_boundaries=True`) | correct — -100 lands on each packed sample's first token | same |
| BOS/EOS/pad ids | bos=1, **eos=2**, pad=0; eos wired into `generate()`; but eos almost never predicted → see §5 | `static.json.config` |
| causal masking | standard HF shift inside `Qwen2ForCausalLM`; trailing pads in blocks don't corrupt causal positions (labels -100) | static pack reproduction |
| position encoding | RoPE, `max_position_embeddings=512`, `rope_theta=10000`, **no sliding window**; all sequences ≤512 | static + config print |
| attention/KV | 11 layers, 768 hidden, 12 heads; LoRA on q/k/v/o only (901K of 110.9M params = **0.8%**) | `distill_train.py` + static |
| embedding / output head | `tie_word_embeddings=False` → **separate frozen lm_head**; embedding output std = 0.05 (see §3) | config + hidden-state probe |
| loss masking | format vs answer zones computed separately (see §4) | `teacher_forced_{base,v7,v8}.json` |
| optimizer / LR schedule | AdamW lr=3e-4, wd=0.01, **no scheduler**, grad clip 1.0 — **clip is saturated** (see §3) | `tiny_overfit.json.grad_norms` |
| gradient norms | lr=3e-4: mean 0.18–4.76, max 147; lr=3e-3: mean 175, **max 10,319** | `tiny_overfit.json` |
| activation statistics | layer-5 output std ≈ 308 (base, before any training); layer-10 max |h| ≈ 11,535; final norm rescales to std 0.54 | §3 |
| decoding config | greedy / temp 0.5, 0.9 / top-k 10, 50 / top-p 0.8, 0.95 — none produce grounded text | `decode_sweep.json` |
| curriculum formatting | Q:/A: scaffolding itself is learned well (format-zone acc 38% for v8 vs 10% base); answer content is not | `teacher_forced_v8.json` |

**VERDICT: the SFT pipeline (tokenizer, labels, mask, packing, LoRA, optimizer
plumbing) is clean.** The failure is not a string/mask/shift bug.

---

## 3. The base model is the problem: insufficient pretraining + pathological conditioning

`docs/ORION-COMP-002.md` (VERIFIED from ledger + reconciliation docs):

> `comp-001-custom-100m-real-0d9808ff` — **563,626 tokens seen of
> 63,827,053 corpus tokens (0.88% of one epoch)**; val ppl 2,802; HellaSwag
> N=100 acc 0.21 ≈ random. Status: PARTIAL_FIRST_PASS.

Hidden-state probe (base, fp32, prompt `Q: What is 12 * 9?\nA:`):

| stage | mean | std | max \|h\| |
|---|---|---|---|
| embedding output (layer 0) | 0.000 | **0.053** | 0.216 |
| layer 5 output | −20.2 | **294** | 6,192 |
| layer 10 output | −31.3 | **466** | **11,535** |
| post-final-norm | −0.04 | 0.54 | 9.0 |
| logits (answer-start) | −3.0 | 2.1 | 9.3 |

A healthy transformer keeps the residual stream O(1–10). A 0.88%-trained 100M
inherits an embedding scale of 0.05, a residual stream that grows ~6,000×, and
gradient variance so wide that **grad clip 1.0 is pervasively saturated**
(raw grads 147 at lr 3e-4; **10,319** at lr 3e-3). The frozen final RMSNorm
hides the mess from the logits (std 2.1 — that's why eval loss *looks* sane)
but cannot fix training dynamics.

Consequence: every LoRA SFT step moves hidden states a tiny amount relative to
the ~500-scale internal drift; **effective learning is ~100× slower than a
healthy setup** — see the controls in §6.

---

## 4. Distinguishing "cannot represent the target" vs "decoding is broken"

**Answer: the model cannot represent the target. Decoding is faithful.**

Teacher-forced diagnostics (full answer text in context, measure whether the
model predicts the next answer token) — 24 unique train questions + 16 probe
questions, per zone (`teacher_forced_{base,v7,v8}.json`):

| model | format-zone top-1 | **answer-zone top-1** | probe answer loss | **first answer token acc** |
|---|---|---|---|---|
| base | 0.100 | 0.078 | 6.846 | **0.0 (0/40)** |
| v7 | 0.325 | 0.107 | 6.618 | **0.0 (0/40)** |
| v8 | **0.383** | 0.102 | 6.544 | **0.0 (0/40)** |

- **Even on its own training rows**, v8 predicts the next answer token only
  ~10% of the time (10× random) and **never** (0/40) predicts the first answer
  token after `A:` — for base, v7, and v8 alike.
- At the answer-start position v8's argmax is `\n` on 8/8 sampled rows; top-5
  are generic pre-training sentence-starters (`" The"`, `" What"`, `" If"`);
  entropy 4–6 nats; EOS probability ≈ **6.4e-08**.
- The greedy output `\nA:\nA:\nA:` is simply this learned distribution decoded:
  the model learned the deterministic 3-token format cycle `\n → A → : → \n`
  (format-zone acc 38%) and nothing else.

VERIFIED: teacher-forced and free-running generation agree — generation is
rendering the model's actual distribution; it is not a sampling/decoding bug.

---

## 5. Decoding sweep + fixed-prompt comparison

Decode sweep (v8, 4 prompts × 7 configs, seed-fixed, 16 new tokens each —
`decode_sweep.json`):

| config | heldout latch | fresh latch | grounded? |
|---|---|---|---|
| greedy | yes | yes | no (loop) |
| temp 0.5 / 0.9 | no | no(0.5:yes, 0.9:no) | no — ungrounded salad |
| top-k 10 / 50 | no | no | no — ungrounded salad |
| top-p 0.8 / 0.95 | no | no | no — ungrounded salad |

Sampling "escapes" the loop only into pre-training-era salad
(`"What is a numberst, in the process of the first year…"`); **no config hits a
teacher reference**. Compare (identical prompts, greedy 12 tokens —
`compare.json`):

- **base**: word salad (`\nThe lvvv.\nThe l…`)
- **v7 / v8**: identical `\nA:\nA:\nA:` latch — training *replaced* gibberish
  with the format loop and learned nothing answer-shaped.

---

## 6. Control experiments (the architecture-memorization test)

Same production pipeline (pack → LoRA r16 q/k/v/o → AdamW → clip 1.0) on
artificially small, learnable tasks. Ran as specified: if the tiny control
fails, fix the implementation first — it did **not** reveal a hard bug; it
revealed a *learning-speed* problem.

| control | rows / steps | train answer-acc (teacher-forced) | exact generation | loss curve |
|---|---|---|---|---|
| tiny, 8 rows, lr 3e-4, 40 epochs (40 steps) | 8 / 40 | 0.0% | 0/8 | 7.06 → 6.31 (glacial) |
| tiny, 8 rows, lr 3e-4, 300 epochs (300 steps) | 8 / 300 | **34.4%** | 0/8 | 7.06 → 1.08; grads max 147 |
| tiny, 8 rows, lr 3e-3, 300 epochs (300 steps) | 8 / 300 | 12.7% | 0/8 | 7.06 → 3.3 then **diverges**; grads max 10,319 |
| synthetic language, 48 rows / 12 unseen | 60 total / ~50 steps | 0.0% | 0/12 unseen | 6.92 → 6.30 |

- The architecture **can** learn: at 300 steps the tiny model's loss collapses
  to 1.08 and its greedy outputs begin with the correct vocabulary
  (`alpha gamma → "zeta theta…"`), i.e. mid-memorization.
- But memorization of 8 trivially small rows requires >300 steps — with the
  real 687-row curriculum and a ~760-step budget, answer content never gets off
  the ground (matches the 10% teacher-forced acc in §4).
- Raising lr does not fix it — the ill-conditioned base makes larger lr
  destabilize (grad max 10,319) — the clip/scale mismatch is the binding
  constraint, not the lr value per se (UNPROVEN whether a properly scaled
  gradient pipeline on the *same* base fully fixes acquisition; the conditioning
  evidence says it won't fully, see §7).

---

## 7. HARD CONCLUSION

**Dominant cause: insufficient pretraining of the base model.**

Ranked attribution (1 = dominant):

| # | cause | evidence | weight |
|---|---|---|---|
| 1 | **Insufficient pretraining** — base at 0.88% of one epoch (563K/63.8M tokens), val ppl 2,802, HellaSwag ≈ random | ledger/documents + §3 conditioning | **DOMINANT** |
| 2 | **Objective/recipe underpowered for this base** — LoRA 0.8% of params, clip 1.0 saturated by base's gradient variance (raw grads to 10K), no scheduler, ~760-step budget | §3, §6 gradients | Major contributor |
| 3 | Data (687-row curriculum, format 9% tokens) | format learned (38%), content not — data *format* is fine; content couldn't be learned with #1/#2 | Secondary |
| 4 | Architecture capacity (110.9M/11L) | provably able to memorize (tiny 300-step control §6); not the binding constraint | Minor |
| — | Implementation bug (tokenizer/labels/mask/PE/KV/head wiring) | **excluded** — §2 all clean | **Not the cause** |
| — | Decoding broken | **excluded** — faithful rendering of the learned distribution (§4, §5) | **Not the cause** |

This is **NOT** a code bug in the SFT training loop. It is **not** a decoding
defect. The 18.7% train/eval-loss reduction of v8 is real and mostly
format-zone: the model genuinely learned the Q/A scaffolding, which is what
eval loss rewards most cheaply — and which is useless for generation.

**Exact minimum change required for the next experiment:**

1. **PRIMARY — pretrain (or swap) the base before further SFT.**
   Finish pretraining `100m-real` to a reasonable state — at minimum ~1 epoch
   over its 63.8M corpus (currently 0.88%; the prior run was cut at the
   CPU-box budget). Re-check the conditioning gate: residual-stream std should
   stay O(1–10), embedding output std should not be 0.05. Alternatively swap
   to a properly pretrained small model (e.g. a healthy 100–500M Qwen/GPT-2
   clone) and re-run the **identical** v8 recipe — the pipeline itself is
   verified clean and would immediately answer how much of the failure was pure
   base state.
2. **SECONDARY (with the current base, if retraining is out of budget):**
   - LoRA rank ≥ 64 and target all linear layers (or full fine-tune) — 901K
     params (0.8%) is too small to shift a 500-scale residual stream;
   - replace fixed clip=1.0 with a scale-aware clip (clip by *median* grad
     norm or normalize per-token) or AdamW with larger eps, since raw grads
     span 0.15→10,000;
   - add LR warmup + cosine schedule (no scheduler today) and a staircase
     budget of ≥3,000 steps for the 687-row curriculum;
   - supervise EOS explicitly (add `<eos>` after every answer — the model
     assigns 6e-08 probability to EOS today, hence 0% stops).

**If the PRIMARY fix is chosen, expected behavior:** same v8 recipe on a
properly pretrained base should at least (a) push answer-zone teacher-forced
top-1 well above 10%, and (b) start breaking the format loop on held-out
questions. The gate for declaring generation working remains the committed
30-row matrix: heldout ≥ 10/16 teacher-reference matches, fresh-domain ≥ 5/9,
≥ 1 fluency pass, EOS stop > 50%.

---

## 8. Artifacts

- `scripts/eval/root_cause.py` — full harness (subcommands: repro, static,
  teacher_forced, decode_sweep, compare, tiny_overfit, synth_control, report)
- `logs/gen_root_cause/repro_v8.json`, `static.json`,
  `teacher_forced_{base,v7,v8}.json`, `decode_sweep.json`, `compare.json`,
  `tiny_overfit.json`, `synth_control.json`, `report_aggregate.json`
- Ledger: `logs/training_runs.jsonl` (root-cause diagnostic + control entries)
- Prior matrix (same numbers, committed earlier): `data/eval/gen_probe_questions.jsonl`,
  `logs/gen_probe_{base,v6,v7,v8}.jsonl`