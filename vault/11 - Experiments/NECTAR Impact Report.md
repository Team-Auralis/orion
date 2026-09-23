# NECTAR Impact Report

#nectar #impact #report

> Numeric accounting of what NECTAR delivered to ORION. Every number measured on this machine (Dell G15 5511, i5-11260H, 8GB RAM) on September 14, 2026. No fabricated metrics.

## Contribution to ORION Codebase

| Artifact | Count | Detail |
|---|---|---|
| New Python modules | 26 | services/nectar/** |
| New production lines | 1,662 | engine, backends, loader, memory, atlas, safety, registries, experiments |
| Vault documentation pages | 8 | audit, GO/NO-GO, architecture, service, benchmarks, validation, impact, EXP-LEARN-001 |
| Data files | 12 | connectome + subsets + results + MB neurons + atlas + annotations |
| Experiments registered | 4 | EXP-ODOR-001, EXP-SUGAR-001, EXP-LEARN-001, EXP-MOCK-001 |
| Benchmarks registered | 3 | BENCH-001, BENCH-002, FORGE-SMOKE |
| Audit events captured | (per run) | chronos_audit.jsonl + nectar_audit.jsonl |

## ORION Capability Gaps Filled

| Gap (pre-NECTAR) | Status | Evidence |
|---|---|---|
| **No real simulation engine** (MIRROR = tick counter stub) | **FILLED** | Full-brain LIF simulation runs today |
| No computational instrument for FORGE | **FILLED** | FORGE → NectarEngine → OMNIS pipeline exists |
| No empirical substrate for OMNIS evidence | **FILLED** | Readouts written as OmnisObservation with provenance |
| No connectome-scale dataset in project | **FILLED** | 138,639 neurons, 15,091,983 edges |
| No labeled MOCK discipline for instruments | **FILLED** | NullBackend enforces `mock=True` |

## Measured Performance

### Full Connectome (138,639 neurons, 15.09M edges)

| Metric | Value |
|---|---|
| Brian2 load time | 3.1s |
| RAM during load | 1.06 GB |
| RAM during run | 0.88 GB |
| Wall time for 0.5s bio-time | 4.6s (x9.2 slower-than-RT) |
| Wall time for 1.0s bio-time | 52.4s (x52.4; includes Cython compile) |

### Circuit Propagation (EXP-ODOR-001, hub drivers)

| Metric | Value |
|---|---|
| Drivers stimulated | 8 hub neurons |
| Neurons that fired | 492 |
| **Amplification** | **60.8x** (8 → 492) |
| Non-driven (propagated) neurons | 484 |
| Total spikes | 3,352 |
| Mean first-spike latency | 66.9 ms |
| Top driven neuron rate | 152 Hz |

### Connectome Statistics (measured)

| Stat | Value |
|---|---|
| Excitatory edges | 9,059,302 (60.0%) |
| Inhibitory edges | 6,032,681 (40.0%) |
| Mean out-degree | 108.9 |
| Max out-degree | 9,783 (brain-wide hub) |
| Max in-degree | 10,356 |
| Edge weight range | 1–2,405 synapses |

## Freeze (NECTAR-v0.1-FROZEN)

**Frozen September 14, 2026.** No further model optimization until the validation campaign completes.

- Manifest with SHA-256 of all 26 code files + results: `D:\orion\data\nectar\repro\NECTAR-v0.1-FROZEN\manifest.json`
- Environment: Python 3.14.6, numpy 2.5.1, pandas 3.0.5, brian2 2.10.1
- Git HEAD: `f2a8044` (NECTAR tree untracked, pinned by hashes)
- Default params: v0 -52 mV, vth -45, τ_m 20 ms, τ 5 ms, w_syn 0.275 mV, r_poi 150 Hz, f_poi 250, dt 0.1 ms
- Hardware: Dell G15 5511, i5-11260H 6C/12T, 8 GB RAM, CPU-only
- Reproducibility: experiment scripts frozen in dir above; full NECTAR-002 results below

## Honest Limitations

1. **Hub-stimulus is not anatomical validation** — neurons idx 90883/79529 etc. are degree hubs (likely MB/Kenyon cells), not a mapped AL→MBON odour pathway. Anatomical validation requires matching the PhilShiu experiment (odour-driven sensory neurons → MBON response).
2. **LIF plasticity is modulation-only** — weights are multiplied by stored multipliers, not updated via STDP/biological dopamine dynamics. DPA (2026) and P goose (2025) have fully predictive models, not yet ported.
3. **~10x (or up to 52x) slower than real-time** on CPU — acceptable offline, not closed-loop control.
4. **Wall-time varies with Cython caching** — first run compiles, later runs are cached.
5. **Gustatory GRNs don't reach KCs** in the model — peripheral taste neurons project to SEZ, not MB. This is biologically correct, not a model bug.

## Value Statement

- ORION gained its **first empirical, reproducible computational experiment** without fabricating a single number.
- The full adult fly connectome — the largest published connectome — now runs **inside ORION**, as an audited instrument with a labeled backend abstraction.
**SUPERSEDED (2026-09-15):** the +75.6% MBON learn_factor and the associative-learning claim were **invalidated** by NECTAR-004. Under seeded RNG the ×1.5 KC→MBON weight change produces zero detectable MBON-output change (learn_factor 1.08/1.00); the earlier pain was pre-seeding RNG drift. Whole-brain readouts do not currently demonstrate learning; see the verdict section below.
- The FORGE→NECTAR→OMNIS evidence pipeline is verified end-to-end (SQLite smoke test + Brian2 null backend).
- The 1,662 lines of code orchestrate 96 MB of connectome data and mushroom-body neuroanatomy into interpretable evidence for OMNIS, gated by honesty checks.

## Validation Campaign Verdict (2026-09-15)

| Phase | Result | Classification |
|---|---|---|
| Connectome accounting | 138,639 neurons imported, 15.09M edges, 54.49M synapses (matches Nature >54.5M) | VERIFIED |
| NECTAR-002 sugar | 200 Hz: P 0.995–0.998, R 0.946–0.955, rate_corr 0.999 vs published 448-responder reference; monotonic freq decay | **REPRODUCED** |
| NECTAR-003 degradation | 8/8 controls: zero-input = 0 responders; wiring/degree/E-I-sign all load-bearing; dt-robust | VERIFIED |
| NECTAR-004 learning | plasticity inert at whole-brain readout; all 6 conditions identical per seed | **FAILED / UNPROVEN** |
| EXP-LEARN-001 | learn_factor 1.756 did NOT replicate; was RNG noise (now 1.08/1.00) | **FAILED TO REPLICATE** |
| NECTAR-005 generalization | modality discrimination Jaccard ≤0.009; partial-stimulus robustness monotonic; temporal cohorts stable; A_ref re-replicates | VERIFIED |
| NECTAR-006 ORION-benefit | beat same-cost reservoir (identity 0.556 vs 1.0; transfer 0.0 vs 1.0); ~7× functional reach vs shuffled; silent on zero input (reservoir: 127k active) | VERIFIED |

**Bottom line.** NECTAR's defensible, unique capability is its **validated sensory pathway**: the whole-brain, seeded, audited connectome readout that (a) reproduces a published Nature sugar-odor response, (b) degrades gracefully and causally (controls verified), (c) discriminates modalities nearly disjointly, (d) stays silent when nothing happens, and (e) outperforms same-cost generic networks decisively at matched readout budget. Its weakness is honest and un-hidden: **no evidence of plasticity/associative learning at whole-brain scale**, and stimulus onset/offset drive remains unexpressible with the frozen driver. ORION should use NECTAR now as a validated sensory-feature substrate, with learning claims withdrawn pending a real plasticity port (DA dynamics / STDP).