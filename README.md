# ORION: Planetary Resilience & Digital Twin Infrastructure

> **dY> RESTRICTED ACCESS: PROPRIETARY & CONFIDENTIAL dY>**
> 
> **COPYRIGHT (c) 2026 TEAM AURALIS / SHAURYA. ALL RIGHTS RESERVED.**
> 
> **ZERO TOLERANCE POLICY:** This is NOT open-source. This repository, its source code, and its underlying architectural concepts are the exclusive private property of Team Auralis. You are **STRICTLY PROHIBITED** from copying, duplicating, reverse-engineering, modifying, distributing, or using this code or idea for any purpose (including training AI models). 
> 
> Intellectual property theft will result in immediate, aggressive, and uncompromising legal action. If you wish to negotiate a commercial or research license, you must contact Team Auralis directly and obtain written consent. **DO NOT STEAL THIS.**

---

## Current Project Status

- **Phase 1 - MVP Construction:** COMPLETE
- **Phase 1.5 - Software Hardening & Red Team Remediation:** COMPLETE ?? *(10/10 Critical Vulnerabilities Neutralized)*
- **Phase 1.5 - Physical Pilot Gate:** PENDING *(Awaiting Chaos Drills & Partner Pentest)*
- **Controlled Field Pilot:** NOT YET EXECUTED
- **Phase 2 - Scale & Federation:** PLANNED
- **Phase 3 - Global Mesh / Satellite Backhaul:** LONG-TERM PLANNED

ORION has completed its MVP construction and intense software hardening cycle. The system successfully passed an adversarial Red Team engagement, neutralizing all critical attack vectors including Phoenix fallback bugs, token extraction, idempotency races, BOLA IP spoofing, and infrastructure plane isolation. The prototype is technically hardened and preparing for a controlled, geofenced field pilot.

## Architecture
ORION employs a resilient, zero-trust event-driven architecture:
Device -> Nginx (TLS/Rate Limit) -> FastAPI -> Keycloak OIDC -> OPA Policy -> Postgres (Outbox) -> NATS JetStream -> Worker (AI Triage) -> Dashboard

## Claim / Evidence Matrix

| Capability | Evidence | Status | Confidence |
|---|---|---|---|
| JWT Authentication | PyJWT signature validation with Keycloak JWKS | Validated | High |
| OPA Authorization | Rego rules enforcing RBAC per-endpoint | Validated | High |
| Internal Infrastructure | NATS, Redis, Postgres on isolated Docker networks | Validated | High |
| API Idempotency | Namespaced UUIDs tested against concurrent races | Validated | High |
| Event Reliability | Strict Transactional Outbox pattern implemented | Validated | High |
| AI Fallback | Worker deterministic fallback | Validated | High |
| Geospatial Routing | Rejects NaN coords, enforces valid bounds | Validated | High |
| HITL Safety | Optimistic Concurrency Control, 10-min TTL, Break-glass audits | Validated | High |
| Rate Limiter | IP spoofing blocked via Nginx X-Real-IP | Validated | High |
| Backup/Restore | scripts/dr_backup_restore.py RTO metrics | Validated | High |
| Live Chaos Drills | Pending execution on Docker stack | Pending | N/A |
| Physical Pilot | AEGIS hardware & geofenced partner deployment | Pending | N/A |

## Quickstart (Development Stack)

1. **Environment Setup**
   A secure .env file is required. Do not commit it to version control.
   Generate one securely using Python:
   `ash
   python -c "import secrets; print(f\"POSTGRES_USER=orion_admin\\nPOSTGRES_PASSWORD={secrets.token_hex(16)}\\nPOSTGRES_DB=orion\\nDATABASE_URL=postgresql://orion_admin:pass@postgres:5432/orion\\nREDIS_PASSWORD={secrets.token_hex(16)}\\nNATS_USER=orion_worker\\nNATS_PASSWORD={secrets.token_hex(16)}\\nKEYCLOAK_ADMIN=admin\\nKEYCLOAK_ADMIN_PASSWORD={secrets.token_hex(16)}\\nKC_DB=postgres\\nKC_DB_URL=jdbc:postgresql://postgres:5432/orion\\nKC_DB_USERNAME=orion_admin\\nKC_DB_PASSWORD=pass\\nGF_SECURITY_ADMIN_USER=admin\\nGF_SECURITY_ADMIN_PASSWORD={secrets.token_hex(16)}\\nGF_DATABASE_TYPE=postgres\\nGF_DATABASE_HOST=postgres:5432\\nGF_DATABASE_NAME=orion\\nGF_DATABASE_USER=orion_admin\\nGF_DATABASE_PASSWORD=pass\")" > .env
   `

2. **Boot the Cluster**
   `ash
   docker-compose up -d --build
   `

3. **Verify Security Posture**
   Run the adversarial probe against the live stack:
   `ash
   python scripts/security_probe.py --url https://localhost:443
   python scripts/redteam_probe.py
   `
