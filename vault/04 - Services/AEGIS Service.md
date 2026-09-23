# AEGIS Service

#service #hardware #communications

> LoRaWAN and direct radio SOS decoding gateway.

## Location

`services/aegis/main.py` (148 lines)

## Protocols

| Protocol | Use Case |
|---|---|
| **LoRaWAN** | Long-range, low-power emergency packets |
| **Direct Radio** | Short-range radio SOS signals |

## Processing Pipeline

```mermaid
graph TD
    SIGNAL["Radio / LoRaWAN Signal"] --> RECV["Packet Reception"]
    RECV --> AUTH{"HMAC-SHA256\nDevice Authentication"}
    AUTH -->|"Valid"| PARSE["Binary Payload Parsing"]
    AUTH -->|"Invalid"| REJ["Log + Reject"]
    PARSE --> LAT["Latitude (float)"]
    PARSE --> LON["Longitude (float)"]
    PARSE --> BAT["Battery Level (int)"]
    LAT --> NORM["Normalize to JSON"]
    LON --> NORM
    BAT --> NORM
    NORM --> PUB["Publish to NATS JetStream"]
    PUB --> W["Worker (CRDT Sync)"]
    W --> PG["PostgreSQL"]
```

## Security

- Every packet must have valid HMAC-SHA256 signature
- Device registry for authorized hardware
- Invalid signatures logged in [[CHRONOS Audit|CHRONOS]]

## Related

- [[ORION]]
- [[AEGIS Gateway]]
- [[NATS Event Mesh]]
- [[Worker Service]]
