# ADR-002 Modular Monolith

#adr #architecture

> Why modular monolith is preferred before microservices.

## Context

ORION needs to scale from solo-developer prototype to team-developed platform. The initial architecture must balance development velocity with future scalability.

## Decision

Start with a **modular monolith** structure:
- Single deployable unit (FastAPI app)
- Internal module boundaries (clear package structure)
- Event-driven interfaces between modules
- Ready to extract to microservices when needed

## Alternatives

1. **Microservices from day 1** - Premature for solo developer
2. **Monolith without modules** - Hard to extract later
3. **Serverless** - Cold start latency unacceptable for emergency response

## Consequences

- **Positive**: Simple deployment, fast iteration, easy debugging
- **Negative**: Tight coupling risk if boundaries aren't respected
- **Mitigation**: NATS event mesh enforces async communication

## Status

Proposed

## Related

- [[System Architecture]]
- [[NATS Event Mesh]]
- [[ORION]]
