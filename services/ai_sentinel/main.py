import asyncio
import json
import os
import signal
import uuid
from datetime import datetime, timezone
import nats
import httpx

# ── MODEL IDENTITY CONFIGURATION (NO AMBIGUITY) ──────────────────────────────
BASELINE_PRODUCTION_MODEL = "qwen2:0.5b"       # Real baseline loaded in Ollama
TARGET_RESEARCH_MODEL = "Qwen3.8-27B"         # Target architecture (Pending 4-bit weights)
FALLBACK_ENGINE_ID = "deterministic_regex_v1" # Hardcoded regex rule engine

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
CONFIGURED_MODEL = os.environ.get("ORION_AI_MODEL", BASELINE_PRODUCTION_MODEL)

async def check_ollama_model_availability(model_name: str) -> dict:
    """Check whether the configured model is physically present in Ollama."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{OLLAMA_URL}/api/tags")
            if resp.status_code == 200:
                models = [m.get("name") for m in resp.json().get("models", [])]
                is_available = any(model_name in m for m in models)
                return {
                    "reachable": True,
                    "model_found": is_available,
                    "available_models": models,
                    "status": "AVAILABLE" if is_available else "MODEL_NOT_FOUND"
                }
    except Exception as e:
        return {
            "reachable": False,
            "model_found": False,
            "available_models": [],
            "status": f"UNREACHABLE ({type(e).__name__})"
        }
    return {"reachable": False, "model_found": False, "available_models": [], "status": "UNKNOWN"}

async def analyze_incident(message: str) -> dict:
    """
    Triage incident messages.
    If the primary model fails or times out, engages deterministic fallback
    and EXPOSES explicit fallback telemetry (NO SILENT FALLBACK).
    """
    prompt = f"""
    You are an emergency response AI. Extract the severity and tags from the following message.
    Severity must be one of: LOW, MODERATE, HIGH, CRITICAL.
    Tags should be 1-3 keywords.
    Respond STRICTLY in JSON format.
    Message: {message}
    """
    
    primary_status = "UNKNOWN"
    fallback_reason = None
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": CONFIGURED_MODEL, "prompt": prompt, "stream": False},
                timeout=2.0
            )
        
        if resp.status_code == 200:
            raw_output = resp.json().get("response", "{}")
            import re
            json_match = re.search(r'\{.*\}', raw_output, re.DOTALL)
            if json_match:
                raw_output = json_match.group(0)
                
            data = json.loads(raw_output)
            return {
                "severity": data.get("severity", "MODERATE"),
                "tags": data.get("tags", []),
                "model_used": CONFIGURED_MODEL,
                "model_role": "PRODUCTION_BASELINE",
                "fallback_active": False,
                "fallback_reason": None,
                "primary_model_status": "ONLINE"
            }
        else:
            fallback_reason = f"HTTP {resp.status_code}: {resp.text[:100]}"
            primary_status = f"HTTP_ERROR_{resp.status_code}"
    except httpx.TimeoutException:
        fallback_reason = "Inference request timed out (>2.0s)"
        primary_status = "TIMEOUT"
    except Exception as e:
        fallback_reason = f"Connection error: {type(e).__name__} ({str(e)})"
        primary_status = "OFFLINE"

    # --- EXPLICIT DETERMINISTIC FALLBACK (TELEMETRY PRESERVED) ---
    print(f"[!] Primary Model ({CONFIGURED_MODEL}) Failed: {primary_status}. Reason: {fallback_reason}. Engaging Fallback.")
    msg_upper = message.upper()
    severity = "MODERATE"
    tags = []
    if any(word in msg_upper for word in ["FIRE", "BURN", "SMOKE"]): tags.append("FIRE")
    if any(word in msg_upper for word in ["HEART", "BREATH", "BLEED", "HELP"]): tags.append("MEDICAL")
    if any(word in msg_upper for word in ["WATER", "FLOOD", "DROWN"]): tags.append("FLOODING")
    if "CRITICAL" in msg_upper or "DIE" in msg_upper or "URGENT" in msg_upper: severity = "CRITICAL"
    
    return {
        "severity": severity,
        "tags": tags,
        "model_used": FALLBACK_ENGINE_ID,
        "model_role": "DETERMINISTIC_FALLBACK",
        "fallback_active": True,
        "fallback_reason": fallback_reason,
        "primary_model_status": primary_status
    }

async def message_handler(msg):
    try:
        event = json.loads(msg.data.decode())
        if event.get("event_type") != "incident.created":
            await msg.ack()
            return
            
        incident_id = event.get("incident_id")
        print(f"[SENTIENCE] Intercepted new incident: {incident_id}")
        
        # 1. Run AI analysis with transparent fallback tracking
        analysis = await analyze_incident(event.get("message", ""))
        print(f"[SENTIENCE] Triage Complete -> Severity: {analysis['severity']}, Tags: {analysis['tags']} (Model: {analysis['model_used']}, Fallback: {analysis['fallback_active']})")
        
        # 2. Publish AI Triage Event back to the mesh
        nc = msg._client
        js = nc.jetstream()
        
        triage_event = {
            "event_id": f"evt-{uuid.uuid4()}",
            "event_type": "incident.ai_triaged",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "incident_id": incident_id,
            "ai_severity": analysis["severity"],
            "ai_tags": ",".join(analysis["tags"]),
            "ai_model": analysis["model_used"],
            "ai_model_role": analysis["model_role"],
            "fallback_active": analysis["fallback_active"],
            "fallback_reason": analysis["fallback_reason"],
            "primary_model_status": analysis["primary_model_status"]
        }
        
        await js.publish("incident.ai_triaged", json.dumps(triage_event).encode())
        print(f"[SENTIENCE] Published incident.ai_triaged for {incident_id}")
        
        await msg.ack()
        
    except Exception as e:
        print(f"[SENTIENCE] Error processing message: {e}")

NATS_URL = os.environ.get("NATS_URL", "nats://localhost:4222")

async def main():
    print("=" * 60)
    print("         ORION SENTIENCE AI SENTINEL SERVICE          ")
    print(f" Configured Production Model : {CONFIGURED_MODEL}")
    print(f" Target Research Model       : {TARGET_RESEARCH_MODEL} (UNINSTALLED)")
    print(f" Fallback Engine             : {FALLBACK_ENGINE_ID}")
    print("=" * 60)

    # Startup model check (Task G)
    print("\n[STARTUP] Performing primary model health check...")
    health = await check_ollama_model_availability(CONFIGURED_MODEL)
    if health["model_found"]:
        print(f"  [OK] Model '{CONFIGURED_MODEL}' is reachable and loaded in Ollama.")
    else:
        print(f"  [CRITICAL WARNING] Configured model '{CONFIGURED_MODEL}' status: {health['status']}.")
        print(f"  [ACTION] Fallback engine '{FALLBACK_ENGINE_ID}' will handle triage requests until Ollama is ready.")
        print(f"  [INFO] Available Ollama models: {health['available_models']}")

    nc = nats.NATS()
    
    try:
        await nc.connect(NATS_URL)
        print(f"\n[SENTIENCE] Connected to NATS at {NATS_URL}")
    except Exception as e:
        print(f"Error connecting to NATS: {e}")
        return

    js = nc.jetstream()
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
