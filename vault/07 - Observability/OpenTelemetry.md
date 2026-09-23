# OpenTelemetry

#observability #tracing

> Distributed tracing instrumentation across all services.

## Purpose

OpenTelemetry provides end-to-end request tracing through the entire ORION stack.

## Trace Propagation

Traces are propagated through:
1. **HTTP headers** - API ↔ Client
2. **NATS headers** - API → Worker → Sentinel
3. **Database spans** - PostgreSQL queries

## Instrumentation

| Service | Instrumentation |
|---|---|
| API | FastAPI middleware + httpx client |
| Worker | NATS subscriber + PostgreSQL spans |
| Sentinel | NATS subscriber + Ollama spans |
| AEGIS | NATS publisher spans |

## Backend

[[Jaeger Tracing|Jaeger]] collects and visualizes traces.

## Related

- [[Jaeger Tracing]]
- [[Prometheus & Grafana]]
- [[ORION]]
