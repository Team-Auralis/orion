# Observability Runbook

#operations #runbook

> How to monitor and debug [[ORION]] systems.

## Dashboards

| Dashboard | URL | Purpose |
|---|---|---|
| Grafana | http://localhost:3001 | Metrics visualization |
| Prometheus | http://localhost:9090 | Raw metrics |
| Jaeger | http://localhost:16686 | Distributed traces |

## Key Metrics to Watch

### API Health
- `api_request_duration_seconds` - Request latency
- `api_requests_total` - Request rate
- `api_errors_total` - Error rate

### Worker Health
- `worker_event_latency_seconds` - Processing time
- `worker_duplicates_total` - Duplicate detection
- `worker_successes_total` - Throughput

### Circuit Breakers
- `circuit_breaker_state` - 0=closed, 1=open
- Watch for prolonged open states

### NATS
- Check JetStream consumer lag
- Monitor message throughput

## Alerting Rules

| Alert | Condition | Severity |
|---|---|---|
| High Latency | p99 > 2s | P2 |
| Error Spike | 5xx rate > 5% | P1 |
| Circuit Open | > 5 minutes | P1 |
| Worker Lag | Consumer lag > 1000 | P2 |

## Tracing

Use Jaeger to:
1. Find slow requests
2. Trace event flow across services
3. Identify bottlenecks
4. Debug NATS propagation

## Related

- [[Prometheus & Grafana]]
- [[OpenTelemetry]]
- [[Jaeger Tracing]]
