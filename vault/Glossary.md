# Glossary

#reference

> Key terms and definitions for [[ORION]].

## ACI Framework

| Term | Definition |
|---|---|
| **ACI** | Artificial Civilization Intelligence - proposed class of intelligent system architecture |
| **ORION** | The research platform being developed toward ACI |
| **AURA** | Multimodal intelligence and reasoning core |
| **OMNIS** | Civilization world model (entities, relationships, causality) |
| **NEXUS** | Multi-agent intelligence fabric |
| **FORGE** | Scientific discovery engine |
| **ASCEND** | Long-horizon planner (days to decades) |
| **MIRROR** | Digital twin / simulation layer |
| **VEIL** | Zero-trust governance and security layer |

## ORION Legacy Modules

| Term | Definition |
|---|---|
| **AEGIS** | Hardware communications gateway (LoRaWAN/radio) |
| **HAVEN** | Civilian-facing emergency platform |
| **PHOENIX** | Offline-first, degraded mode, disaster recovery |
| **ATLAS** | Cloud/edge infrastructure + geospatial dispatch |
| **CHRONOS** | Immutable audit trail |
| **SENTIENCE** | Legacy AI triage (deprecated → AURA) |
| **TITAN** | Legacy cloud layer (deprecated → ATLAS) |
| **SHIELD** | Legacy identity (deprecated → VEIL) |

## Technical Terms

| Term | Definition |
|---|---|
| **CRDT** | Conflict-free Replicated Data Type - merge without coordination |
| **Max-State CRDT** | CRDT where higher status always wins |
| **JetStream** | NATS persistent messaging with replay |
| **Outbox Pattern** | Transactional outbox for exactly-once event publishing |
| **HITL** | Human-in-the-Loop - operator approval required |
| **OCC** | Optimistic Concurrency Control |
| **HMAC** | Hash-based Message Authentication Code |
| **JWKS** | JSON Web Key Set - public keys for JWT verification |
| **Rego** | Policy language for OPA |
| **SOAR** | Security Orchestration, Automation and Response |
| **MTTD** | Mean Time to Detect |
| **MTTR** | Mean Time to Respond |
| **RTO** | Recovery Time Objective |
| **RPO** | Recovery Point Objective |

## Incident States

| State | Definition |
|---|---|
| **CREATED** | Initial state |
| **REPORTED** | Submitted by civilian/hardware |
| **TRIAGED** | AI classification complete |
| **DISPATCHING** | Responder en route |
| **EVACUATING** | Active evacuation |
| **RESOLVED** | Incident handled |

## Security Terms

| Term | Definition |
|---|---|
| **Break-Glass** | Emergency OPA bypass with elevated token |
| **Kill Switch** | Redis-backed instant operation suspension |
| **Geofencing** | Bounding box constraint for pilot mode |
| **Zero Trust** | No implicit trust, verify everything |
| **PII** | Personally Identifiable Information |

## Related

- [[ORION]]
- [[System Architecture]]
