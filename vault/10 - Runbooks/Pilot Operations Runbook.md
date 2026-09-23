# Pilot Operations Runbook

#operations #runbook #pilot

> Day-to-day operations during the closed pilot phase.

## Pre-Pilot Checklist

- [ ] Geofence bounding box configured
- [ ] Operator accounts created and tested
- [ ] Hardware devices registered (if applicable)
- [ ] Kill switch tested
- [ ] Monitoring dashboards reviewed
- [ ] All team members briefed

## Daily Operations

### Morning
1. Check Grafana dashboards for overnight anomalies
2. Review CHRONOS audit log for unusual activity
3. Verify all services healthy
4. Check circuit breaker states

### During Operations
1. Monitor incoming incidents
2. Review AI Sentinel triage accuracy
3. Approve/reject dispatch recommendations
4. Handle any break-glass requests

### End of Day
1. Review day's incidents
2. Check for any unresolved alerts
3. Backup database
4. Log any issues

## Kill Switch

### Activate
```bash
curl -k -X POST https://localhost:443/v1/pilot/kill-switch \
  -H "Authorization: Bearer <operator-jwt>" \
  -d '{"action": "suspend"}'
```

### Deactivate
```bash
curl -k -X POST https://localhost:443/v1/pilot/kill-switch \
  -H "Authorization: Bearer <operator-jwt>" \
  -d '{"action": "resume"}'
```

## Escalation Path

1. Operator → Team Lead
2. Team Lead → System Admin
3. System Admin → External Support (if needed)

## Related

- [[Pilot Plan]]
- [[Phase 1.5 - Deployment Hardening]]
- [[Incident Response Runbook]]
