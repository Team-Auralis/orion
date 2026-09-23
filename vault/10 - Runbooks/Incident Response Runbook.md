# Incident Response Runbook

#operations #runbook

> How to respond to system incidents in [[ORION]].

## Severity Levels

| Level | Description | Response Time |
|---|---|---|
| **P0** | System down, no SOS processing | Immediate |
| **P1** | Degraded mode, partial outage | 15 minutes |
| **P2** | Single service failure | 1 hour |
| **P3** | Non-critical issue | Next business day |

## Common Incidents

### API Unreachable
1. Check Nginx status: `docker logs ascend-lb`
2. Check API replicas: `kubectl get pods -l app=orion-api`
3. Check circuit breaker state in Grafana
4. Restart if needed: `docker-compose restart orion-api`

### PostgreSQL Down
1. System automatically degrades to NATS-only mode (HTTP 202)
2. Check PostgreSQL logs: `docker logs postgres`
3. Run DR restore if data loss suspected: `scripts/dr_backup_restore.py`
4. Verify RTO: Should be < 2 seconds for small snapshots

### NATS Down
1. System returns HTTP 503
2. Check NATS logs: `docker logs nats`
3. Restart NATS: `docker-compose restart nats`
4. Events will replay from JetStream on reconnect

### AI Sentinel Unresponsive
1. Check Ollama status on host
2. Sentinel falls back to deterministic keyword matching
3. Restart: `docker-compose restart orion-sentinel`

## Escalation

1. Check [[Prometheus & Grafana|Grafana]] dashboards
2. Check [[Jaeger Tracing|Jaeger]] traces
3. Check [[CHRONOS Audit|CHRONOS]] audit log
4. Contact on-call engineer

## Related

- [[Disaster Recovery Runbook]]
- [[Break Glass Runbook]]
- [[PHOENIX Resilience]]
