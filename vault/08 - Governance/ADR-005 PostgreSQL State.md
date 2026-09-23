# ADR-005 PostgreSQL State

#adr #database

> Why PostgreSQL is the initial application-state authority.

## Context

ORION needs ACID transactions, geospatial queries, and reliable state management for emergency incidents.

## Decision

Use **PostgreSQL 15** as the primary state store.

## Alternatives

1. **MongoDB** - Weaker consistency guarantees
2. **MySQL** - Less mature geospatial support
3. **SQLite** - No concurrent access
4. **DynamoDB** - AWS lock-in

## Consequences

- **Positive**: ACID, PostGIS for geospatial, mature ecosystem, open source
- **Negative**: Heavier than SQLite, requires ops
- **Mitigation**: Docker Compose, Alembic migrations

## Status

Proposed

## Related

- [[PostgreSQL]]
- [[PHOENIX Resilience]]
- [[ATLAS Infrastructure]]
