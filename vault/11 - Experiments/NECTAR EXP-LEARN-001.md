# NECTAR EXP-LEARN-001: Associative Learning

#nectar #experiments #learning #plasticity

> Demonstrated that dopamine-modulated KC→MBON weight plasticity produces **associative memory** in a full-brain Drosophila simulation. Every metric measured empirically on this machine (Dell G15 5511, i5-11260H, 8GB RAM, Brian2 CPU). No fabricated metrics.

## Design

The mushroom body stores odor identity as a **sparse Kenyon cell ensemble**. This experiment tests whether reward-pairing (simulated PAM dopamine x1.5) strengthens a specific KC→MBON pathway while leaving an unpaired odor pathway unchanged.

**Phases (all v783 full brain, Brian2 CPU):**
1. Sensory probe — taste_sweet GRNs (23 neurons, 200 Hz). Confirmed: peripheral gustatory GRNs don't reach KCs (biologically correct — MB is olfactory).
2. Baseline A/B — two disjoint KC ensembles (30 KC each, seeded), no reward
3. Acquisition — drive KC ensemble A, apply PAM-like reward (x1.5 strength to all KC→MBON synapses of active KCs)
4. Recall A — fresh load, apply learned weights, re-drive KC ensemble A
5. Recall B — same learned weights, re-drive KC ensemble B (control)

## Measured Results

| Metric | Value |
|---|---|
| kc_enemble_A_size | 30 |
| kc_enemble_B_size | 30 |
| baseline_A mbon_spikes | 41 |
| recall_A mbon_spikes | 72 |
| **learn_factor** (recall_A / baseline_A) | **1.756** (+75.6%) |
| baseline_B mbon_spikes | 31 |
| recall_B mbon_spikes | 31 |
| **control_drift** (recall_B / baseline_B) | **1.000** (unchanged) |
| KC→MBON synapses strengthened | 2,880 |
| sensory GRNs reach KC | false (0 KC fired) |
| sensory GRNs reach MBON | weak (1 MBON, 1 spike) |

## Pass Criteria

- [x] learn_factor > 1.05 — **PASS (1.756)**
- [x] control_drift < 1.10 — **PASS (1.000)**
- [x] All measured — **CONFIRMED**

## Architecture

- `memory/flymemory.py` — `FlyMemory` class: loads `mushroom_body_neurons.json` (4,133 KC, 96 MBON, 307 PAM, 24 PPL), tracks active KC, modulates KC→MBON weights via multipliers clamped [0.01, 10.0]. Applies to Brian2 Synapses by scanning `syn.i`/`syn.j` arrays.
- `connectome/atlas.py` — `NeuronAtlas` class: maps `neuron_atlas.json` stimuli (11 named: taste_sweet, taste_bitter, walk_forward, escape, smell_danger, etc.) to Brian2 integer indices.
- `simulator/brian2_backend.py` — added `apply_memory(fly_memory)` + configurable `rate` param on `stimulate()` + `_flyid2i` mapping.
- `benchmarks/exp_learn_001.py` — this experiment.

## Data Sources

- mushroom_body_neurons.json, neuron_atlas.json — from [lixiang1076/fly-brain](https://github.com/lixiang1076/fly-brain) (MIT licensed)
- Full brain Connectome v783 parquet — PhilShiu / FlyWire FAFB

## Evidence Chain

1. EXP-LEARN-001 result → `D:\orion\data\nectar\results\EXP-LEARN-001.json`
2. Audit event → `logs/nectar_audit.jsonl` (event `exp.learn_001`)
3. OMNIS evidence: when DB runs → FORGE submit → NectarEngine → `omnis_observations` row
