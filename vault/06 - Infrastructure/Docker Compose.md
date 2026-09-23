# Docker Compose

#infrastructure #devops

> Container orchestration for local development and testing.

## Location

`docker-compose.yml` (234 lines)

## Services (14+)

| Service | Image | Network | Purpose |
|---|---|---|---|
| **redis** | redis:7 | core | Cache, dedup, circuit breakers |
| **postgres** | postgres:15 | core | Application state |
| **keycloak** | keycloak:23.0 | core | Identity provider |
| **opa** | openpolicyagent/opa | core | Policy engine |
| **nats** | nats:latest | core | Event mesh |
| **ascend-lb** | nginx | edge | L7 load balancer + TLS |
| **orion-api** | custom | edge+core | FastAPI application |
| **orion-worker** | custom | core | CRDT sync worker |
| **orion-sentinel** | custom | core | AI triage |
| **orion-aegis** | custom | core | Hardware gateway |
| **orion-dashboard** | custom | edge | Next.js operator UI |
| **prometheus** | prom/prometheus | core | Metrics |
| **grafana** | grafana/grafana | core | Dashboards |
| **jaeger** | jaegertracing/all-in-one | core | Distributed tracing |

## Networks

| Network | Services | Purpose |
|---|---|---|
| **edge** | nginx, api, dashboard, orbital-view | Public-facing |
| **core** | worker, sentinel, aegis, postgres, redis, nats, keycloak, opa | Internal |

## Usage

```bash
docker-compose up -d --build
```

Everything accessible through https://localhost:443 (Nginx). Internal ports locked down.

## Related

- [[System Architecture]]
- [[Kubernetes]]
- [[Tech Stack]]
