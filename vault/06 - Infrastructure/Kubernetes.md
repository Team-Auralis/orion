# Kubernetes

#infrastructure #devops

> Production container orchestration.

## Location

`k8s/orion-workloads.yaml` (100 lines)

## Workloads

| Deployment | Replicas | Resources | Purpose |
|---|---|---|---|
| **orion-api** | 3 | Default | FastAPI application |
| **orion-worker** | 5 | Default | CRDT sync (CPU-intensive) |
| **orion-sentinel** | 2 | 2 CPU / 4Gi RAM | AI inference |

## Service

Exposes orion-api via LoadBalancer on port 80.

## Scaling Notes

- Workers have highest replica count (5) due to event processing load
- Sentinel needs dedicated CPU/RAM for LLM inference
- API is stateless, horizontally scalable

## Related

- [[Docker Compose]]
- [[System Architecture]]
- [[ATLAS Infrastructure]]
