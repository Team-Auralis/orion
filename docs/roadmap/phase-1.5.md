# Phase 1.5: Deployment Hardening Gate

**Status:** IN PROGRESS // PRE-FLIGHT

While Phase 1 successfully established the functional core of the ORION platform (API, Mesh, AI, Dispatch), the system is classified as a **Technically Validated Prototype**. Before it can be exposed to public networks or relied upon by real emergency responders, it must pass this critical hardening gate.

## Objectives

### 1. Operational Controls (Human-in-the-Loop)
- [ ] Implement explicit operator approval workflows for physical asset dispatch.
- [ ] Transition AI strictly to a `classify → recommend → explain` paradigm.
- [ ] Implement a **Policy Recheck** step immediately preceding physical dispatch to prevent UI bypass.

### 2. Observability & SRE
- [ ] Deploy Prometheus and Grafana for metrics visualization.
- [ ] Implement OpenTelemetry distributed tracing across the API and CRDT workers.
- [ ] Define measurable Service Level Objectives (SLOs) (e.g., `< 1s SOS acceptance latency`, `> 99.9% availability`).

### 3. Reliability & Recovery
- [ ] Test deterministic max-state merge strategies under load (CRDT semantics).
- [ ] Design and test PostgreSQL backup/restore procedures.
- [ ] Run failure/recovery drills on NATS cluster partitions.

### 4. Security & Privacy
- [ ] Implement application-layer rate limiting and abuse protection with measurable metrics.
- [ ] Migrate from `.env` files to a production Secret Manager with automated credential rotation.
- [ ] Execute an independent, third-party penetration test.
- [ ] Establish Data Minimization and Retention policies.

### 5. AI Safety & Validation
- [ ] Conduct adversarial testing against the Sentinel AI NLP engine.
- [ ] Build strict deterministic fallback parsers (AI unavailable → Deterministic Rules → Human Review).

### 6. The Final Gate: Closed Pilot
- [ ] Run a controlled, authenticated pilot with a partnered emergency response organization in a geofenced area.
