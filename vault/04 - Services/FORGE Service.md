# FORGE Service

#service #ai #research

> Runtime for the [[FORGE Scientific Engine]].

## Location

`services/forge/engine.py` (71 lines)

## Pipeline

```mermaid
graph TD
    OMNIS["OMNIS State"] --> HYP["Hypothesis"]
    HYP --> EXP["Experiment"]
    EXP --> RES["Result"]
    RES --> EVAL{"Evaluation\nScore >= 0.8?"}
    EVAL -->|Yes| UPDATE["Knowledge Update"]
    UPDATE --> OMNIS
    EVAL -->|No| REJ["Reject"]
```

## Current State

**Status: Basic Implementation**

- Hypothesis generation from OMNIS state
- Experiment design
- Result evaluation
- OMNIS knowledge update (threshold: 0.8)

## Related

- [[FORGE Scientific Engine]]
- [[MIRROR Digital Twin]]
- [[OMNIS World Model]]
- [[ORION]]
