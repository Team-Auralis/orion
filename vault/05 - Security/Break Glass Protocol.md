# Break Glass Protocol

#security #emergency

> Emergency override mechanism for catastrophic failures.

## Purpose

When normal security controls prevent critical emergency response, operators can bypass OPA authorization using a short-lived elevated token.

## Flow

```
1. Operator triggers break-glass
2. System mints 15-minute elevated token
3. Token bypasses OPA checks
4. All actions fully audited in CHRONOS
5. Token auto-expires after 15 minutes
```

## Safeguards

| Safeguard | Description |
|---|---|
| **Time-Limited** | 15-minute token expiry |
| **Audited** | Every break-glass action logged |
| **Authenticated** | Only authenticated operators can trigger |
| **HITL Required** | Human-in-the-loop approval |
| **Rate Limited** | Cannot be spammed |

## Test Coverage

- Break-glass mint: tested
- Break-glass use: tested
- Break-glass denial (expired/invalid): tested
- 3/3 HITL safety suite passed

## Related

- [[VEIL Security]]
- [[OPA Policy Engine]]
- [[CHRONOS Audit]]
- [[API Service]]
- [[Break Glass Runbook]]
