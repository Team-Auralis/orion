# Keycloak Identity

#security #identity

> OpenID Connect identity provider for ORION.

## Purpose

Keycloak handles authentication and identity management. It issues JWT tokens that are verified by the [[API Service]] on every request.

## Configuration

| Setting | Value |
|---|---|
| **Version** | 23.0 |
| **Protocol** | OpenID Connect |
| **Token Type** | JWT |
| **Verification** | JWKS endpoint |

## Roles

| Role | Permissions |
|---|---|
| **citizen** | Create SOS incidents, read own incidents |
| **operator** | Full CRUD, dispatch, break-glass, pilot controls |

## JWT Flow

```mermaid
sequenceDiagram
    participant U as User
    participant K as Keycloak
    participant A as API
    participant O as OPA

    U->>K: Authenticate
    K-->>U: JWT (signed)
    U->>A: Request + JWT
    A->>K: Fetch JWKS
    K-->>A: Public keys
    A->>A: Verify JWT signature
    A->>A: Extract principal + roles
    A->>O: Check authorization
    O-->>A: Allow / Deny
```

## Circuit Breaker

- Fail-fast after 5 consecutive JWKS fetch failures
- 30-second cooldown
- Redis-backed state

## Related

- [[VEIL Security]]
- [[Zero Trust Architecture]]
- [[OPA Policy Engine]]
- [[API Service]]
