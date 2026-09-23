# NECTAR Service

NECTAR is a Drosophila connectome simulation instrument integrated into ORION.
It runs the full 138,639-neuron adult fly brain (Brian2 CPU), validates against
published Nature 2024 results, and forms associative memories through
dopamine-modulated mushroom-body plasticity.

## Setup

```bash
cd services/nectar
pip install -r requirements.txt
```

## Structure

```
core/          backend abstraction + engine (FORGE -> NECTAR -> OMNIS)
connectome/    loader (parquet/csv/feather), id maps, adjacency, neuron atlas
simulator/     brian2_backend (PRIMARY), null_backend (MOCK)
memory/        FlyMemory: KC/MBON/PAM/PPL indices + dopamine plasticity
encoders/      stimulus encoding registry
decoders/      readout decoding
readouts/      anatomical readout groups (AL, MB, LH, OL, MOT, BON)
experiments/   experiment registry (EXP-*)
benchmarks/    benchmark + ablation registry + experiments
safety/        CHRONOS-grade audit layer
```

## Running Smoke Test (no Brian2 required)

```python
from simulator.null_backend import NullBackend
from core.engine import NectarEngine

backend = NullBackend()
backend.load_connectome("dummy", {})
readout = backend.readout(["antennal_lobe"])
assert readout["mock"] is True  # never accidentally real
```

## Production Run (Brian2 CPU)

Ensure Brian2 is installed. NECTAR picks up `Brian2Backend` automatically.

Connectome data must be placed in `D:\orion\data\nectar\connectome\` (see architecture docs).

## Experiments

```bash
# Odor propagation (hub drivers)
python benchmarks/exp_odor_001.py 0.5 8

# Sugar validation vs Nature 2024 reference (v630)
python benchmarks/exp_sugar_001.py 3

# Associative learning (odor A + reward, odor B control)
python benchmarks/exp_learn_001.py 1

# FORGE -> NECTAR -> OMNIS pipeline smoke (no DB / no simulator required)
python benchmarks/forge_smoke.py
```
