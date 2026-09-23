# Prometheus & Grafana

#observability #monitoring

> Metrics collection and visualization.

## Prometheus

Scrapes metrics from all ORION services.

### Key Metrics

| Metric | Service | Description |
|---|---|---|
| `worker_event_latency_seconds` | Worker | Event processing time |
| `worker_duplicates_total` | Worker | Duplicate events skipped |
| `worker_successes_total` | Worker | Successfully processed events |
| `api_request_duration_seconds` | API | Request latency |
| `circuit_breaker_state` | API | OPA/Keycloak breaker status |

## Grafana

Pre-configured dashboards for:
- Worker performance (latency, throughput)
- API request rates and error rates
- Circuit breaker state
- NATS message flow

## Related

- [[OpenTelemetry]]
- [[Jaeger Tracing]]
- [[ORION]]
