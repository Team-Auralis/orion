# Break Glass Runbook

#operations #runbook #security

> Emergency override procedures for [[ORION]].

## When to Use

- Normal OPA authorization is blocking critical emergency response
- Keycloak is unreachable
- System is in degraded mode and operators need elevated access

## Procedure

### 1. Trigger Break-Glass

```bash
# Via API
curl -k -X POST https://localhost:443/v1/break-glass \
  -H "Authorization: Bearer <operator-jwt>" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Critical emergency - normal auth degraded"}'
```

### 2. Receive Elevated Token

System returns a 15-minute elevated token. Use this for subsequent requests.

### 3. Execute Emergency Actions

All actions with elevated token are fully audited in [[CHRONOS Audit|CHRONOS]].

### 4. Token Auto-Expires

After 15 minutes, normal authorization resumes.

## Safeguards

- Only authenticated operators can trigger
- All actions logged with timestamps
- Rate limited to prevent abuse
- Time-limited (15 minutes)

## Audit Review

After break-glass event:
1. Review `chronos_audit.jsonl` for all actions taken
2. Verify no unauthorized actions
3. Document reason in incident report

## Related

- [[Break Glass Protocol]]
- [[VEIL Security]]
- [[OPA Policy Engine]]
- [[Incident Response Runbook]]
