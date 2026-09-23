# NATS Event Mesh

#infrastructure #messaging

> Asynchronous event bus with JetStream for guaranteed delivery.

## Purpose

NATS is the nervous system of [[ORION]]. All inter-service communication flows through NATS events.

## Features

| Feature | Description |
|---|---|
| **JetStream** | Persistent messaging with replay |
| **Consumer Groups** | Load-balanced event processing |
| **Guaranteed Delivery** | At-least-once semantics |
| **Headers** | OpenTelemetry trace propagation |

## Event Topics

| Topic | Publisher | Subscriber | Description |
|---|---|---|---|
| `incident.created` | API | Worker, Sentinel | New SOS incident |
| `incident.ai_triaged` | Sentinel | Worker | AI classification complete |
| `incident.dispatched` | Worker | API, Dashboard | Asset dispatched |
| `security.event` | Cyber emitter | Cyber SOAR | Security anomaly |

## Outbox Pattern

The [[API Service]] uses transactional outbox for exactly-once publishing:

1. Incident + outbox entry created in single PostgreSQL transaction
2. Background publisher reads unpublished outbox entries
3. Publishes to NATS
4. Marks entry as published

This prevents "NATS silent loss" - events lost when NATS is temporarily unreachable.

## Trace Propagation

OpenTelemetry trace IDs are carried in NATS headers, enabling end-to-end distributed tracing from API → Worker → Sentinel.

## Related

- [[ORION]]
- [[API Service]]
- [[Worker Service]]
- [[AI Sentinel]]
- [[PHOENIX Resilience]]
