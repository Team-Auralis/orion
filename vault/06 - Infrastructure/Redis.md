# Redis

#infrastructure #cache

> Distributed cache for circuit breakers, deduplication, and kill-switch.

## Use Cases

| Use Case | Mechanism | TTL |
|---|---|---|
| **Event Deduplication** | SETNX atomic ops | 24 hours |
| **Circuit Breaker (OPA)** | Counter + timestamp | 30s cooldown |
| **Circuit Breaker (Keycloak)** | Counter + timestamp | 30s cooldown |
| **Kill Switch** | Key presence check | Manual |
| **Pilot Geofence** | Config storage | Persistent |

## Deduplication Flow

```python
# Atomic SETNX - returns True if key was set
is_new = redis.setnx(f"dedup:{event_id}", 1, ex=86400)
if is_new:
    process_event(event)
else:
    skip_duplicate(event)
```

## Circuit Breaker Pattern

```python
failures = redis.incr(f"cb:{service}:failures")
if failures >= 5:
    redis.setex(f"cb:{service}:open", 30, 1)
    # Fail fast for 30 seconds
```

## Security

- Redis requirepass configured
- Network segmentation: unreachable from edge containers
- ACL-enabled for production

## Related

- [[ORION]]
- [[PHOENIX Resilience]]
- [[Worker Service]]
- [[API Service]]
