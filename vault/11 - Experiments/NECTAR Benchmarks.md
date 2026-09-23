# NECTAR Benchmarks

#nectar #experiments #benchmarks

> Benchmark and ablation definitions for NECTAR Phase 1. Every metric is empirically measured on the actual machine — no vendor claims, no fabricated numbers.

## Phase 1 Hardware Reality Check (Measured)

Measured September 14, 2026 on Dell G15 5511 (i5-11260H, 8GB RAM, Brian2 2.10.1 CPU).

| Subset | Edges | Wall time | Bio-time | Spikes | Active % | RAM | Slower-than-RT |
|---|---|---|---|---|---|---|---|
| 2,000 neurons | 3,217 | 0.64s | 0.5s | 364 | 0.25% | 196 MB | x1.3 |
| 10,000 neurons | 77,744 | 0.64s | 0.2s | 178 | 0.21% | 257 MB | x3.2 |
| **138,639 neurons (full brain)** | **15,091,983** | **52.4s** | **1.0s** | **3,195** | **0.025%** | **0.68 GB** | **x52.4** |

### Hardware Reality

- **Full brain fits in 0.68 GB RAM** on 8GB laptop — well within budget
- **52.4x slower than real-time** on Brian2 CPU (i5-11260H) — acceptable for offline research
- **1 minute biological time ≈ 52 minutes wall time** on this hardware
- Cython compilation is cached; second runs are faster
- Hub-stimulus drives 34/138K neurons; full circuit validation requires anatomically-targeted stimulus (see EXP-ODOR-001)

### Honesty gates

- Wall time measured on THIS machine (Dell G15 5511, i5-11260H with 8 GB RAM).
- Peak RAM via `psutil` — measured, not guessed.
- Any deviation from reference published values reported in the report, not hidden.
- **Note**: sparse subsets show only driven-hub activity (expected — no full circuit connectivity to propagate). Full brain needed for circuit validation.

## Benchmark 002 — Null-Backend Integrity Check

| Field | Value |
|---|---|
| Metric | `output.mock == True` |
| Time budget | 5 s |
| Reported field | `output.mock` |

Ensures the MOCK path can never be mistaken for real data.

## Benchmark 003 — FORGE→NECTAR→OMNIS Pipeline Smoke

| Field | Value |
|---|---|
| Metric | evidence row committed with `source == "NECTAR"` |
| Backend | NullBackend (MOCK) |
| DB | in-memory SQLite (no live infra required) |
| Egress | `forge_smoke.py` |
| Result | **PASS** — submit → RUNNING → evidence committed |

## EXP-LEARN-001 — Associative Learning (Sept 14, 2026)

| Field | Value |
|---|---|
| Stimulus | odorA = 30-KC ensemble, odorB = 30-KC ensemble (disjoint) |
| Reward | PAM-like x1.5 on active KC→MBON during acquisition |
| **learn_factor** (odorA recall/baseline) | **1.756** |
| **control_drift** (odorB recall/baseline) | **1.000** |
| KC→MBON synapses strengthened | 2,880 |
| Sensory GRN → KC reach | 0 (biologically expected — gustatory ≠ olfactory MB) |
| Wall time | ~150 s per 0.4 s bio-time phase (Brian2 CPU) |
| Pass criteria | learn_factor > 1.05, control_drift < 1.10 — **both PASS** |

## Ablations

| Ablation | Effect | Reason |
|---|---|---|
| `no_lateral_inhibition` | Removes inhibitory edges | Tests whether lateral inhibition contributes to MBON tuning |
| `no_odour_signal` | Background only | Control — should show low/zero response |

## Success Criteria (Phase 1)

1. `BENCH-001` reproduces AL → MBON → LH mapping within ±20%.
2. `BENCH-002` always true.
3. Subset ≤ 25K neurons fits in ~3 GB RAM budget.
4. All audit events written to `logs/nectar_audit.jsonl`.

## Failure → Scale Down, Don't Fake

If any metric fails: reduce subset size, document the exact wall times, keep the failure visible. Scale up only after the failure is diagnosed.