# Zero Trust Architecture

#security #architecture

> Every request is authenticated, authorized, and audited. No implicit trust.

## Principles

1. **Never trust, always verify** - Every request authenticated
2. **Least privilege** - Minimal permissions granted
3. **Assume breach** - Design for compromise detection
4. **Micro-segmentation** - Network isolation between services

## Trust Boundaries

```mermaid
graph TD
    subgraph internet["INTERNET"]
        CLIENT["Client"]
    end
    subgraph edge["EDGE"]
        NGINX["NGINX\nTLS Termination"]
        API["API"]
        DASH["Dashboard"]
        ORB["Orbital View"]
    end
    subgraph core["CORE"]
        WORKER["Worker"]
        SENTINEL["Sentinel"]
        AEGIS["AEGIS"]
        KC["Keycloak"]
        OPA["OPA"]
    end
    subgraph data["DATA TIER"]
        PG["PostgreSQL"]
        REDIS["Redis"]
        NATS["NATS"]
    end

    CLIENT --> NGINX
    NGINX --> API
    NGINX --> DASH
    NGINX --> ORB
    API --> WORKER
    API --> SENTINEL
    API --> AEGIS
    API --> KC
    API --> OPA
    WORKER --> PG
    WORKER --> REDIS
    WORKER --> NATS
```

## Authentication Flow

```mermaid
sequenceDiagram
    participant C as Client
    participant N as Nginx
    participant A as API
    participant K as Keycloak
    participant O as OPA
    participant H as Handler

    C->>N: Request + JWT
    N->>A: Forward
    A->>A: Extract JWT from header
    A->>K: Fetch JWKS
    K-->>A: Public keys
    A->>A: Verify JWT signature + expiry
    A->>A: Extract roles + principal
    A->>O: Policy check {principal, method, path, roles}
    O-->>A: Allow / Deny
    alt Allowed
        A->>H: Execute handler
        H-->>C: Response
    else Denied
        A-->>C: 403 Forbidden
    end
```

## Related

- [[VEIL Security]]
- [[Keycloak Identity]]
- [[OPA Policy Engine]]
- [[Break Glass Protocol]]
- [[FORGE CYBER]]
