# ORION

**ORION is a research platform for studying civilization-scale machine intelligence.** It is an experimental framework — an architecture in development toward the proposed **Artificial Civilization Intelligence (ACI)** — and makes no claim to be ACI, AGI, or ASI. It exists to make such claims *testable*.

The project started as an emergency-response platform and has grown into a full-stack research system: a FastAPI service mesh, a continuity auditor, an experiment harness for brain-inspired learning (NECTAR), and a strict governance layer for any real-world interaction.

> **Intended trajectory:** ORION → AURA → OMNIS → NEXUS → FORGE → ASCEND → civilization simulation → governed real-world interaction → ACI benchmark → independent validation.

---

## Architecture

```
                    ┌───────────────────────────────────────────┐
                    │             Nginx (TLS frontier)          │
                    └───────────────────┬───────────────────────┘
                                        │
                  ┌─────────────────────┼─────────────────────┐
                  │                     │                     │
        ┌─────────▼─────────┐  ┌───────▼────────┐  ┌─────────▼────────┐
        │   orion-api (FastAPI)│ │ orion-worker   │  │ orion-sentinel   │
        │  v1/incidents,       │ │ NATS consumer  │  │ AI triage/fallback│
        │  telemetry, pilot,   │ │ + JetStream    │  │ + math coprocessor│
        │  dispatch/HITL       │ │ (incident.*)   │  │                   │
        └────┬─────────┬──────┘ └───────┬────────┘  └─────────┬────────┘
             │         │                │                      │
     ┌───────▼───┐ ┌───▼────┐   ┌──────▼─────┐        ┌───────▼───────┐
     │ Postgres  │ │ Redis  │   │ NATS       │        │ Keycloak     │
     │ (ORM/DB)  │ │ (cache │   │ (event bus)│        │ (OIDC/JWT)   │
     └───────────┘ │ + pil.)│   └────────────┘        └───────────────┘
                   └────────┘
     ┌───────────────────────────────────────────────────────────────┐
     │ Governance: OPA policy engine + FORGE verification +          │
     │             HITL approval for any physical-action transfer    │
     └───────────────────────────────────────────────────────────────┘
```

### Core pillars

| Module | Role |
|--------|------|
| **AURA** | Multimodal intelligence and reasoning core (relational state abstraction, game-lab transfer studies). |
| **OMNIS** | Continuously updateable civilization world model — entities, relationships, causality (see `modules/cic`, `services/omnis`). |
| **NEXUS** | Multi-agent intelligence fabric for coordination, dispute resolution, and aggregation. |
| **FORGE** | Scientific discovery and hypothesis generation; verifies any high-stakes recommendation. |
| **ASCEND** | Long-horizon planner (days to decades) with uncertainty handling and replanning. |
| **VEIL / SHIELD / OPA** | Governance + security layer that gates all real-world interaction. |

### Services in this repo

| Service | Path | What it does |
|---------|------|--------------|
| `orion-api` | `apps/api/main.py` | FastAPI gateway: incidents, `/v1/haven/sos`, telemetry compression, pilot suspend/resume, dispatch recommendations with human-in-the-loop, JWT auth via Keycloak JWKS. |
| `orion-worker` | `services/worker/main.py` | NATS/JetStream consumer (`incident.*`), idempotency dedup, geospatial dispatch, outbox publishing with timeout protection. |
| `orion-sentinel` | `services/ai_sentinel/main.py` | AI triage on JetStream with deterministic fallback; second-opinion math review (Mathstral via Ollama). |
| `orion-aegis` | `services/aegis/main.py` | Edge/communications gateway: validated device ingress, SOS decoding, channel management. |
| **NECTAR** | `services/nectar/` | Fruit-fly mushroom-body learning experiments (KC→MBON plasticity, Brian2 connectome simulation, reproducible RNG + stable tokenizer). |
| **CIC** | `modules/cic`, `services/cic/` | Continuity/consistency auditing: cosine-drift detection with clamped `[0,1]` scores, composite drift, policy-aware recommendations. |
| **OMNIS** | `services/omnis/` | World-model evidence ingestion + `TransferGuard` (physical-action transfers require FORGE verification regardless of confidence). |
| **FORGE CYBER** | `services/cyber/` | Normalized security event schema (OSES), SOAR response engine (policy-gated, human-approved, audited), event emitter. |
| **Mathsage** | `services/mathsage/` | LLM-backed math coprocessor used as a non-blocking second opinion in FORGE review. |

### Support services (docker-compose)

`postgres`, `redis` (password-protected), `keycloak` (OIDC), `opa` (policy), `nats` (auth'd event bus), `prometheus`, `grafana`, `jaeger` (traces), plus `orion-dashboard` (Next.js).

---

## Getting Started

1. **Clone & install** — Python 3.11+ recommended.
   ```bash
   git clone https://github.com/Team-Auralis/orion.git
   cd orion
   ```
2. **Configure environment**
   ```bash
   cp .env.example .env
   # Replace every CHANGE_ME_* value with a strong random secret:
   #   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
   `.env` is gitignored — never commit real credentials. Tests and CI rely on `REDIS_URL`.
3. **Start the stack**
   ```bash
   docker-compose up -d --build
   # Everything terminates at https://localhost:443 (Nginx); internal ports are locked down.
   ```
4. **Run the test suite** (Redis must be reachable — use the `REDIS_URL` from your `.env`):
   ```bash
   pip install -r requirements.txt -r requirements-dev.txt
   $env:REDIS_URL = "redis://:<password>@localhost:6379/0"   # PowerShell
   pytest
   ```

### Key endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/v1/incidents` | JWT | Create incident; triggers dispatch pipeline. |
| POST | `/v1/haven/sos` | public¹ | Civilian SOS ingestion (validated). |
| POST | `/v1/auth/break-glass` | public¹ | Emergency access (audited; JWT issued). |
| POST | `/v1/telemetry/compress` | public¹ | Lossy quaternary/ternary packing + sensor consistency gating (rate-limited and input-capped). |
| GET | `/v1/pilot/status`, POST `/v1/pilot/suspend`/`resume` | JWT+admin | AI pilot kill-switch. |
| GET | `/v1/dispatch/recommendations` | JWT | HITL dispatch recommendations. |
| GET | `/v1/ai/health` | JWT | Ollama/AI-stack health. |

¹ Public endpoints are defense-in-depth: rate-limited via slowapi, bounded input sizes, and validation at the model boundary.

---

## Security Model

- **Authentication:** RS256 JWTs from Keycloak, verified against the realm JWKS by `kid` — forged/expired/unknown-key tokens are rejected (see `tests/test_jwt_verification.py`).
- **Rate limiting / spoofing:** `X-Real-IP` is only trusted from known proxy peers (`TRUSTED_PROXY_IPS`); the rate limiter can't be gamed with a spoofed header.
- **Secrets hygiene:** `.env`, private keys, DB files, and model weights are gitignored and dockerignored; compose wires secrets via `${REDIS_PASSWORD}` etc., never literals.
- **Governance / HITL:** physical-action transfers must pass FORGE verification (`services/omnis/transfer_guard.py`); SOAR responses require human approval for high-impact actions; self-approval, non-human approvers, stale/future approvals are all rejected.
- **Input validation:** pydantic caps (e.g. `states` ≤ 100k, `readings` ≤ 10k) prevent unbounded payload DoS on unauthenticated paths.
- **Data integrity:** worker dedup fails open (a Redis outage can't silently drop events); JetStream uses correct ack/nak semantics with `nak(delay=5)` on transient errors; outbox publishes time out instead of wedging the loop.

---

## Testing

- **Suite:** `pytest` (169+ tests) — see `pytest.ini` / `requirements-dev.txt`.
- **Coverage highlights:** JWT verification, secrets hygiene (`test_no_secrets.py`), JetStream/ack semantics, outbox chaos, rate-limit spoofing, transfer-guard policy, CIC drift, NECTAR tokenizer determinism, flymemory vectorization, SOAR approval flows.
- **CI:** `.github/workflows/ci.yml` runs the suite; `strix-security.yml` runs an external agentic pentest over `apps/api` and `services/worker`.

---

## Repository Layout

```
apps/api          FastAPI gateway (routes, auth, telemetry, pilot, dispatch)
apps/dashboard    Next.js dashboard
apps/mobile       Mobile app
services/         Worker, sentinel, aegis, nectar, cic, omnis, cyber, forge, nexus, ascend...
modules/          Reusable research modules (CIC layers, game-lab, orbital-view)
scripts/          Training, evaluation, hardening and audit tooling
tests/            pytest suite
infra/            Compose, Nginx, Keycloak realm, certs (public only)
docs/             ACI architecture documentation suite
contracts/        Interface/protocol contracts
policy/           Governance policies (OPA)
forge/            FORGE experiment artifacts
```

---

## Experimental Status

- Portions of the platform are pipelines and scaffolding around the research subsystems; the most actively developed research areas are **NECTAR** (connectome learning with reproducible seeds) and **game-lab** (transfer learning under controlled comparisons).
- Transfer experiments report *whatever the evidence shows* — e.g. matched hyperparameters removed a learning-rate confound and the claimed transfer advantage honestly disappeared under several seeds.
- Model checkpoints and trained artifacts are **not** distributed in this repository.

## License

See `THIRD_PARTY.md` and the repository copyright header. All rights reserved.