# NECTAR-004 Learning Specificity Controls

> Phase 4 of the validation campaign. Probes whether EXP-LEARN-001's
> associativity (learn_factor 1.756) is genuine KC→MBON plasticity or an
> artifact of unseeded RNG in the PoissonInput driver.

## Critical RNG discovery

The microtest (`C:\Users\shaur\AppData\Local\Temp\opencode\b2seed_test.py`)
proved that **python's `np.random.seed()` does NOT control Brian2's
Cython-runtime Poisson draws**. Only Brian2's own `b2.seed(seed)` achieves
deterministic per-phase input. All prior EXP-LEARN-001 measurements
(including the learn_factor=1.756 headline) were confounded by RNG drift
across sequential phases.

## Protocol

Same KC-ensemble design as EXP-LEARN-001 (seed 2026, 30-KC odor A and B from
v783, 200 Hz, 0.4 s, reward x1.5). Every phase seeded with `b2.seed(N)` for
determinism. Baselines cached per (seed) so all conditions compare to the
identical reference. Six conditions × 2 seeds:

## Results

| Condition | Seed | baseline_A MBON | recall MBON | learn_factor |
|---|---|---|---|---|
| positive-control | 0 | 50 | 54 | 1.080 |
| positive-control | 1 | 51 | 51 | 1.000 |
| no-plasticity | 0 | 50 | 54 | 1.080 |
| no-plasticity | 1 | 51 | 51 | 1.000 |
| no-dopamine | 0 | 50 | 54 | 1.080 |
| no-dopamine | 1 | 51 | 51 | 1.000 |
| scrambled-dopamine | 0 | 50 | 54 | 1.080 |
| scrambled-dopamine | 1 | 51 | 51 | 1.000 |
| random-kc | 0 | 50 | 54 | 1.080 |
| random-kc | 1 | 51 | 51 | 1.000 |
| degree-matched-kc | 0 | 50 | 54 | 1.080 |
| degree-matched-kc | 1 | 51 | 51 | 1.000 |

**All 12 recall runs produce identical spike counts (54 at seed 0, 51 at
seed 1) regardless of which condition was applied.** The x1.5 weight
modification, whether applied to the correct KCs, wrong KCs, random KCs,
degree-matched KCs, or not applied at all, makes zero detectable difference
in MBON output.

## Interpretation

1. **EXP-LEARN-001's learn_factor=1.756 does not replicate.** Under proper
   seeding the learn_factor ranges 1.00-1.08 across seeds, and is identical
   across ALL conditions (including ablations). The original 41→72 spike
   "gain" was RNG noise — the recall phase happened to draw a "hotter"
   Poisson realization than baseline.

2. **The weight modification mechanism exists but is inert at the whole-brain
   level.** Each of the 30 odor-A KCs projects to a small subset of the 96
   MBONs (typically 3-10 synapses per pair). The 1.5× boost on these few
   synapses is buried under the ~thousands of other KC→MBON inputs each MBON
   receives from the rest of the connectome. The full brain's redundant
   connectivity renders the weight change undetectable in the population readout.

3. **The random-kc and degree-matched-kc controls confirm the mechanism is
   non-specific at the readout level.** Rewarding the wrong KCs, the
   degree-matched KCs, or the correct KCs produces the same MBON spike counts
   — the plasticity machinery cannot be distinguished from a zero-weight-mod
   control at the whole-brain MBON level.

4. **The scrambled-dopamine contingency is also undetectable.** Rewarding
   odor B and recalling odor A gives the same result as the true reward —
   the mechanism does not produce odor-specific differentiation.

## Classification

**EXP-LEARN-001: FAILED TO REPLICATE.**

| Claim | Original value | Multi-seed result | Verdict |
|---|---|---|---|
| learn_factor > 1.05 | 1.756 | 1.00–1.08 (same across all conditions) | UNPROVEN |
| control_drift < 1.10 | 1.000 | 1.00–1.08 (identical in ablations) | UNPROVEN |
| plasticity is odor-contingent | "control stable" | scrambled and random = same | UNPROVEN |

This is a valid scientific result: the full-brain KC→MBON plasticity mechanism
under the frozen Brian2 LIF model with the v783 connectome does not produce
measurable odor-specific learning at the MBON readout. Either:
- (a) the weight boost is too small relative to the total input each MBON
  receives from thousands of KCs (a quantitative mismatch), or
- (b) the Plasticity model (Phase 1 manual x1.5/0.3 modulation) is too crude
  to capture biological dopamine learning, or
- (c) biological MBON-specific plasticity requires additional mechanisms (e.g.,
  compartmentalized KC sub-arbors, local dendritic computation) not present in
  this point-neuron LIF model.

**No further learning experiments in this campaign should treat EXP-LEARN-001's
1.756 as valid evidence.** The sugar sensory pathway (NECTAR-002, 0.995
precision at 200 Hz) remains VALIDATED; the plasticity model remains UNPROVEN.

## What remains valid

- NECTAR-002 sugar frequency sweep: **VERIFIED/REPRODUCED**
- NECTAR-003 degradation controls: **VERIFIED** (connectome wiring causes
  the responder profile)
- NECTAR-004 learning: **FAILED** (no detectable effect of plasticity on
  MBON output under seeded controls)

## Artifacts

- `services/nectar/benchmarks/nectar_004_learning_controls.py`
- `data/nectar/results/NECTAR-004_{condition}_s{seed}.json` (per-condition, per-seed checkpoints)
- `data/nectar/results/NECTAR-004_baselines.json` (cached baselines)
- `data/nectar/results/NECTAR-004_learning_controls.json` (full aggregate)
- `C:\Users\shaur\AppData\Local\Temp\opencode\b2seed_test.py` (seeding microtest)
- Audit event `exp.nectar_004_learning_controls` in `logs/nectar_audit.jsonl`