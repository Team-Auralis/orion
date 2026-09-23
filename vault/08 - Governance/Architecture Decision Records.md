# Architecture Decision Records

#governance #adr

> Key architectural decisions documented in `decisions/` directory.

## ADR List

| ADR | Decision | Status |
|---|---|---|
| [[ADR-002 Modular Monolith]] | Modular monolith before microservices | Proposed |
| [[ADR-003 Keycloak Identity]] | Keycloak as initial identity authority | Proposed |
| [[ADR-004 OPA Policy]] | OPA as independent authorization layer | Proposed |
| [[ADR-005 PostgreSQL State]] | PostgreSQL as initial state authority | Proposed |
| [[ADR-006 NATS Events]] | NATS/Redis Streams as async event layer | Proposed |
| [[ADR-007 Idempotency]] | Idempotency at API and event boundaries | Proposed |

## Template

Each ADR follows:
- **Context**: Why the decision was needed
- **Decision**: What was decided
- **Alternatives**: What was considered
- **Consequences**: What follows from the decision
- **Status**: Proposed / Accepted / Superseded

## Related

- [[ORION]]
- [[System Architecture]]
