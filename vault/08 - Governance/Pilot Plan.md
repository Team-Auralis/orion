# Pilot Plan

#governance #pilot

> Closed pilot execution plan with partner emergency response organization.

## Status: BLOCKED (Awaiting Partner Agency)

## Constraints (Implemented)

- **Geofencing**: All incidents constrained to configured bounding box
- **Kill Switch**: Redis-backed instant operation suspension
- **OPA Pilot Actions**: Specific policies for pilot mode

## Entry Criteria

- [ ] Partner agency engaged
- [ ] Geofence bounding box configured
- [ ] Operator accounts provisioned
- [ ] Hardware devices registered (if applicable)
- [ ] Monitoring dashboards reviewed
- [ ] Incident response runbook approved
- [ ] DR drill passed

## Pilot Scenarios

Defined in `docs/governance/pilot-scenarios.md`:
- T1: Single building fire
- T2: Multi-vehicle accident
- T3: Flood in residential area
- T4: Network partition simulation
- T5: Kill-switch activation
- T6: Break-glass emergency
- T7: Mass casualty event
- T8: Hardware device failure

## Exit Criteria

- All scenarios executed successfully
- Zero data loss incidents
- HITL approval working end-to-end
- DR drill passed in production-like environment

## Related

- [[Phase 1.5 - Deployment Hardening]]
- [[ORION]]
- [[Deployment Runbook]]
- [[Incident Response Runbook]]
