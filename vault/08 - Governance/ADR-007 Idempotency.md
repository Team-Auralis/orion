# ADR-007 Idempotency

#adr #reliability

> Why idempotency is required at both API and event-consumer boundaries.

## Context

Network partitions, retries, and duplicate messages are inevitable. The system must handle them safely.

## Decision

Idempotency at two layers:
1. **API layer**: Idempotency keys for POST endpoints
2. **Event layer**: Redis SETNX dedup with 24h TTL

## Alternatives

1. **Idempotency only at API** - Events still duplicated
2. **Idempotency only at events** - API retries cause duplicates
3. **Database unique constraints** - Doesn't cover all cases

## Consequences

- **Positive**: Exactly-once processing, safe retries, crash recovery
- **Negative**: Additional Redis dependency, slight latency
- **Mitigation**: Redis is already used for circuit breakers

## Status

Proposed

## Related

- [[PHOENIX Resilience]]
- [[Worker Service]]
- [[Redis]]
