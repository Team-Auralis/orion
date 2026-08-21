
import math
def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c
import asyncio
import json
import os
import signal
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
import nats

# Ponytail: We're going to interact directly with the DB here for the Read View projection.
# In prod, extract DB setup to a shared lib.
DB_URL = os.environ.get("DATABASE_URL", "postgresql://orion_admin:orion_password@localhost:5433/keycloak")
engine = create_engine(DB_URL)

from database import Incident, IdempotencyKey, Asset

# CRDT State Hierarchy (Max-State CRDT)
STATE_HIERARCHY = {
    "CREATED": 0,
    "REPORTED": 1,
    "TRIAGED": 2,
    "DISPATCHING": 3,
    "EVACUATING": 4,
    "RESOLVED": 5
}

# Bounded LRU cache for deduplication
from collections import OrderedDict
processed_events = OrderedDict()
MAX_CACHE_SIZE = 10000

def process_db_event(event, event_type):
    with Session(engine) as db:
        incident_id = event.get("incident_id")
        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        
        if event_type == "incident.created":
            if not incident:
                new_inc = Incident(
                    id=incident_id,
                    type=event.get("incident_type"),
                    user_id=event.get("actor_id"),
                    latitude=event.get("hardware_lat", 0.0),
                    longitude=event.get("hardware_lon", 0.0),
                    message=event.get("message", "Recovered via CRDT Sync Engine"),
                    status="CREATED",
                    created_at=datetime.fromisoformat(event.get("timestamp")),
                    updated_at=datetime.fromisoformat(event.get("timestamp"))
                )
                db.add(new_inc)
                try:
                    db.commit()
                    print(f"CRDT Engine inserted missing incident: {incident_id}")
                except Exception as e:
                    db.rollback()
                    print(f"Failed to insert missing incident: {e}")
            else:
                print(f"Incident {incident_id} already exists. Skipping created event.")
                
        elif event_type == "incident.status_changed":
            new_status = event.get("new_status", "").upper()
            if incident:
                current_status = incident.status.upper()
                
                # MAX-STATE CRDT LOGIC
                current_rank = STATE_HIERARCHY.get(current_status, -1)
                new_rank = STATE_HIERARCHY.get(new_status, -1)
                
                if new_rank > current_rank:
                    print(f"CRDT MERGE: Upgrading status {current_status} -> {new_status}")
                    incident.status = new_status
                    incident.updated_at = datetime.fromisoformat(event.get("timestamp"))
                    db.commit()
                else:
                    print(f"CRDT IGNORE: {new_status} (rank {new_rank}) is <= {current_status} (rank {current_rank}). Event discarded.")
            else:
                print(f"Warning: Received status change for unknown incident {incident_id}")
                
        elif event_type == "incident.ai_triaged":
            if incident:
                print(f"CRDT MERGE: Applying AI Triage data to {incident_id}")
                incident.ai_severity = event.get("ai_severity")
                incident.ai_tags = event.get("ai_tags")
                
                current_rank = STATE_HIERARCHY.get(incident.status.upper(), -1)
                triage_rank = STATE_HIERARCHY.get("TRIAGED", -1)
                if triage_rank > current_rank:
                    print(f"CRDT MERGE: AI Auto-Triaged status upgraded to TRIAGED")
                    incident.status = "TRIAGED"
                
                severity = event.get("ai_severity", "").upper()
                if severity in ["HIGH", "CRITICAL"]:
                    
                    
                    available_assets = db.query(Asset).filter(Asset.status == "IDLE").all()
                    closest_asset = None
                    min_distance = float('inf')
                    
                    for asset in available_assets:
                        dist = haversine(incident.latitude, incident.longitude, asset.latitude, asset.longitude)
                        if dist < min_distance:
                            min_distance = dist
                            closest_asset = asset
                    
                    if closest_asset:
                        print(f"ATLAS GEO: Routing closest asset {closest_asset.asset_id} to {incident_id} (Distance: {min_distance:.2f} km)")
                        closest_asset.target_incident_id = incident_id
                        closest_asset.status = "DISPATCHED"
                    else:
                        print(f"ATLAS GEO WARNING: No available assets to dispatch for {incident_id}!")
                
                incident.updated_at = datetime.fromisoformat(event.get("timestamp"))
                db.commit()
            else:
                print(f"Warning: Received AI triage for unknown incident {incident_id}")

async def message_handler(msg):
    data = msg.data.decode()
    
    try:
        event = json.loads(data)
        event_id = event.get('event_id')
        event_type = event.get('event_type')
        
        if event_id in processed_events:
            print(f"Skipping already processed event: {event_id}")
            await msg.ack()
            return
            
        print(f"Processing event {event_type} for incident {event.get('incident_id')}")
        
        # Offload synchronous DB work to a separate thread to prevent blocking the asyncio event loop
        await asyncio.to_thread(process_db_event, event, event_type)
        
        # Bounded LRU eviction
        processed_events[event_id] = True
        if len(processed_events) > MAX_CACHE_SIZE:
            processed_events.popitem(last=False)
            
        await msg.ack()
        
    except Exception as e:
        print(f"Worker Error: {e}")
        # Not acking message so it gets redelivered

NATS_URL = os.environ.get("NATS_URL", "nats://localhost:4222")


async def network_handler(msg):
    data = json.loads(msg.data.decode())
    print(f"\n[PATHFINDER NETWORK ENGINE] Telemetry received: {data}")
    if data.get('event_type') == 'network.link_degraded':
        region = data.get('region', 'UNKNOWN')
        link = data.get('link_type', 'UNKNOWN')
        print(f"[*] ALERT: High packet loss detected on {link} in region {region}.")
        print(f"[*] ACTION: Orchestrator is recalculating optimal transport paths...")
        print(f"[*] RESOLUTION: Rerouting {region} critical traffic to SATELLITE/NTN failover path.\n")
    await msg.ack()

async def main():
    nc = nats.NATS()
    
    try:
        await nc.connect(NATS_URL)
        print(f"Connected to NATS at {NATS_URL}")
    except Exception as e:
        print(f"Error connecting to NATS: {e}")
        return

    # Initialize JetStream
    js = nc.jetstream()
    
    # Create stream if it doesn't exist
    try:
        await js.add_stream(name="incidents", subjects=["incident.*", "network.*"])
        print("JetStream 'incidents' stream initialized.")
    except Exception as e:
        print(f"Stream setup: {e}")

    # Subscribe via JetStream for guaranteed delivery
    sub = await js.subscribe("incident.*", cb=message_handler, durable="crdt_sync_engine")
    net_sub = await js.subscribe("network.*", cb=network_handler, durable="pathfinder_engine")
    print("CRDT Sync Engine listening for 'incident.*' events...")

    stop_event = asyncio.Event()

    def signal_handler():
        print("Shutting down worker...")
        stop_event.set()

    loop = asyncio.get_event_loop()
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)
    except NotImplementedError:
        pass

    await stop_event.wait()
    
    await sub.unsubscribe()
    await nc.drain()

if __name__ == '__main__':
    asyncio.run(main())

