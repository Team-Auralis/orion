# Disaster Recovery Runbook

#operations #runbook

> Backup and restore procedures for [[ORION]].

## Backup

### Automated Backup

```bash
# Run backup script
python scripts/dr_backup_restore.py --backup
```

### Manual PostgreSQL Backup

```bash
docker exec postgres pg_dump -U orion orion > backup_$(date +%Y%m%d).sql
```

## Restore

```bash
# Automated restore
python scripts/dr_backup_restore.py --restore backup_20260904.sql

# Manual restore
cat backup.sql | docker exec -i postgres psql -U orion orion
```

## DR Metrics

| Metric | Target | Actual |
|---|---|---|
| **RTO** (Recovery Time Objective) | < 30s | **1.60s** |
| **RPO** (Recovery Point Objective) | < 1hr | Depends on backup frequency |
| **Test Snapshot Size** | - | 0.21 MB |

## DR Drill Schedule

- **Weekly**: Automated backup verification
- **Monthly**: Full restore drill
- **Quarterly**: Production-like DR exercise

## Related

- [[PostgreSQL]]
- [[PHOENIX Resilience]]
- [[Deployment Runbook]]
