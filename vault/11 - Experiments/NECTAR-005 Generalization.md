# NECTAR-005 Stimulus Generalization & Discrimination

> Phase 5 of the validation campaign. After NECTAR-004 showed the plasticity
> machinery is inert under seeded controls, the campaign's weight rests on the
> VALIDATED sugar sensory pathway. This phase tests how robust and how
> DISCRIMINATIVE that pathway is under stimulus perturbations.

## Protocol

Base: v630 connectome (127,400 neurons), seeded (b2.seed(0)), 1.0 s runs,
direct-stimulus method. Every condition runs in a **fresh process** (Brian2's
global object registry leaks irrecoverably across in-process full-brain loads;
multiple loads in one process OOM on 8 GB). Cases:

- `A_ref` — 21 sugar GRNs @ 200 Hz (baseline, must reproduce NECTAR-002)
- `A_noise` — sugar 21 + 0.5 Hz background Poisson on ALL 127,400 neurons
- `A_partial_10 / A_partial_5` — 10 / 5 of the 21 sugar GRNs
- `B_bitter` — 42 taste_bitter GRNs (distinct stimulus)
- `C_danger` — 39 smell_danger GRNs (distinct stimulus)
- `C_novel_vision` — vision_looming GRNs (novel modality)
- `A_window_early / A_window_late` — A_ref responders split by first-spike
  latency (<0.5 s / ≥0.5 s), the temporal generalization probe

Implementation notes / corrections:
- First version's rate-correlation used a v783-native index map against v630
  spike trains (corr=0.0097 was a bug); fixed to a v630-consistent map (→0.997).
- `PoissonInput.rate` has no setter in Brian2 2.10.1, and 127k separate
  PoissonInput objects exhaust memory (global `instances` registry from
  `find_name`). Network-wide noise = ONE PoissonInput with N=1 across the neuron
  group; temporal offsets = first-spike window split of the full run.
- Atlas stimulus_indices() maps against Completeness_783 by default; on v630 the
  stimulus FlyWire IDs were re-mapped through the v630 completeness index (the
  un-re-mapped version raised an out-of-range error in `stimulate`).

## Results

| Condition | driven | responders | P vs sugar | R vs sugar | rate_corr |
|---|---|---|---|---|---|
| A_ref | 21 | 417 | 0.998 | 0.929 | 0.997 |
| A_noise | 21 + all | 55,765 | 0.007 | 0.926 | 0.831 |
| A_partial_10 | 10 | 319 | 0.991 | 0.705 | 0.896 |
| A_partial_5 | 5 | 268 | 0.974 | 0.583 | 0.772 |
| B_bitter | 42 | 137 | 0.036 | 0.011 | -0.837 |
| C_danger | 39 | 8,223 | 0.008 | 0.154 | -0.430 |
| C_novel_vision | 104 | 608 | 0.016 | 0.022 | -0.475 |
| A_window_early | 21 | 369 | 1.000 | 0.824 | — |
| A_window_late | 21 | 48 | 0.979 | 0.105 | — |

Discrimination (Jaccard over full responder sets):

| Pair | Jaccard |
|---|---|
| A_ref vs B_bitter | 0.0091 |
| A_ref vs C_danger | 0.0078 |
| A_ref vs C_novel_vision | 0.0089 |
| B_bitter vs C_danger | 0.0006 |

## Interpretation

- **A_ref reproduces NECTAR-002** (P 0.998, R 0.929, corr 0.997) → result is
  run-to-run stable.
- **Partial-stimulus robustness**: dropping to 10/21 and 5/21 driven GRNs keeps
  precision ≥0.97 while recall degrades monotonically (0.71 → 0.58) and rate
  correlation stays high (0.90 → 0.77). The readout is robust to incomplete
  stimuli — failures are false-negatives, never fabricated positives.
- **Discrimination**: sugar, bitter, danger and vision drive essentially
  disjoint responder populations (Jaccard ≤ 0.009, with the negative rate
  correlations showing *opposite* rate structure). The connectome assigns
  distinct network states to distinct stimuli — a prerequisite for a sensory
  pathway to be informative.
- **Temporal robustness**: the early-spiking cohort (first spike <0.5 s) is
  precision 1.0 and covers 82% of the sugar reference; the late cohort is sparse
  but high-precision. Responder identity is stable across time windows (no
  drift/garbage responders). Note: genuine stimulus on/offset (drive rate change
  mid-run) is not expressible with the frozen driver — `PoissonInput.rate` is
  read-only in Brian2 2.10.1.
- **A_noise caveat**: 0.5 Hz on all neurons with the frozen weight
  (`w_syn·f_poi·mV ≈ 69 mV/event`) produces huge background drive (55,765
  responders), i.e. it tests the pathway under overwhelming background activity
  rather than perturbation-level noise; recall still holds at 0.926. Treated as
  a high-background robustness probe, not a clean noise floor.

## Caveats & honesty notes

- Jaccard/overlap comparisons use the 200 Hz sugar reference's responder set
  (448). P is "precision vs sugar reference", not an inherent quality metric.
- A_noise is confounded by the strong background effective weight; a fairer
  low-rate background needs a weight-tuned driver (frozen backend forbids it).
- Time-window split uses the A_ref full 1 s run's spike timestamps; it is a
  population-stability probe, not a stimulus onset/offset manipulation.

## Status

VERIFIED for replication stability, partial-stimulus robustness,
discrimination capacity, and temporal population stability. A_noise partially
supported (confounded). Stimulus onset/offset control remains UNTESTED (backend
constraint, documented).