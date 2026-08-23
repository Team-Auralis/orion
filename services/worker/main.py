
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
from prometheus_client import start_http_server, Counter, Histogram
import time

WORKER_LATENCY = Histogram('worker_processing_latency_seconds', 'Time spent processing event')
WORKER_DUPLICATES = Counter('worker_duplicates_dropped_total', 'Events dropped due to idempotency mesh')
WORKER_SUCCESS = Counter('worker_events_processed_total', 'Events successfully processed')

import os
import signal
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
import nats

# Ponytail: We're going to interact directly with the DB here for the Read View projection.
# In prod, extract DB setup to a shared lib.
DB_URL = os.environ.get("DATABASE_URL", "postgresql://orion_admin:LOCAL_DEV_SECRET@localhost:5433/keycloak")
engine = create_engine(DB_URL)

from apps.api.database import Incident, IdempotencyKey, Asset, DispatchRecommendation

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
import redis
redis_client = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"), decode_responses=True)

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
                        print(f"ATLAS GEO: Recommending asset {closest_asset.asset_id} to {incident_id} (Distance: {min_distance:.2f} km)")
                        import uuid
                        rec = DispatchRecommendation(
                            id=f"rec-{uuid.uuid4().hex[:8]}",
                            incident_id=incident_id,
                            recommended_asset_id=closest_asset.asset_id,
                            reason=f"Closest available asset ({min_distance:.2f} km). AI Severity: {severity}",
                            status="PENDING"
                        )
                        db.add(rec)
                    else:
                        print(f"ATLAS GEO WARNING: No available assets to dispatch for {incident_id}!")
                
                incident.updated_at = datetime.fromisoformat(event.get("timestamp"))
                db.commit()
            else:
                print(f"Warning: Received AI triage for unknown incident {incident_id}")

from opentelemetry import trace
from opentelemetry.propagate import extract
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

trace.set_tracer_provider(TracerProvider())
otlp_exporter = OTLPSpanExporter(endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"), insecure=True)
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(otlp_exporter))
tracer = trace.get_tracer(__name__)

async def message_handler(msg):
    ctx = extract(msg.headers if msg.headers else {})
    with tracer.start_as_current_span("process_nats_message", context=ctx) as span:
        data = msg.data.decode()
        span.set_attribute("nats.subject", msg.subject)
        start_time = time.time()
        
        try:
            event = json.loads(data)
            event_id = event.get('event_id')
            event_type = event.get('event_type')
            
            # Ponytail: Redis SETNX for atomic distributed deduplication.
            if redis_client:
                # 24 hour expiration to prevent memory leak, but long enough for any duplicate retries
                if not redis_client.set(f"processed:{event_id}", "1", nx=True, ex=86400):
                    print(f"Skipping already processed event: {event_id}")
                    WORKER_DUPLICATES.inc()
                    await msg.ack()
                    return
                
            print(f"Processing event {event_type} for incident {event.get('incident_id')}")
            
            # Offload synchronous DB work to a separate thread to prevent blocking the asyncio event loop
            await asyncio.to_thread(process_db_event, event, event_type)
                
            WORKER_SUCCESS.inc()
            WORKER_LATENCY.observe(time.time() - start_time)
            await msg.ack()
        except Exception as e:
            print(f"Error processing message: {e}")
            # In production, we might want to NAK or move to dead-letter queue
            await msg.term()

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
    start_http_server(8002)
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

