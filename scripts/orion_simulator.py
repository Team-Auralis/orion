import asyncio
import json
import uuid
import nats
from datetime import datetime, timezone

async def run_disaster_scenario():
    print("--- [ORION DIGITAL TWIN SIMULATOR] ---")
    print("Scenario: Cyclone Outage (Large-area cellular failure & SOS surge)\n")
    
    try:
        nc = await nats.connect("nats://localhost:4222")
        js = nc.jetstream()
        print("[*] Connected to NATS Event Bus.")
    except Exception as e:
        print(f"[!] Could not connect to local NATS (Docker is likely offline): {e}")
        print("    -> Simulator requires the NATS edge cluster to run.")
        return
        
    print("\n[*] INJECTING: Regional cellular network failure (Region: COASTAL)")
    network_fail_event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "network.link_degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "region": "COASTAL",
        "link_type": "cellular",
        "status": "OFFLINE"
    }
    await js.publish("incident.created", json.dumps(network_fail_event).encode())
    
    print("\n[*] INJECTING: Mass SOS event surge (Triggering Edge Store-and-Forward)")
    for i in range(5):
        sos_event = {
            "event_id": str(uuid.uuid4()),
            "event_type": "incident.created",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "incident_type": "SOS",
            "actor_id": f"civilian_{i}",
            "hardware_lat": 28.5 + (i * 0.01),
            "hardware_lon": -80.6 + (i * 0.01),
            "message": "Storm surge flooding home!",
        }
        await js.publish("incident.created", json.dumps(sos_event).encode())
        print(f"    -> Emitted Civilian SOS {i+1}")
        
    print("\n[*] SIMULATION COMPLETE: Events published to NATS Mesh.")
    print("    -> PHOENIX EDGE will process CRDT logic.")
    print("    -> ATLAS GEO will calculate Haversine routes.")
    print("    -> Human Dispatcher will receive final Policy Recheck prompts.")
    
    await nc.close()

if __name__ == "__main__":
    asyncio.run(run_disaster_scenario())
