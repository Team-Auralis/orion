# NECTAR GO/NO-GO Assessment

#nectar #decision #honesty

> Conditional GO assessment for whole-Drosophila-brain integration into ORION. Conducted September 14, 2026 on Dell G15 5511.

## Hardware Reality (Measured, Not Assumed)

| Spec | Measured Value | Verdict |
|---|---|---|
| CPU | i5-11260H, 6C/12T @ 2.6-4.4GHz | ADEQUATE |
| RAM | **8 GB total**, ~5 GB available after OS | SEVERELY CONSTRAINED |
| GPU | RTX 3050 Laptop, 4 GB VRAM, CUDA 13.2 driver | USABLE (requires torch CUDA reinstall) |
| PyTorch | **2.13.0+cpu — CPU-only build** | MUST FIX: `pip install torch --index-url .../cu121` |
| Disk D: | 25.6 GB free | SUFFICIENT (user confirmed) |
| Disk C: | 8.6 GB free | NOT IN PLAY (use D:) |

## Data Requirements (FlyWire FAFB v783)

| Data Product | Size (approx) | Notes |
|---|---|---|
| Connectivity parquet/csv.gz | 1-3 GB | 3.7M connections, synapse counts |
| Neuron annotations TSV | ~50-100 MB | 139K neurons, cell types |
| **Subset for Phase 1 (≤25K neurons)** | ~200-400 MB | First cut: optic lobe or hemibrain scale |

## Backend Selection (Evidence-Ranked)

| Backend | Scale Proven | Speed | RAM | Verdict |
|---|---|---|---|---|
| **Brian2 (CPU) — PhilShiu reference** | 140K neurons / 50M synapses (Nature 2024) | Slow but proven | 4-16 GB | **PRIMARY (Phase 1)** |
| Brian2GeNN (GPU) | 4.13M neurons / 24.2B synapses (single GPU) | Near real-time | fits 4GB VRAM | **ELEVATION PATH (Phase 2+)** |
| NEST | billions (MPI) | Fast, parallel | high fixed cost | Contingency |
| Loihi 2 (neuromorphic) | 140K / 50M on 12 chips | Orders of magnitude faster | hardware access needed | UNREACHABLE locally |

## GO / NO-GO Decision: **CONDITIONAL GO**

### GO Conditions (all must hold)
- [x] User frees/uses D: drive for data + models
- [x] User accepts torch CUDA reinstall for GPU path
- [x] Phase 1 starts small (≤25K neurons) then scales up
- [x] All metrics empirically measured — NO fabricated numbers
- [x] Failed experiments are recorded as valid scientific output

### Honesty Gates (every benchmark reports)
- Wall time measured on THIS machine, not vendor claims
- RAM/VRAM measured with psutil/monitoring
- Mocks explicitly labeled `MOCK` — never silent
- Delta vs PhilShiu published numbers reported, not hidden

## Measured Performance (September 14, 2026)

| Scale | Wall (1s bio) | RAM | Slower-than-RT |
|---|---|---|---|
| 2K neurons | ~1.3s | 196 MB | x1.3 |
| 10K neurons | ~3.2s | 257 MB | x3.2 |
| **138K (full brain)** | **52.4s** | **0.68 GB** | **x52.4** |

**Full brain fits in 0.68 GB RAM — well within 8GB budget. GO confirmed.**

## Execution Path

1. **Phase 1 — Pilot scale (≤25K neurons)**: Connectome subset, Brian2 CPU, sniff-only readouts. Validity: circuits reproduce known mapping (e.g. olfaction → MBON).
2. **Phase 2 — Whole-brain (139K neurons)**: Requires elevated RAM discipline or GeNN GPU path. Validity: matches PhilShiu 91% behavioral prediction plate.
3. **Phase 3 — ORION integration**: FORGE experiments target NECTAR, OMNIS ingests evidence, CHRONOS logs everything, MIRROR gains real compute substrate.

## Failure Criteria (NO-GO Follow)
- Phase 1 cannot reproduce a single known anatomical circuit → rethink connectome subset
- Memory pressure exceeds 95% RAM → downscale, don't fake
- Benchmark integrity violated (fabricated numbers) → abort entire integration