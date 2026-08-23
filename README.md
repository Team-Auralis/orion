# ORION: Planetary Resilience & Digital Twin Infrastructure

> **🛑 RESTRICTED ACCESS: PROPRIETARY & CONFIDENTIAL 🛑**
> 
> **COPYRIGHT (c) 2026 TEAM AURALIS / SHAURYA. ALL RIGHTS RESERVED.**
> 
> **ZERO TOLERANCE POLICY:** This is NOT open-source. This repository, its source code, and its underlying architectural concepts are the exclusive private property of Team Auralis. You are **STRICTLY PROHIBITED** from copying, duplicating, reverse-engineering, modifying, distributing, or using this code or idea for any purpose (including training AI models). 
> 
> Intellectual property theft will result in immediate, aggressive, and uncompromising legal action. If you wish to negotiate a commercial or research license, you must contact Team Auralis directly and obtain written consent. **DO NOT STEAL THIS.**

---

## Current Project Status

Phase 1 - MVP Construction: COMPLETE

Phase 1.5 - Software Hardening: COMPLETE

Phase 1.5 - Physical Pilot Gate: PENDING

Controlled Field Pilot: NOT YET EXECUTED

Phase 2 - Scale & Federation: PLANNED

Phase 3 - Global Mesh / Satellite Backhaul: LONG-TERM PLANNED

ORION has completed its MVP construction and software hardening cycle and is now a technically hardened emergency-response prototype preparing for a controlled, geofenced field pilot. The platform is not yet a production emergency service; remaining validation, partner deployment, and operational evidence are explicit gates rather than implied capabilities.

## 7. Phase 0/1 objective
> **Prove two devices can communicate through a simulated SOS workflow, with an independent policy engine validating the action.**

## 8. High-level architecture
`Device -> FastAPI -> Keycloak Identity -> OPA Policy -> PostgreSQL State -> NATS Event -> Worker -> Operator Dashboard`

## 9. Security model
Zero-trust relying on Keycloak for identity ("Who are you?") and OPA for authorization ("Are you allowed to do this?"). FastAPI coordinates without duplicating rules.

## 10. Research directions
Resilient communication, digital twins, distributed infra, zero-trust edge, adversarial AI security.

## 11. Documentation map
See the `docs/` folder. Everything is organized into 12 core parts, governance, roadmap, and phase-0-1 specs.

## 12. Roadmap
- Phase 0: Architecture + repository + documentation.
- Phase 1: Core SOS vertical slice.
- Phase 2: Resilience, failure testing, offline support.
- Phase 3: Telemetry and intelligence.
- Phase 4: AI decision-support.
- Phase 5: Digital Twin.
- Phase 6: Civilian deployment.

## 13. Scope boundary
In scope: civilian communication, emergency coordination, satellite mesh, zero-trust.
Out of scope: autonomous weapons, targeting systems, military control.

## 14. Repository status
Official technical knowledge base and architectural source of truth for ORION.

## Claim / Evidence Matrix

| Capability | Evidence | Status | Confidence |
|---|---|---|---|
| API | 	ests/test_api_unit.py | Implemented | High |
| JWT authentication | 	ests/test_api_unit.py | Validated | High |
| OPA authorization | 	ests/test_api_unit.py | Validated | High |
| API idempotency | 	ests/test_advanced_backend.py | Validated | High |
| Event reliability | Transactional Outbox (API) | Implemented | Medium (chaos tests pending) |
| AI fallback | Worker deterministic fallback | Validated | High |
| Geospatial routing | 	ests/test_advanced_backend.py | Implemented/Validated | High |
| AEGIS hardware | N/A | Pilot pending | N/A |
| HITL Safety | tests/test_hitl_safety.py (Break-Glass Bypass) | Validated | High (Live OPA path pending) |
| Backup/restore | scripts/dr_backup_restore.py | Validated | High (1.60s RTO on 0.21MB test DB) |
| Observability | OpenTelemetry + Prometheus setup | Implemented | Medium (Live environment verification pending) |
| Physical pilot | N/A | Pilot pending | N/A |
