# Threat Model

#security #architecture

> STRIDE-based threat analysis for [[ORION]].

## Scope

Full platform analysis covering:
- Authentication/Authorization bypass
- Data exfiltration
- Denial of service
- Privilege escalation
- Tampering with audit logs

## STRIDE Analysis

| Threat | Category | Mitigation |
|---|---|---|
| JWT forgery | Spoofing | Keycloak JWKS verification |
| OPA bypass | Elevation of Privilege | Break-glass audit trail |
| Incident tampering | Tampering | CRDT Max-State (forward only) |
| SOS flood | Denial of Service | SlowAPI rate limiting |
| PII exposure | Information Disclosure | PII masking before storage |
| Audit log tampering | Tampering | Append-only JSONL |
| Lateral movement | Elevation of Privilege | Network segmentation (edge/core) |

## Findings (R-01 through R-10)

| Finding | Status |
|---|---|
| R-01: Exception classification + idempotent replay | Closed |
| R-04: Redis ACL + network segmentation | Closed (config) |
| R-05: Rego Rule 2b | Closed |
| R-07: Coordinate validation + sanitized 422 | Closed |
| R-08: Secret rotation | Closed |
| R-09: Subject-partitioned rate keys | Closed |

## Documentation

- `docs/cyber/threat-model.md` - Full STRIDE mapping
- `docs/cyber/architecture.md` - Component model
- `docs/cyber/range-plan.md` - FORGE RANGE scenarios

## Related

- [[VEIL Security]]
- [[FORGE CYBER]]
- [[Zero Trust Architecture]]
