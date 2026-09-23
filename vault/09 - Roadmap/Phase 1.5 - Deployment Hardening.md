# Phase 1.5 - Deployment Hardening

#roadmap #phase-1.5 #in-progress

> Deployment Hardening Gate. Technically Validated Prototype → Production Ready.

## Status: IN PROGRESS

## Objectives

### 1. Operational Controls (HITL) - CLEARED
- [x] Operator approval workflows for dispatch
- [x] AI classify → recommend → explain paradigm
- [x] OPA policy recheck before physical dispatch
- [x] Asset state machine with OCC
- [x] HITL safety verification (3/3 tests passed)
- [ ] End-to-end live OPA integration (pending)

### 2. Observability & SRE - CLEARED
- [x] Prometheus + Grafana deployed
- [x] OpenTelemetry distributed tracing
- [ ] Measurable SLOs defined

### 3. Reliability & Recovery - CLEARED (Test) / PENDING (Scale)
- [x] CRDT merge verified under load
- [x] Transactional outbox (NATS silent loss fixed)
- [x] Redis dedup (replaced in-memory LRU)
- [x] DR backup/restore (RTO: 1.60s)
- [ ] Production-scale DR evidence

### 4. Security & Privacy - CURRENT FOCUS
- [x] Rate limiting (SlowAPI)
- [x] PII masking (SSN, phone, email)
- [x] Secret stripping from defaults
- [ ] Production secret manager
- [ ] Third-party penetration test

### 5. Hardware Integration - CLEARED
- [x] AEGIS hardware gateway
- [x] SRE runbooks

### 6. Closed Pilot - BLOCKED
- [ ] Controlled pilot with partner agency
- [x] Geofence constraints finalized
- [x] Kill switch implemented
- [ ] Partner agency engaged

## Related

- [[Phase 1 - MVP Complete]]
- [[Phase 2 - FORGE CYBER]]
- [[Pilot Plan]]
- [[Deployment Runbook]]
