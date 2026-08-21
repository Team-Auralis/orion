import asyncio
import struct
import binascii
import os
import json
import uuid
import nats
from datetime import datetime, timezone

NATS_URL = os.environ.get("NATS_URL", "nats://localhost:4222")

# AEGIS COMMS PROTOCOL V1
# Byte 0: Message Type (0x01 = SOS)
# Byte 1-4: Latitude (Float32, Big Endian)
# Byte 5-8: Longitude (Float32, Big Endian)
# Byte 9: Battery Level (0-100)

class AegisHardwareGateway:
    def __init__(self):
        self.nc = nats.NATS()

    async def connect(self):
        await self.nc.connect(NATS_URL)
        print("AEGIS Gateway connected to Event Mesh.")

    async def decode_and_route_payload(self, hex_payload: str, device_eui: str):
        try:
            raw_bytes = binascii.unhexlify(hex_payload)
            if len(raw_bytes) != 10:
                print(f"[AEGIS] DROP: Invalid payload length {len(raw_bytes)}. Expected 10 bytes.")
                return

            msg_type = raw_bytes[0]
            if msg_type != 0x01:
                print(f"[AEGIS] DROP: Unknown message type {msg_type}")
                return

            # Decode Float32 (Big Endian)
            lat = struct.unpack(">f", raw_bytes[1:5])[0]
            lon = struct.unpack(">f", raw_bytes[5:9])[0]
            battery = raw_bytes[9]

            print(f"[AEGIS] DECODED PHYSICAL PACKET from {device_eui}:")
            print(f"        LAT: {lat:.6f}, LON: {lon:.6f}, BATTERY: {battery}%")

            # Translate to ORION Cloud JSON Format
            incident_id = f"INC-HW-{uuid.uuid4().hex[:6].upper()}"
            event = {
                "event_id": f"evt-{uuid.uuid4()}",
                "event_type": "incident.created",
                "version": 1,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "incident_id": incident_id,
                "actor_id": f"hw-{device_eui}",
                "incident_type": "HARDWARE_SOS",
                "message": f"Raw LoRaWAN SOS. Battery: {battery}%",
                "correlation_id": f"hwreq-{uuid.uuid4().hex[:6]}"
            }
            
            # Since the Hardware Gateway bypasses the API (it's physically connected to edge mesh),
            # we also need to pass the latitude and longitude in the event so the CRDT worker can create it.
            # Upgrading the event schema slightly for hardware:
            event["hardware_lat"] = lat
            event["hardware_lon"] = lon

            await self.nc.publish("incident.created", json.dumps(event).encode())
            print(f"[AEGIS] TRANSLATED & ROUTED TO CLOUD as {incident_id}")

        except Exception as e:
            print(f"[AEGIS] FATAL DECODE ERROR: {e}")

async def run_simulation():
    gateway = AegisHardwareGateway()
    await gateway.connect()
    
    print("\n[AEGIS] Listening for physical RF packets...")
    await asyncio.sleep(1)
    
    print("\n[AEGIS] << RECEIVING RAW LORAWAN PACKET FROM DEVICE A8B4C9...")
    # Simulate a raw packet: 
    # Type: 0x01
    # Lat: 37.7749 (San Francisco) -> 0x421719c2
    # Lon: -122.4194 -> 0xc2f4d54f
    # Bat: 15% -> 0x0f
    # Payload = 01421719c2c2f4d54f0f
    
    hex_payload = "01421719c2c2f4d54f0f"
    print(f"[AEGIS] RAW HEX: {hex_payload}")
    await gateway.decode_and_route_payload(hex_payload, "A8B4C9")
    
    await asyncio.sleep(1)
    
    # We must also ensure the worker knows how to extract `hardware_lat` and `hardware_lon`
    print("\n[AEGIS] Simulation complete. Terminating gateway.")
    await gateway.nc.close()

if __name__ == "__main__":
    asyncio.run(run_simulation())
