import asyncio
import json
import os
import signal
import uuid
from datetime import datetime, timezone

import nats

async def analyze_incident(message: str) -> dict:
    """
    Simulated NLP AI Model. 
    In prod, this would call Ollama or Gemini to extract severity and tags.
    """
    message = message.lower()
    
    severity = "LOW"
    tags = ["GENERAL"]
    
    if "flood" in message or "water" in message:
        severity = "HIGH"
        tags = ["FLOODING", "WATER_RESCUE"]
    if "fire" in message or "smoke" in message:
        severity = "CRITICAL"
        tags = ["FIRE", "HAZMAT"]
    if "trapped" in message or "help" in message:
        severity = "CRITICAL"
        tags.append("RESCUE_REQUIRED")
        
    # Simulate AI processing delay
    await asyncio.sleep(1.0)
    
    return {
        "severity": severity,
        "tags": tags
    }

async def message_handler(msg):
    try:
        event = json.loads(msg.data.decode())
        if event.get("event_type") != "incident.created":
            await msg.ack()
            return
            
        incident_id = event.get("incident_id")
        print(f"[SENTIENCE] Intercepted new incident: {incident_id}")
        
        # 1. Run AI analysis
        analysis = await analyze_incident(event.get("message", ""))
        print(f"[SENTIENCE] AI Triage Complete -> Severity: {analysis['severity']}, Tags: {analysis['tags']}")
        
        # 2. Publish AI Triage Event back to the mesh
        nc = msg._client
        js = nc.jetstream()
        
        triage_event = {
            "event_id": f"evt-{uuid.uuid4()}",
            "event_type": "incident.ai_triaged",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "incident_id": incident_id,
            "ai_severity": analysis["severity"],
            "ai_tags": ",".join(analysis["tags"])
        }
        
        await js.publish("incident.ai_triaged", json.dumps(triage_event).encode())
        print(f"[SENTIENCE] Published incident.ai_triaged for {incident_id}")
        
        await msg.ack()
        
    except Exception as e:
        print(f"[SENTIENCE] Error processing message: {e}")

async def main():
    nats_url = os.environ.get("NATS_URL", "nats://localhost:4222")
    nc = nats.NATS()
    
    try:
        await nc.connect(nats_url)
        print(f"[SENTIENCE] Connected to NATS at {nats_url}")
    except Exception as e:
        print(f"Error connecting to NATS: {e}")
        return

    js = nc.jetstream()
    
    # We subscribe specifically to incident.created so the AI can analyze new SOS pings
    # using a consumer group so if we run multiple Sentience nodes, they load balance.
    sub = await js.subscribe("incident.created", cb=message_handler, durable="sentience_ai")
    print("[SENTIENCE] AI Orchestration Layer listening for new incidents...")

    stop_event = asyncio.Event()

    def signal_handler():
        print("Shutting down Sentience Worker...")
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
