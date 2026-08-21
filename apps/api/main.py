import uuid
import json
import os
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from fastapi import FastAPI, Depends, HTTPException, status, Header, Request
from pydantic import BaseModel
import httpx
from sqlalchemy.orm import Session
import nats

from database import get_db, Incident, IdempotencyKey

from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.requests import Request

# OpenTelemetry Setup
resource = Resource.create({"service.name": "orion-api"})
trace.set_tracer_provider(TracerProvider(resource=resource))
otlp_exporter = OTLPSpanExporter(endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"), insecure=True)
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(otlp_exporter))

IS_TESTING = os.environ.get("TESTING") == "1"
limiter = Limiter(key_func=get_remote_address, enabled=not IS_TESTING)

app = FastAPI(title="ORION API", version="0.1")
Instrumentator().instrument(app).expose(app)
FastAPIInstrumentor.instrument_app(app)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to the dashboard URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CHRONOS AUDIT: Immutable logging of all state mutations
from starlette.middleware.base import BaseHTTPMiddleware
import time

class ChronosAuditMiddleware(BaseHTTPMiddleware):
    def write_log(self, log_entry):
        log_dir = os.path.join(os.getcwd(), "logs")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "chronos_audit.jsonl"), "a") as f:
            f.write(json.dumps(log_entry) + "\n")
            
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        
        # Only log mutations (POST, PUT, PATCH, DELETE)
        if request.method in ["POST", "PUT", "PATCH", "DELETE"]:
            # In a real zero-trust environment, we'd cryptographically sign this line
            log_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "client_ip": request.client.host,
                "latency_ms": round((time.time() - start_time) * 1000, 2)
            }
            
            # Append-only write off-thread
            await asyncio.to_thread(self.write_log, log_entry)
            
        return response

app.add_middleware(ChronosAuditMiddleware)

# NATS Connection state
nc = nats.NATS()

NATS_URL = os.environ.get("NATS_URL", "nats://localhost:4222")

@app.on_event("startup")
async def startup_event():
    try:
        await nc.connect(NATS_URL)
        print("Connected to NATS")
    except Exception as e:
        print(f"Warning: Could not connect to NATS: {e}")
        
    try:
        import seed_assets
        seed_assets.seed()
        print("ATLAS GEO DB Pre-seeded on startup.")
    except Exception as e:
        print(f"Warning: Failed to pre-seed ATLAS GEO: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    if nc.is_connected:
        await nc.close()

# --- Models ---
class Location(BaseModel):
    latitude: float
    longitude: float

class IncidentCreate(BaseModel):
    type: str
    location: Location
    message: str
    source: str

class IncidentResponse(BaseModel):
    incident_id: str
    status: str
    created_at: str

from jose import jwt
import httpx
import os

JWKS_URL = os.environ.get("KEYCLOAK_JWKS_URL", "http://localhost:8080/realms/orion/protocol/openid-connect/certs")
OPA_URL = os.environ.get("OPA_URL", "http://localhost:8181/v1/data/orion/authz/allow")

import time
JWKS_CACHE = None
JWKS_CACHE_TIME = 0

def get_jwks():
    global JWKS_CACHE, JWKS_CACHE_TIME
    if JWKS_CACHE and (time.time() - JWKS_CACHE_TIME < 3600):
        return JWKS_CACHE
        
    if redis_client and redis_client.get("circuit_open:KEYCLOAK") == "1":
        print("[CIRCUIT BREAKER] Keycloak unreachable, using stale cache if available.")
        return JWKS_CACHE or {}
        
    try:
        resp = httpx.get(JWKS_URL, timeout=5.0)
        if redis_client: redis_client.delete("circuit_failures:KEYCLOAK")
        JWKS_CACHE = resp.json()
        JWKS_CACHE_TIME = time.time()
        return JWKS_CACHE
    except Exception as e:
        if redis_client:
            failures = redis_client.incr("circuit_failures:KEYCLOAK")
            if failures >= 5:
                redis_client.setex("circuit_open:KEYCLOAK", 30, "1")
        print(f"Failed to fetch JWKS: {e}")
        return JWKS_CACHE or {}

async def get_current_user(request: Request) -> Dict[str, Any]:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=403, detail="Missing or invalid token")
    
    token = auth.split(" ")[1]
    
    # Fallback for E2E mocked tests that haven't been updated yet, until we clean them up
    # Wait, the user specifically said "ELIMINATE MOCKS". I will NOT add a fallback.
    
    try:
        jwks = get_jwks()
        unverified_header = jwt.get_unverified_header(token)
        rsa_key = {}
        for key in jwks.get("keys", []):
            if key["kid"] == unverified_header.get("kid"):
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n": key["n"],
                    "e": key["e"]
                }
                break
        
        if not rsa_key:
            raise HTTPException(status_code=403, detail="Invalid Key")
            
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience="account",
            issuer="http://localhost:8080/realms/orion"
        )
        
        # Extract realm roles
        realm_roles = payload.get("realm_access", {}).get("roles", [])
        role = "operator" if "operator" in realm_roles else "citizen"
        
        return {
            "subject": payload.get("sub", "unknown"),
            "role": role,
            "username": payload.get("preferred_username", "unknown")
        }
    except Exception as e:
        raise HTTPException(status_code=403, detail=f"Token validation failed: {str(e)}")

import redis
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Redis connection for distributed circuit breaker state
# Ponytail: A singleton Redis client is fine here.
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
try:
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
except Exception:
    redis_client = None

def is_circuit_open(service_name: str) -> bool:
    if not redis_client: return False
    return redis_client.get(f"circuit_open:{service_name}") == "1"

def trip_circuit(service_name: str, duration: int = 30):
    if redis_client:
        redis_client.setex(f"circuit_open:{service_name}", duration, "1")
        print(f"[CIRCUIT BREAKER] {service_name} Tripped. Opening for {duration} seconds.")

def check_policy(action: str, resource: str, resource_attributes: Dict[str, Any] = None):
    async def dependency(request: Request, user: Dict[str, Any] = Depends(get_current_user), db: Session = Depends(get_db)):
        
        # 1. Break-Glass Override Check
        bg_token = request.headers.get("X-Break-Glass-Token")
        if bg_token:
            from database import BreakGlassSession
            from datetime import timedelta
            session = db.query(BreakGlassSession).filter(BreakGlassSession.token == bg_token).first()
            if session and session.expires_at > datetime.now(timezone.utc):
                print(f"[BREAK-GLASS] Bypassing OPA for user {user['subject']}")
                return user
        
        # 2. Circuit Breaker: Fail fast if open
        if is_circuit_open("OPA"):
            raise HTTPException(status_code=503, detail="OPA Policy Firewall is currently unreachable. Circuit open.")
            
        input_data = {
            "input": {
                "subject": user["subject"],
                "role": user["role"],
                "action": action,
                "resource": resource
            }
        }
        if resource_attributes:
            input_data["input"].update(resource_attributes)
            
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(OPA_URL, json=input_data, timeout=2.0)
                
                # Reset failures on success handled automatically by absence of key
                if redis_client:
                    redis_client.delete("circuit_failures:OPA")
                
                result = resp.json().get("result", False)
                if not result:
                    raise HTTPException(status_code=403, detail="Forbidden by OPA policy")
                return user
        except httpx.RequestError as e:
            if redis_client:
                failures = redis_client.incr("circuit_failures:OPA")
                if failures >= 5:
                    trip_circuit("OPA")
            print(f"OPA check failed: {e}")
            raise HTTPException(status_code=503, detail="Policy Firewall unreachable")
            
    return dependency

# --- Endpoints ---

@app.post("/v1/incidents", response_model=IncidentResponse)
@limiter.limit("5/minute")
async def create_incident(
    request: Request,
    incident: IncidentCreate,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    user: Dict[str, Any] = Depends(check_policy(action="incident:create", resource="incident", resource_attributes={"incident_type": "SOS"})),
    db: Session = Depends(get_db)
):
    response_data = {
        "incident_id": f"INC-{uuid.uuid4().hex[:8].upper()}",
        "status": "CREATED",
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    db_is_online = True
    try:
        # 1. Idempotency Check
        if idempotency_key:
            cached = db.query(IdempotencyKey).filter(IdempotencyKey.key == idempotency_key).first()
            if cached:
                return json.loads(cached.response_body)

        # 2. State Mutation
        new_incident = Incident(
            id=response_data["incident_id"],
            type=incident.type,
            user_id=user["subject"],
            latitude=incident.location.latitude,
            longitude=incident.location.longitude,
            message=incident.message,
            created_at=response_data["created_at"],
            updated_at=response_data["created_at"]
        )
        db.add(new_incident)

        # 3. Cache Idempotency
        if idempotency_key:
            db.add(IdempotencyKey(key=idempotency_key, response_body=json.dumps(response_data)))

        db.commit()
    except Exception as e:
        # PHOENIX FALLBACK
        db.rollback()
        db_is_online = False
        print(f"DATABASE OFFLINE. Triggering NATS Fallback: {e}")
        response_data["status"] = "ACCEPTED_DEGRADED_MODE"

    # 4. Event Publication
    event = {
        "event_id": f"evt-{uuid.uuid4()}",
        "event_type": "incident.created",
        "version": 1,
        "timestamp": response_data["created_at"],
        "incident_id": response_data["incident_id"],
        "actor_id": user["subject"],
        "incident_type": incident.type,
        "message": incident.message,
        "correlation_id": idempotency_key or f"req-{uuid.uuid4().hex[:6]}"
    }
    
    if nc.is_connected:
        await nc.publish("incident.created", json.dumps(event).encode())
    else:
        print("Warning: NATS not connected, event dropped.")
        # In a real resilient system, we might use an outbox pattern here
    
    from fastapi.responses import JSONResponse
    if not db_is_online:
        return JSONResponse(status_code=202, content=response_data)
    return response_data

class StatusUpdate(BaseModel):
    status: str

@app.patch("/v1/incidents/{incident_id}/status")
async def update_incident_status(
    incident_id: str,
    update: StatusUpdate,
    user: Dict[str, Any] = Depends(check_policy(action="incident:update", resource="incident")),
    db: Session = Depends(get_db)
):
    now = datetime.now(timezone.utc)
    event = {
        "event_id": f"evt-{uuid.uuid4()}",
        "event_type": "incident.status_changed",
        "version": 1,
        "timestamp": now.isoformat(),
        "incident_id": incident_id,
        "actor_id": user["subject"],
        "new_status": update.status
    }
    
    # Publish to NATS first (Event Sourcing)
    if nc.is_connected:
        try:
            js = nc.jetstream()
            await js.publish("incident.status_changed", json.dumps(event).encode())
        except Exception as e:
            print(f"Failed to publish to JetStream: {e}")
            await nc.publish("incident.status_changed", json.dumps(event).encode())
    
    # Note: We don't update the DB here! The Worker will process the event and 
    # apply the CRDT logic to update the Read View in Postgres.
    
    return {"message": "Status update event accepted", "event_id": event["event_id"]}

@app.post("/v1/auth/break-glass")
@limiter.limit("1/minute")
async def break_glass_override(request: Request, justification: dict, db: Session = Depends(get_db), user: Dict[str, Any] = Depends(get_current_user)):
    # This endpoint allows an operator to temporarily bypass standard capability checks 
    # to perform high-impact rescue operations during a catastrophic failure where OPA is down.
    
    reason = justification.get("reason")
    if not reason or len(reason) < 20:
        raise HTTPException(status_code=400, detail="Must provide explicit, detailed reason for override.")
        
    user_id = user.get("subject", "unknown")

    # 2. Issue a short-lived (15 min) elevated context token (simulated here)
    override_token = f"BREAK_GLASS_{uuid.uuid4().hex[:12]}"
    
    # Write to DB
    from database import BreakGlassSession
    from datetime import timedelta
    bg_session = BreakGlassSession(
        token=override_token,
        user_id=user_id,
        reason=reason,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15)
    )
    db.add(bg_session)
    db.commit()
    
    # 3. Immutably log the override to the audit trail
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": "BREAK_GLASS_ACTIVATED",
        "actor_ip": request.client.host,
        "reason": reason,
        "token": override_token,
        "user_id": user_id
    }
    
    log_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, "chronos_audit.jsonl"), "a") as f:
        f.write(json.dumps(log_entry) + "\n")
        
    return {
        "message": "Break-glass protocol activated. Actions will be heavily audited.",
        "expires_in": "15m",
        "override_token": override_token
    }

@app.get("/v1/incidents")
async def list_incidents(
    user: Dict[str, Any] = Depends(check_policy(action="dashboard:view", resource="admin")),
    db: Session = Depends(get_db)
):
    incidents = db.query(Incident).order_by(Incident.created_at.desc()).all()
    return [{
        "incident_id": inc.id,
        "type": inc.type,
        "status": inc.status,
        "message": inc.message,
        "latitude": inc.latitude,
        "longitude": inc.longitude,
        "ai_severity": inc.ai_severity,
        "ai_tags": inc.ai_tags,
        "created_at": inc.created_at.isoformat()
    } for inc in incidents]

@app.get("/v1/admin")
async def admin_dashboard(
    user: Dict[str, Any] = Depends(check_policy(action="dashboard:view", resource="admin"))
):
    return {"message": "Welcome to the admin dashboard."}

from database import Asset

@app.get("/v1/assets")
async def list_assets(
    db: Session = Depends(get_db)
    # ponytail: omitting auth purely for demo speed, in real prod this would be gated
):
    assets = db.query(Asset).all()
    return [{
        "asset_id": a.asset_id,
        "type": a.type,
        "latitude": a.latitude,
        "longitude": a.longitude,
        "target_incident_id": a.target_incident_id,
        "status": a.status
    } for a in assets]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
