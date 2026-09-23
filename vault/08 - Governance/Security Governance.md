# Security Governance

#governance #security

> Security policies and governance framework for [[ORION]].

## Principles

1. **Defense in Depth** - Multiple security layers
2. **Least Privilege** - Minimal permissions
3. **Audit Everything** - [[CHRONOS Audit|CHRONOS]] immutable log
4. **Fail Secure** - Default deny on failure
5. **No Secrets in Code** - Environment variables only

## Policies

| Policy | Implementation |
|---|---|
| Authentication | [[Keycloak Identity\|Keycloak]] JWT/JWKS |
| Authorization | [[OPA Policy Engine\|OPA]] Rego policies |
| Rate Limiting | SlowAPI per-principal |
| PII Protection | Regex masking before storage |
| Secret Management | .env (dev) → Secret Manager (prod) |
| Network Segmentation | edge/core Docker networks |
| Audit | Append-only JSONL |
| Break Glass | Time-limited elevated tokens |

## Penetration Testing

- Scope defined: `docs/governance/pentest-scope.md`
- Tool: Strix pentest suite
- Status: Scope defined, no tester engaged

## Related

- [[VEIL Security]]
- [[Zero Trust Architecture]]
- [[FORGE CYBER]]
- [[Threat Model]]
