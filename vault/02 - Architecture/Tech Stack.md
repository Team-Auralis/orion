# Tech Stack

#architecture #infrastructure

> Complete technology stack for [[ORION]].

## Backend (Python)

| Component | Technology | Version | Purpose |
|---|---|---|---|
| **Web Framework** | FastAPI | 0.110.0 | Core REST API |
| **ASGI Server** | Uvicorn | - | ASGI serving |
| **ORM** | SQLAlchemy | 2.0.28 | Database access |
| **Database** | PostgreSQL | 15 | Application state |
| **Migrations** | Alembic | - | Schema management |
| **Message Bus** | NATS (nats-py) | 2.7.0 | Event mesh with JetStream |
| **Cache/Dedup** | Redis | 5.0.3 | Circuit breakers, dedup, kill-switch |
| **Identity** | Keycloak | 23.0 | OpenID Connect (JWT/JWKS) |
| **Authorization** | Open Policy Agent (OPA) | - | Rego policy engine |
| **Rate Limiting** | SlowAPI | - | Per-principal token buckets |
| **Retries** | Tenacity | - | Backoff/retry logic |
| **HTTP Client** | httpx | - | Async (OPA, Keycloak, Ollama) |
| **JWT** | PyJWT + cryptography | - | Token handling |
| **AI/LLM** | Ollama (qwen2:0.5b) | - | Local inference for triage |

## Frontend (TypeScript/React)

| Component | Technology | Version | Purpose |
|---|---|---|---|
| **Framework** | Next.js | 16.3.1 | Operator dashboard |
| **UI Library** | React | 19 | Component system |
| **Styling** | Tailwind CSS | 4 | Utility-first CSS |
| **Auth** | next-auth | - | Authentication integration |

## Orbital View (JavaScript)

| Component | Technology | Purpose |
|---|---|---|
| **3D Globe** | Cesium.js | Photorealistic visualization |
| **Satellite Math** | satellite.js | Orbit propagation |
| **Build** | Vite | Bundling |

## Infrastructure/DevOps

| Component | Technology | Purpose |
|---|---|---|
| **Containerization** | Docker Compose 3.8 | 14+ services |
| **Orchestration** | Kubernetes | Production deployment |
| **Reverse Proxy** | Nginx | TLS termination (80/443) |
| **Metrics** | Prometheus | Time-series metrics |
| **Dashboards** | Grafana | Visualization |
| **Tracing** | OpenTelemetry + Jaeger | Distributed tracing |

## Security Tooling

| Component | Purpose |
|---|---|
| **Strix** | Pentesting/security scanning |
| **FORGE CYBER** | Detection engine (11 rules) + SOAR |
| **PII Masking** | Regex scrubbing (SSN, phone, email) |

## Hardware Integration

| Component | Purpose |
|---|---|
| **LoRaWAN** | Long-range emergency packets |
| **Direct Radio** | AEGIS radio SOS decoding |
| **HMAC-SHA256** | Device authentication |
| **Binary Payload** | Lat/lon/battery parsing |

## Related

- [[System Architecture]]
- [[Docker Compose]]
- [[Kubernetes]]
- [[ORION]]
