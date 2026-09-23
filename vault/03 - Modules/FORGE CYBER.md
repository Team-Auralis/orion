# FORGE CYBER

#module #security #ai

> Defensive security engine - detection, SOAR, and incident response.

## Purpose

FORGE CYBER is ORION's SOC/SIEM layer. It detects security anomalies, orchestrates automated responses, and maintains an immutable audit trail of all security events.

## Detection Engine

11 detection rules in `services/cyber/detections.py`:

| Rule | Description |
|---|---|
| **Brute Force** | Repeated auth failures from same source |
| **Impossible Travel** | Same user auth from geographically distant locations |
| **Break-Glass Anomaly** | Unusual break-glass token usage patterns |
| **Kill-Switch Tamper** | Unauthorized attempts to modify kill-switch |
| **NATS Unauthorized** | Unauthorized publisher on NATS |
| **Payload Oversize** | SOS payload exceeding size limits |
| **Asset Teleport** | Asset appearing in two distant locations simultaneously |
| **Policy Deny Burst** | Rapid OPA policy denials |
| **Session Anomaly** | Unusual session behavior |
| **Rate Limit Abuse** | Excessive API calls despite rate limiting |
| **Audit Tamper** | Attempts to modify audit logs |

## SOAR Engine

Security Orchestration, Automation and Response (`services/cyber/soar.py`):

- **Policy-gated execution** - Actions require OPA approval
- **Human approval for high-impact** - Critical actions need HITL
- **Rollback capability** - Undo automated responses
- **Audit trail** - Every SOAR action logged

## Event Schema

```python
# services/cyber/oses.py
class SecurityEvent:
    event_type: str
    severity: str
    source: str
    actor: Actor
    timestamp: datetime
    metadata: dict
    confidence: float
```

## Current State

**Status: Functional (Phase 2 Complete)**

- 25/25 unit tests green
- Event emitter wired to auth failures, break-glass, OPA denials, kill-switch
- JSONL sink when `FORGE_CYBER_EVENTS` is set

## Documentation

- `docs/cyber/architecture.md` - Component model, safety contract
- `docs/cyber/threat-model.md` - STRIDE mapping
- `docs/cyber/range-plan.md` - FORGE RANGE topology
- `docs/cyber/metrics.md` - MTTD/MTTR definitions

## Related

- [[ORION]]
- [[VEIL Security]]
- [[Break Glass Protocol]]
- [[Zero Trust Architecture]]
- [[Cyber Service]]
