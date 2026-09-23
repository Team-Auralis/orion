# PHOENIX Resilience

#module #resilience

> Offline-first, degraded mode, and disaster recovery capabilities.

## Purpose

PHOENIX ensures ORION continues operating even when infrastructure fails. It provides CRDT-based conflict-free synchronization, degraded mode fallbacks, and disaster recovery.

## Core Capabilities

### CRDT Event Synchronization
- **Max-State CRDT**: Status only advances forward, never regresses
- **Offline/Edge Sync**: Edge devices queue events locally, resync when connectivity returns
- **Conflict-Free**: Deterministic merge without coordination

### Degraded Modes

| Mode | Trigger | Behavior |
|---|---|---|
| **Normal** | All systems operational | Full API + DB + NATS |
| **NATS-Only** | PostgreSQL down | HTTP 202 ACCEPTED, NATS-only ingestion |
| **Total Degraded** | DB + NATS down | HTTP 503 Service Unavailable |

### Disaster Recovery

- PostgreSQL backup/restore procedures
- Live DR drill: **RTO 1.60 seconds** for 0.21 MB snapshot
- `scripts/` contain backup automation

### Deduplication
- Redis SETNX atomic deduplication
- 24-hour TTL window
- Prevents reprocessing across worker instances

### Outbox Pattern
- Transactional outbox for exactly-once NATS publishing
- Database commits and NATS publishes are atomic

## Current State

**Status: Functional**

- CRDT sync verified under network chaos simulation
- Redis dedup working (replaced in-memory LRU)
- Outbox pattern implemented (fixed NATS silent loss bug)
- DR backup/restore tested

## Related

- [[ORION]]
- [[Worker Service]]
- [[Redis]]
- [[PostgreSQL]]
- [[NATS Event Mesh]]
- [[Disaster Recovery Runbook]]
