# PostgreSQL

#infrastructure #database

> Primary application state store.

## Purpose

PostgreSQL is the source of truth for all persistent state in [[ORION]].

## Schema Entities

| Entity | Purpose |
|---|---|
| **incidents** | Emergency SOS incidents |
| **assets** | Responder assets (703+ seeded) |
| **audit_log** | [[CHRONOS Audit\|CHRONOS]] immutable audit |
| **outbox** | Transactional outbox for NATS |

## Key Features

- **ACID transactions** for outbox pattern
- **Haversine queries** for geospatial dispatch
- **Optimistic Concurrency Control** for asset state machine
- **Alembic migrations** for schema management

## DR Procedures

- Backup/restore scripts in `scripts/`
- Live DR drill: **RTO 1.60 seconds** for 0.21 MB snapshot
- `dr_backup_restore.py` automation

## Degraded Mode

When PostgreSQL is down:
- API falls back to NATS-only ingestion (HTTP 202)
- Worker cannot project events
- System remains partially operational

## Related

- [[ORION]]
- [[PHOENIX Resilience]]
- [[ATLAS Infrastructure]]
- [[Disaster Recovery Runbook]]
