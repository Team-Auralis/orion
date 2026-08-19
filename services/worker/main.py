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

from database import Incident, IdempotencyKey

# CRDT State Hierarchy (Max-State CRDT)
STATE_HIERARCHY = {
    "CREATED": 0,
    "REPORTED": 1,
    "TRIAGED": 2,
    "DISPATCHING": 3,
    "EVACUATING": 4,
    "RESOLVED": 5
}

# In-memory deduplication scaffold
processed_events = set()

async def message_handler(msg):
    subject = msg.subject
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
        
        with Session(engine) as db:
            incident_id = event.get("incident_id")
            incident = db.query(Incident).filter(Incident.id == incident_id).first()
            
            if event_type == "incident.created":
                if not incident:
                    # The API failed to write to DB during Degraded Mode, so we must insert it
                    new_inc = Incident(
                        id=incident_id,
                        type=event.get("incident_type"),
                        user_id=event.get("actor_id"),
                        latitude=0.0, # Simplified for demo, would normally extract from event
                        longitude=0.0,
                        message="Recovered via CRDT Sync Engine",
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
        
        processed_events.add(event_id)
        await msg.ack()
        
    except Exception as e:
        print(f"Worker Error: {e}")
        # Not acking message so it gets redelivered

async def main():
    nats_url = os.environ.get("NATS_URL", "nats://localhost:4222")
    nc = nats.NATS()
    
    try:
        await nc.connect(nats_url)
        print(f"Connected to NATS at {nats_url}")
    except Exception as e:
        print(f"Error connecting to NATS: {e}")
        return

    # Initialize JetStream
    js = nc.jetstream()
    
    # Create stream if it doesn't exist
    try:
        await js.add_stream(name="incidents", subjects=["incident.*"])
        print("JetStream 'incidents' stream initialized.")
    except Exception as e:
        print(f"Stream setup: {e}")

    # Subscribe via JetStream for guaranteed delivery
    sub = await js.subscribe("incident.*", cb=message_handler, durable="crdt_sync_engine")
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
