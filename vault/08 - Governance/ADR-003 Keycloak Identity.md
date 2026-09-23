# ADR-003 Keycloak Identity

#adr #security

> Why Keycloak is the initial identity authority.

## Context

ORION needs enterprise-grade authentication with JWT/JWKS, role-based access, and integration with external identity providers.

## Decision

Use **Keycloak 23.0** as the OpenID Connect identity provider.

## Alternatives

1. **Auth0** - Vendor lock-in, cost at scale
2. **Firebase Auth** - Google ecosystem dependency
3. **Custom JWT** - Reinventing the wheel
4. **AWS Cognito** - AWS lock-in

## Consequences

- **Positive**: Open source, full control, standards-compliant, supports federation
- **Negative**: Heavy container, requires ops knowledge
- **Mitigation**: Docker Compose makes local setup trivial

## Status

Proposed

## Related

- [[Zero Trust Architecture]]
- [[VEIL Security]]
- [[API Service]]
