# NECTAR Scientific Decision Report

> Final classification of the NECTAR validation campaign (phases 1–6,
> executed 2026-09-14 → 2026-09-15). Every metric on this page was measured on
> the campaign machine (Dell G15 5511, i5-11260H, 8 GB RAM, CPU, Brian2 2.10.1).
> No number is estimated or tuned away.

## Classification Summary

| Claim under test | Campaign result | Verdict |
|---|---|---|
| v630/v783 connectome import integrity | roster 100% covered; 54,492,922 synapses (Nature: >54.5M); 60% excitatory | **VERIFIED** |
| Sugar pathway reproduces published response | P 0.995–0.998, R 0.946–0.955 at 200 Hz, rate_corr ≈ 0.999 vs the 448-responder reference; precision ≥0.97 across all freqs | **REPRODUCED** |
| Pathway is causally wired (not artifact) | 8/8 NECTAR-003 controls: zero-input = **0 responders**; shuffled IDs null chance-real ratio ~400×; wiring/degree/E-I-sign removal collapses recall to 0.047 vs 0.888–0.938 for connectivity-preserving manipulations | **VERIFIED** |
| Pathway generalizes across stimuli | modality responder sets effectively disjoint (Jaccard ≤ 0.009); partial 10/21 and 5/21 drives keep precision ≥0.97 with monotonic recall 0.71→0.58; early/late temporal cohorts both high-precision | **VERIFIED** |
| NECTAR adds value over generic alternatives | Identity 1.0 vs reservoir 0.556 (chance 0.333); transfer 1.0 vs 0.0; ~7× responder reach vs shuffled at equal cost; 0 responders on silence vs reservoir 127,400 | **VERIFIED** |
| Associative learning / KC→MBON plasticity | All 6 conditions × 2 seeds identical (learn_factor 1.080 / 1.000); EXP-LEARN-001's 1.756 does not replicate | **FAILED / UNPROVEN** |

## What this means for ORION

- **USE now:** the connectome-based sensory readout as a validated, audited
  feature substrate — reproducible, causally verified, discriminating, cheap
  (~11 s wall per 1 s simulated), quiet on zero input.
- **DO NOT claim yet:** learning, memory, or DA-mediated plasticity. The
  modulation port works mechanically but has no measurable whole-brain effect;
  a real plasticity model (DA dynamics / STDP w/ fast-timescale traces) must be
  ported and re-validated before "associative memory" claims resume.
- **Known instrument limits (documented, not hidden):** stimulus onset/offset
  (rate mid-run changes) unexpressible with the frozen driver
  (PoissonInput.rate is read-only in Brian2 2.10.1); multiseed whole-brain
  suites must run in fresh processes (Brian2 global registry leaks); dt=0.1 ms
  full-brain runs need ~1–2.5 GB free RAM.

## Evidence files

- Phase pages: `vault/11 - Experiments/NECTAR_*` (002–006, accounting, 004
  supersedes EXP-LEARN-001)
- Data: `data/nectar/results/NECTAR-00{2,3,4,5}*.json`, `NECTAR-005_*.json`,
  `NECTAR-006_*.json`, `NECTAR-006_benefit*.json`
- Audit: `logs/nectar_audit.jsonl` (events `exp.nectar_002_sweep`,
  `exp.nectar_003_degradation`, `exp.nectar_004_learning_controls`,
  `exp.nectar_005_generalization`, `exp.nectar_006_benefit`)
- Freeze: `data/nectar/repro/NECTAR-v0.1-FROZEN/manifest.json` (+ phase-2
  benchmark scripts with hashes)

## Residual risks

1. Single-machine, single-backend evidence: CPU-only LIF approximation; no
   second implementation (GEMM/NEURON) has cross-checked these numbers.
2. Comparison reference = Nature 2024 supplementary dataset (phased EM) — a
   different materialization than the import snapshot (v630: 127,978/2.61M
   thresholded vs imported 127,400/14.69M); qualifications recorded in
   `NECTAR_CONNECTOME_ACCOUNTING.md`.
3. A_noise (NECTAR-005) is partially confounded by the frozen Poisson weight —
   treated as a high-background probe, not a clean noise floor.
4. Live ORION Postgres (5433) remains down; OMNIS/chronos real-DB writes still
   verified only via SQLite/JSONL paths.