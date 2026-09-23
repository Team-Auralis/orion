# ADR-004 OPA Policy

#adr #security

> Why OPA is an independent authorization layer.

## Context

Authorization logic should be separated from application code for auditability, testability, and policy-as-code governance.

## Decision

Use **Open Policy Agent (OPA)** with Rego policies for authorization.

## Alternatives

1. **Casbin** - Less mature ecosystem
2. **Built-in FastAPI deps** - Tightly coupled to code
3. **Keycloak authorization** - Less flexible policy language

## Consequences

- **Positive**: Policy-as-code, testable, auditable, language-agnostic
- **Negative**: Additional service, learning curve for Rego
- **Mitigation**: Simple policies, comprehensive tests

## Status

Proposed

## Related

- [[Zero Trust Architecture]]
- [[VEIL Security]]
- [[Break Glass Protocol]]
