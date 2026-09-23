# AEGIS Gateway Runbook

#operations #runbook #hardware

> Operations for the [[AEGIS Gateway]] hardware communications layer.

## Device Registration

### Add New Device

```bash
# Register device with HMAC key
curl -k -X POST https://localhost:443/v1/aegis/devices \
  -H "Authorization: Bearer <operator-jwt>" \
  -d '{
    "device_id": "DEVICE-001",
    "hmac_key": "shared-secret-key",
    "protocol": "lorawan",
    "location": {"lat": 28.6139, "lon": 77.2090}
  }'
```

## Monitoring

### Check Gateway Status

```bash
docker logs orion-aegis --tail 100
```

### Common Log Messages

| Message | Meaning |
|---|---|
| `HMAC verification passed` | Device authenticated |
| `HMAC verification failed` | Invalid device signature |
| `LoRaWAN packet decoded` | Successful decode |
| `Radio SOS received` | Direct radio signal |

## Troubleshooting

### Device Not Connecting
1. Verify HMAC key matches device configuration
2. Check radio frequency alignment
3. Verify device is within range
4. Check gateway logs for errors

### Payload Parsing Errors
1. Verify binary format matches expected schema
2. Check device firmware version
3. Review payload hex dump in logs

## Related

- [[AEGIS Gateway]]
- [[AEGIS Service]]
- [[NATS Event Mesh]]
