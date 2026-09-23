# NECTAR Service

#nectar #service

> **NECTAR** (formerly FlyBrain) is a **specialized computational instrument** for ORION: a whole-Drosophila-brain connectome simulation subsystem. It executes connectome-faithful spiking neuron models under FORGE experiment dispatch and reports structured readouts as evidence into OMNIS.

## Mandate

- ORION remains the orchestrator. NECTAR is a labeled instrument — its outputs are **evidence for OMNIS**, never autonomous authority.
- Every action is audited via [[NECTAR Integration Architecture|safety layer]].
- No fabricated metrics. Mocks labeled `MOCK`.

## Backends

| Backend | Type | Status | Notes |
|---|---|---|---|
| Brian2 (CPU) | PRIMARY | Reference | [[GO-NOGO]]: proven at 140K neurons (Nature 2024, PhilShiu) |
| Brian2GeNN (GPU) | Elevation path | Requires torch CUDA | [[GO-NOGO]] Phase 2+ |
| NullBackend | MOCK | Tests/CI only | `output.mock == True` enforced |

## Interfaces

```python
class NectarBackend:
    def load_connectome(self, path, constraints) -> None: ...
    def stimulate(self, neurons, pattern, duration) -> None: ...
    def step(self, dt) -> None: ...
    def readout(self, groups) -> dict: ...
    def checkpoint(self, path) -> None: ...
    def health(self) -> dict: ...
```

`NectarEngine` (core/engine.py) orchestrates submit → run → evidence into OMNIS.

## Repository Layout

```
services/nectar/
  core/          backend abstraction + engine
  connectome/    loader (parquet/csv/feather), id maps, adjacency, atlas
  simulator/     brian2_backend, null_backend (MOCK)
  memory/        FlyMemory: KC/MBON/PAM/PPL indices + dopamine plasticity
  encoders/      stimulus encoding registry
  decoders/      readout decoding (firing rate per group)
  readouts/      anatomical readout groups (AL, MB, LH, OL, MOT, BON)
  experiments/   experiment registry (EXP-*)
  benchmarks/    benchmark + ablation registry (BENCH-*, EXP-*, FORGE-SMOKE)
  safety/        CHRONOS-grade audit layer
```

## Storage (D: drive)

```
D:\orion\data\nectar\
  connectome\   # v783 source data
  mb\           # mushroom-body neurons, neuron atlas, flywire annotations
  subsets\      # curated Phase-1 subsets
  results\      # raw traces + integrity hashes + fly_memory.json
  checkpoints\  # simulator state
```

## Roadmap from Open-Source Survey (Sept 2026)

Surveyed repos: `cobanov/awesome-fly`, `eonsystemspbc/fly-brain`, `lixiang1076/fly-brain`, `snedea/flybrain`, `fruitflydev/flycoinrh` (unverifiable — likely typo/crypto).

| Source | Gives us | Status |
|---|---|---|
| lixiang1076/fly-brain | `mushroom_body_neurons.json` (4,133 KC, 96 MBON, 307 PAM, 24 PPL); `dopamine_learning.py` KC→MBON plasticity; `neuron_atlas.json` stimuli | **DONE** — integrated. EXP-LEARN-001 proves associative memory (learn_factor 1.756) |
| eonsystemspbc/fly-brain | Multi-framework benchmark (Brian2, Brian2CUDA, PyTorch, NEST) | Benchmark reference; confirms Brian2 CPU path |
| snedea/flybrain | Emergent behaviors demo: food-seeking, phototaxis, startle on 139K LIF | Behavioral targets for future experiments |
| cobanov/awesome-fly | Index — FastFly (CUDA real-time), MaleCNS 166K, FlyGym embodied body, flyvis vision | Long-term roadmap |

## Related

- [[GO-NOGO Assessment]]
- [[NECTAR Integration Architecture]]
- [[NECTAR Benchmarks]]
- [[NECTAR EXP-LEARN-001]]