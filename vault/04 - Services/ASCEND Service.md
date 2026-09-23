# ASCEND Service

#service #ai #planning

> Runtime for the [[ASCEND Planner]] long-horizon planning engine.

## Location

`services/ascend/planner.py` (75 lines)

## Pipeline

```mermaid
graph LR
    OBJ["Objective"] --> DEC["Decompose"]
    DEC --> MILE["Milestones"]
    MILE --> EVAL{"Evaluate"}
    EVAL -->|"Replan Trigger"| REPLAN["Updated Plan"]
    REPLAN --> DEC
    EVAL -->|"On Track"| DONE["Continue"]
```

## Current State

**Status: Basic Implementation**

- Multi-year objective decomposition
- Constraint identification
- Trajectory evaluation with replan triggers

## Related

- [[ASCEND Planner]]
- [[FORGE Scientific Engine]]
- [[MIRROR Digital Twin]]
- [[ORION]]
