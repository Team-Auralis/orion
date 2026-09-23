# Deployment Runbook

#operations #runbook

> Step-by-step deployment guide for [[ORION]].

## Prerequisites

- Docker + Docker Compose installed
- .env file configured (see `.env.example`)
- Minimum 8GB RAM available

## Local Development

```bash
# Clone and configure
cp .env.example .env
# Edit .env with your values

# Start all services
docker-compose up -d --build

# Verify
curl -k https://localhost:443/health
```

## Production (Kubernetes)

```bash
# Apply workloads
kubectl apply -f k8s/orion-workloads.yaml

# Verify pods
kubectl get pods -l app=orion
```

## Service Ports (Internal Only)

| Service | Port | Network |
|---|---|---|
| API | 8000 | edge |
| Dashboard | 3000 | edge |
| PostgreSQL | 5432 | core |
| Redis | 6379 | core |
| NATS | 4222 | core |
| Keycloak | 8080 | core |
| OPA | 8181 | core |
| Prometheus | 9090 | core |
| Grafana | 3001 | core |
| Jaeger | 16686 | core |

## Verification Checklist

- [ ] All containers running
- [ ] API health check passes
- [ ] Keycloak accessible
- [ ] OPA policy loaded
- [ ] NATS JetStream active
- [ ] PostgreSQL accepting connections
- [ ] Redis responding
- [ ] Grafana dashboards loading

## Related

- [[Docker Compose]]
- [[Kubernetes]]
- [[Phase 1.5 - Deployment Hardening]]
