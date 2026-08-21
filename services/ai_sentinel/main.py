import asyncio
import json
import os
import signal
import uuid
from datetime import datetime, timezone

import nats

import httpx

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

async def analyze_incident(message: str) -> dict:
    prompt = f"""
    You are an emergency response AI. Extract the severity and tags from the following message.
    Severity must be one of: LOW, MODERATE, HIGH, CRITICAL.
    Tags should be 1-3 keywords.
    Respond STRICTLY in JSON format.
    Message: {message}
    """
    
    try:
        # Strict timeout to prevent queue stalling
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": "qwen2:0.5b", "prompt": prompt, "stream": False},
                timeout=2.0
            )
        
        raw_output = resp.json().get("response", "{}")
        import re
        json_match = re.search(r'\{.*\}', raw_output, re.DOTALL)
        if json_match:
            raw_output = json_match.group(0)
            
        data = json.loads(raw_output)
        return {
            "severity": data.get("severity", "MODERATE"),
            "tags": data.get("tags", [])
        }
    except Exception as e:
        print(f"[!] AI Inference Failed/Timeout ({e}). Engaging Deterministic Fallback.")
        msg_upper = message.upper()
        severity = "MODERATE"
        tags = []
        if any(word in msg_upper for word in ["FIRE", "BURN", "SMOKE"]): tags.append("FIRE")
        if any(word in msg_upper for word in ["HEART", "BREATH", "BLEED", "HELP"]): tags.append("MEDICAL")
        if any(word in msg_upper for word in ["WATER", "FLOOD", "DROWN"]): tags.append("FLOODING")
        if "CRITICAL" in msg_upper or "DIE" in msg_upper or "URGENT" in msg_upper: severity = "CRITICAL"
        return {"severity": severity, "tags": tags}

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

NATS_URL = os.environ.get("NATS_URL", "nats://localhost:4222")

async def main():
    nc = nats.NATS()
    
    try:
        await nc.connect(NATS_URL)
        print(f"[SENTIENCE] Connected to NATS at {NATS_URL}")
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
