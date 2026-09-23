# Jaeger Tracing

#observability #tracing

> Distributed trace visualization.

## Purpose

Jaeger collects OpenTelemetry traces and provides a UI for debugging request flows.

## Access

Available at `http://localhost:16686` in the [[Docker Compose]] stack.

## Use Cases

- Debug slow requests through the API
- Trace event flow: API → NATS → Worker → PostgreSQL
- Identify bottlenecks in the security pipeline
- Verify trace propagation across NATS headers

## Related

- [[OpenTelemetry]]
- [[Prometheus & Grafana]]
- [[ORION]]
