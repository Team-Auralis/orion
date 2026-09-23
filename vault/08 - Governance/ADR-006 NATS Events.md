# ADR-006 NATS Events

#adr #messaging

> Why NATS is the asynchronous event layer.

## Context

ORION needs reliable, low-latency event delivery between services with guaranteed delivery semantics.

## Decision

Use **NATS with JetStream** as the event mesh.

## Alternatives

1. **RabbitMQ** - Heavier, more complex
2. **Kafka** - Overkill for initial scale
3. **Redis Streams** - Considered as fallback
4. **SQS** - AWS lock-in

## Consequences

- **Positive**: Lightweight, JetStream for persistence, exactly-once with dedup
- **Negative**: Smaller ecosystem than Kafka
- **Mitigation**: Redis dedup provides exactly-once semantics at application layer

## Status

Proposed

## Related

- [[NATS Event Mesh]]
- [[Worker Service]]
- [[PHOENIX Resilience]]
