# NECTAR Integration Architecture

#architecture #nectar #integration

> How the Drosophila whole-brain simulation plugs into ORION as a specialized computational instrument. ORION remains orchestrator; fly brain is a measured, labeled subsystem — never conflated with ACI capability.

## Layer Model

```mermaid
graph TD
    subgraph ORION_CORE["ORION Core"]
        API["apps/api (FastAPI)"]
        FORGE["services/forge<br/>Hypothesis → Experiment"]
        OMNIS["services/omnis<br/>World Model (DB)"]
        CHRONOS["CHRONOS Audit Log"]
        NEXUS["services/nexus<br/>Agent Fabric"]
        MIRROR["services/mirror<br/>Digital Twin (stub)"]
    end

    subgraph NECTAR["NECTAR SUBSYSTEM"]
        FB_API["services/nectar/api<br/>REST + NATS"]
        FB_CORE["services/nectar/core<br/>Backend Abstraction"]
        FB_SIM["Simulators<br/>Brian2 (CPU) → GeNN (GPU)"]
        FB_CONN["Connectome Store<br/>Parquet/CSV on D:"]
        FB_EXP["Experiments + Benchmarks"]
        FB_OBS["Observability<br/>metrics, traces, audit"]
    end

    API -->|POST /v1/NECTAR/experiments| FB_API
    FORGE -->|experiment dispatch| FB_API
    FB_API --> FB_CORE
    FB_CORE -->|load/step/stimulate| FB_SIM
    FB_SIM -->|read connectivity| FB_CONN
    FB_EXP --> FB_SIM
    FB_API -->|results → evidence| OMNIS
    FB_API -->|every action logged| CHRONOS
    NEXUS -->|sensor/plugin registration| FB_API
    MIRROR -->|future: real substrate| FB_EXP
```

## Data Flow

```mermaid
sequenceDiagram
    participant F as FORGE
    participant A as NECTAR API
    participant C as Core
    participant S as Simulator (Brian2/GeNN)
    participant O as OMNIS
    participant L as CHRONOS

    F->>A: POST experiment (stimulus spec)
    A->>L: audit log (experiment.requested)
    A->>C: resolve backend + connectome
    C->>S: load_connectome(subset)
    S->>S: warm-up / initialize
    C->>S: stimulate(protocol)
    S->>C: activity traces (spikes, rates)
    C->>A: structured readout
    A->>O: evidence ingestion (entities/observations)
    A->>L: audit log (experiment.completed)
    A->>F: result payload + integrity hash
```

## Backend Abstraction

```python
class NectarBackend:
    """Any simulator must implement this contract."""
    name: str
    def load_connectome(self, path, constraints) -> None: ...
    def stimulate(self, neurons, pattern, duration) -> None: ...
    def step(self, dt) -> None: ...
    def readout(self, groups) -> dict: ...
    def checkpoint(self, path) -> None: ...
    def health(self) -> dict: ...
```

## Constraints (Safety-First)

1. NECTAR output is **evidence for OMNIS**, not autonomous action authority.
2. Every experiment has a **lifecycle trace** in CHRONOS — audit, not trust.
3. Readouts are **labeled by neuron group** — no "brain says" amalgamation.
4. All mocks labeled `MOCK` in output and telemetry.

## Storage Layout (D: drive)

```
D:\orion\data\\nectar\
  connectome\         # downloaded, versioned (v783)
  subsets\            # curated Phase-1 subsets
  results\            # raw traces + integrity hashes
  checkpoints\        # simulator state snapshots
```

## Sizing (Phase 1 — ≤25K neurons)

| Item | Budget |
|---|---|
| Connectome subset | 200-400 MB |
| Working RAM (Brian2) | ~2-3 GB |
| Runtime | minutes per 1s bio-time |
| GPU | not required Phase 1 (CPU proven) |