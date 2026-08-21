# ORION Phase 1 MVP Deployment Guide

The ORION Phase 1 MVP is fully containerized. A single command spins up the entire stack, including the AI Sentinel, the Geospatial Engine, the Hardware Translation Gateway, and the Digital Twin Dashboard.

## Prerequisites
1. Docker and Docker Compose
2. Ollama running locally on the host machine (`ollama run qwen2:0.5b`)

## Deployment

1. **Start the Stack**
   ```bash
   docker-compose up --build -d
   ```

2. **Access the Subsystems**
   - **Operator Dashboard (MIRROR TWIN):** [http://localhost:3000](http://localhost:3000)
   - **FastAPI Core (TITAN CLOUD):** [http://localhost:8001/docs](http://localhost:8001/docs)
   - **Keycloak Admin (SHIELD IDENTITY):** [http://localhost:8080](http://localhost:8080)

3. **Verify the Mesh**
   - The Postgres DB, OPA Policy Engine, and NATS JetStream will boot automatically.
   - The Python `orion-worker` will bind to JetStream and wait for CRDT events.
   - The Python `orion-sentinel` will bind to NATS and connect to the host's Ollama instance.
   - The Python `orion-aegis` will bind to NATS to receive physical hardware RF decodes.

## Architecture Highlights
- **100% Zero-Trust:** All API actions are cryptographically verified by Keycloak and policy-checked by Open Policy Agent.
- **Offline Resilience:** The CRDT worker automatically merges stale offline edge events mathematically to prevent split-brain data loss.
- **Planetary Scale (ATLAS GEO):** The system has 703 procedurally generated responder assets spanning every 10 degrees of the Earth.
- **Immutable Audit:** Every API mutation is appended to `logs/chronos_audit.jsonl` for cyber-forensics.
- **DevSecOps Hardened:** The system automatically drops malicious volumetric flooding (DoS) using `slowapi` token buckets.
