from apps.api.security import mask_pii
import uuid
import json
import os
import hashlib
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from fastapi import FastAPI, Depends, HTTPException, status, Header, Request
from pydantic import BaseModel, Field
import httpx
from sqlalchemy.orm import Session
import sqlalchemy
import sqlalchemy.exc
import nats

from apps.api.database import get_db, Incident, IdempotencyKey, OutboxEvent
from apps.api.pilot import enforce_pilot_constraints, suspend_pilot as pilot_suspend, resume_pilot as pilot_resume, pilot_status

from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.propagate import inject
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.requests import Request

# OpenTelemetry Setup
resource = Resource.create({"service.name": "orion-api"})
trace.set_tracer_provider(TracerProvider(resource=resource))
otlp_exporter = OTLPSpanExporter(endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"), insecure=True)
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(otlp_exporter))

def get_real_ip(request: Request) -> str:
    # Strictly trust X-Real-IP from Nginx edge proxy
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "127.0.0.1"

limiter = Limiter(key_func=get_real_ip, enabled=True)

app = FastAPI(title="ORION API", version="0.1")
Instrumentator().instrument(app).expose(app)
FastAPIInstrumentor.instrument_app(app)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("NEXT_PUBLIC_API_URL", "http://localhost:3000")],
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

async def outbox_publisher_loop():
    while True:
        try:
            if nc.is_connected:
                db = SessionLocal()
                try:
                    events = db.query(OutboxEvent).filter(OutboxEvent.published == False).limit(100).all()
                    for ev in events:
                        headers = json.loads(ev.headers) if ev.headers else {}
                        await nc.publish(ev.topic, ev.payload.encode(), headers=headers)
                        ev.published = True
                    if events:
                        db.commit()
                finally:
                    db.close()
        except Exception as e:
            print(f"Outbox publisher error: {e}")
        await asyncio.sleep(1)

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
        
    asyncio.create_task(outbox_publisher_loop())

@app.on_event("shutdown")
async def shutdown_event():
    if nc.is_connected:
        await nc.close()

# --- Models ---
class Location(BaseModel):
    latitude: float
    longitude: float

    model_config = {"allow_inf_nan": False}

class IncidentCreate(BaseModel):
    type: str
    location: Location
    message: str = Field(..., max_length=1000)
    source: str

class IncidentResponse(BaseModel):
    incident_id: str
    status: str
    created_at: str

class RecommendationResponse(BaseModel):
    id: str
    incident_id: str
    recommended_asset_id: str
    reason: str
    status: str
    created_at: str

class RecommendationAction(BaseModel):
    action: str

class AssetStatusUpdate(BaseModel):
    status: str # IDLE, EN_ROUTE, ON_SCENE, RETURNING, OFFLINE, MAINTENANCE
    latitude: Optional[float] = None
    longitude: Optional[float] = None


import jwt
import httpx
import os
import hashlib

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
        if redis_client:
            try:
                redis_client.delete("circuit_failures:KEYCLOAK")
            except Exception:
                pass
        JWKS_CACHE = resp.json()
        JWKS_CACHE_TIME = time.time()
        return JWKS_CACHE
    except Exception as e:
        if redis_client:
            try:
                failures = redis_client.incr("circuit_failures:KEYCLOAK")
                if failures >= 5:
                    redis_client.setex("circuit_open:KEYCLOAK", 30, "1")
            except Exception:
                pass
        print(f"Failed to fetch JWKS: {e}")
        return JWKS_CACHE or {}

async def get_current_user(request: Request) -> Dict[str, Any]:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        if request.url.path == "/v1/incidents" and request.method == "POST":
            return {"subject": "civilian", "role": "citizen"}
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
            audience=os.environ.get("JWT_AUDIENCE", "account"),
            issuer=os.environ.get("JWT_ISSUER", "http://localhost:8080/realms/orion")
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
from apps.api.database import SessionLocal, OutboxEvent
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
    try:
        return redis_client.get(f"circuit_open:{service_name}") == "1"
    except Exception:
        return False

def trip_circuit(service_name: str, duration: int = 30):
    if redis_client:
        redis_client.setex(f"circuit_open:{service_name}", duration, "1")
        print(f"[CIRCUIT BREAKER] {service_name} Tripped. Opening for {duration} seconds.")

def check_policy(action: str, resource: str, resource_attributes: Dict[str, Any] = None):
    async def dependency(request: Request, user: Dict[str, Any] = Depends(get_current_user), db: Session = Depends(get_db)):
        
        # 1. Break-Glass Override Check
        bg_token = request.headers.get("X-Break-Glass-Token")
        if bg_token:
            from apps.api.database import BreakGlassSession
            from datetime import timedelta
            session = db.query(BreakGlassSession).filter(
                BreakGlassSession.token == hashlib.sha256(bg_token.encode()).hexdigest(),
                BreakGlassSession.user_id == user["subject"]
            ).first()
            if session:
                expires_at = session.expires_at.replace(tzinfo=timezone.utc) if session.expires_at.tzinfo is None else session.expires_at
                if expires_at > datetime.now(timezone.utc):
                    print(f"[BREAK-GLASS] Bypassing OPA for user {user['subject']}")
                    return user
                else:
                    raise HTTPException(status_code=403, detail="Break-glass token has expired.")
            else:
                raise HTTPException(status_code=403, detail="Invalid break-glass token or identity mismatch.")
        
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
            import traceback; traceback.print_exc()
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
    enforce_pilot_constraints(incident.location.latitude, incident.location.longitude)
    incident.message = mask_pii(incident.message)
    response_data = {
        "incident_id": f"INC-{uuid.uuid4().hex[:8].upper()}",
        "status": "CREATED",
        "created_at": datetime.now(timezone.utc).isoformat()
    }

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
    headers = {}
    inject(headers)

    db_is_online = True
    try:
        # 1. Idempotency Check
        namespaced_key = f"{user['subject']}:{idempotency_key}" if idempotency_key else None
        if namespaced_key:
            try:
                cached = db.query(IdempotencyKey).filter(IdempotencyKey.key == namespaced_key).first()
                if cached:
                    return json.loads(cached.response_body)
            except Exception as ex:
                print(f"Idempotency cache lookup error: {ex}")
                pass

        # 2. State Mutation
        dt_created = datetime.fromisoformat(response_data["created_at"])
        new_incident = Incident(
            id=response_data["incident_id"],
            type=incident.type,
            user_id=user["subject"],
            latitude=incident.location.latitude,
            longitude=incident.location.longitude,
            message=incident.message,
            created_at=dt_created,
            updated_at=dt_created
        )
        db.add(new_incident)

        # 3. Cache Idempotency
        if namespaced_key:
            db.add(IdempotencyKey(key=namespaced_key, response_body=json.dumps(response_data)))

        # 4. Outbox Event
        outbox_event = OutboxEvent(
            id=event["event_id"],
            topic="incident.created",
            payload=json.dumps(event),
            headers=json.dumps(headers)
        )
        db.add(outbox_event)

        db.commit()
    except sqlalchemy.exc.IntegrityError as e:
        db.rollback()
        if namespaced_key:
            try:
                cached = db.query(IdempotencyKey).filter(IdempotencyKey.key == namespaced_key).first()
                if cached:
                    return json.loads(cached.response_body)
            except Exception as ex:
                print(f"Idempotency cache lookup error: {ex}")
                pass
        raise HTTPException(status_code=409, detail="Conflict")
    except sqlalchemy.exc.OperationalError as e:
        # PHOENIX FALLBACK
        db.rollback()
        db_is_online = False
        print(f"DATABASE OFFLINE. Triggering NATS Fallback: {e}")
        response_data["status"] = "ACCEPTED_DEGRADED_MODE"
        
        # If DB is offline, we MUST rely on NATS.
        if nc.is_connected:
            await nc.publish("incident.created", json.dumps(event).encode(), headers=headers)
        else:
            # BOTH DB AND NATS ARE OFFLINE. DO NOT RETURN 202 ACCEPTED.
            raise HTTPException(status_code=503, detail="CRITICAL: Storage and Message Bus are both unreachable. Cannot safely store SOS signal.")
        
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
    
    # R-03: Route status updates through the outbox
    outbox_event = OutboxEvent(
        id=event["event_id"],
        topic="incident.status_changed",
        payload=json.dumps(event),
        headers=json.dumps({"X-Correlation-ID": f"req-{uuid.uuid4().hex[:6]}"})
    )
    db.add(outbox_event)
    db.commit()
    return {"message": "Status update event accepted", "event_id": event["event_id"]}

@app.post("/v1/auth/break-glass")
@limiter.limit("1/minute")
async def break_glass_override(request: Request, justification: dict, db: Session = Depends(get_db), user: Dict[str, Any] = Depends(get_current_user)):
    # This endpoint allows an operator to temporarily bypass standard capability checks 
    # to perform high-impact rescue operations during a catastrophic failure where OPA is down.
    
    # Equivalent privileged authorization (since OPA might be down, we check identity role directly)
    if user.get("role") not in ("operator", "admin") and "operator" not in user.get("roles", []) and "admin" not in user.get("roles", []):
        raise HTTPException(status_code=403, detail="Unauthorized. Only emergency operators may activate break-glass.")
        
    reason = justification.get("reason")
    if not reason or len(reason) < 20:
        raise HTTPException(status_code=400, detail="Must provide explicit, detailed reason for override.")
        
    user_id = user.get("subject", "unknown")
    user_role = user.get("role", "unknown")

    # 2. Issue a short-lived (15 min) elevated context token (simulated here)
    import secrets
    override_token = f"BREAK_GLASS_{secrets.token_hex(16)}"
    
    # Write to DB
    from apps.api.database import BreakGlassSession
    from datetime import timedelta
    bg_session = BreakGlassSession(
        token=hashlib.sha256(override_token.encode()).hexdigest(),
        user_id=user_id,
        reason=reason,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15)
    )
    db.add(bg_session)
    db.commit()
    
    
    token_hash = hashlib.sha256(override_token.encode()).hexdigest()
    
    # 3. Immutably log the override to the audit trail
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": "BREAK_GLASS_ACTIVATED",
        "actor_ip": request.client.host,
        "reason": reason,
        "token_hash": token_hash,
        "user_id": user_id,
        "user_role": user_role
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

# --- P1.5-016: Controlled Pilot Constraints ---

class PilotAction(BaseModel):
    reason: str

@app.get("/v1/pilot/status")
async def get_pilot_status(
    user: Dict[str, Any] = Depends(check_policy(action="pilot:status", resource="pilot"))
):
    return pilot_status()

@app.post("/v1/pilot/suspend")
async def suspend_pilot_endpoint(
    request: Request,
    action: PilotAction,
    user: Dict[str, Any] = Depends(check_policy(action="pilot:suspend", resource="pilot"))
):
    if not action.reason or len(action.reason) < 20:
        raise HTTPException(status_code=400, detail="Must provide an explicit, detailed suspension reason.")
    pilot_suspend(user["subject"], action.reason)
    print(f"[PILOT] Suspended by {user['subject']}: {action.reason}")
    return {"status": "suspended", "reason": action.reason}

@app.post("/v1/pilot/resume")
async def resume_pilot_endpoint(
    user: Dict[str, Any] = Depends(check_policy(action="pilot:resume", resource="pilot"))
):
    pilot_resume(user["subject"])
    print(f"[PILOT] Resumed by {user['subject']}")
    return {"status": "active"}

from apps.api.database import Asset

@app.get("/v1/assets")
async def list_assets(
    user: Dict[str, Any] = Depends(check_policy(action="dashboard:view", resource="assets")),
    db: Session = Depends(get_db)
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

@app.get("/v1/dispatch/recommendations", response_model=List[RecommendationResponse])
async def get_recommendations(
    user: Dict[str, Any] = Depends(check_policy(action="dispatch:read", resource="dispatch_recommendation")),
    db: Session = Depends(get_db)
):
    from apps.api.database import DispatchRecommendation
    recs = db.query(DispatchRecommendation).filter(DispatchRecommendation.status == "PENDING").all()
    return [{
        "id": r.id,
        "incident_id": r.incident_id,
        "recommended_asset_id": r.recommended_asset_id,
        "reason": r.reason,
        "status": r.status,
        "created_at": r.created_at.isoformat()
    } for r in recs]

@app.post("/v1/dispatch/recommendations/{rec_id}/action")
async def action_recommendation(
    rec_id: str,
    action_req: RecommendationAction,
    user: Dict[str, Any] = Depends(check_policy(action="dispatch:action", resource="dispatch_recommendation")),
    db: Session = Depends(get_db)
):
    from apps.api.database import DispatchRecommendation, Asset, OutboxEvent
    from sqlalchemy.orm.exc import StaleDataError
    from apps.api.pilot import enforce_pilot_active

    # Kill Switch Check
    enforce_pilot_active()

    rec = db.query(DispatchRecommendation).filter(DispatchRecommendation.id == rec_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    
    if rec.status != "PENDING":
        raise HTTPException(status_code=400, detail="Recommendation is already processed")
        
    # Check expiry (10 minutes)
    created_at = rec.created_at.replace(tzinfo=timezone.utc) if rec.created_at.tzinfo is None else rec.created_at
    time_diff = (datetime.now(timezone.utc) - created_at).total_seconds()
    if time_diff > 600:
        rec.status = "EXPIRED"
        rec.resolved_by = "SYSTEM"
        rec.resolved_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(status_code=400, detail="Recommendation expired. State may have changed.")
        
    action = action_req.action.upper()
    try:
        if action == "APPROVE":
            rec.status = "APPROVED"
            rec.resolved_by = user.get("subject", "unknown")
            rec.resolved_at = datetime.now(timezone.utc)
            
            asset = db.query(Asset).filter(Asset.asset_id == rec.recommended_asset_id).first()
            if asset and asset.status == "IDLE":
                asset.target_incident_id = rec.incident_id
                asset.status = "DISPATCHED"
                
                # Emit asset dispatched event
                event = {
                    "event_id": f"evt-{uuid.uuid4()}",
                    "event_type": "asset.dispatched",
                    "asset_id": asset.asset_id,
                    "incident_id": rec.incident_id,
                    "actor_id": user.get("subject", "unknown"),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                db.add(OutboxEvent(id=event["event_id"], topic="asset.dispatched", payload=json.dumps(event)))
            else:
                raise HTTPException(status_code=400, detail="Asset is no longer IDLE.")
        elif action == "REJECT":
            rec.status = "REJECTED"
            rec.resolved_by = user.get("subject", "unknown")
            rec.resolved_at = datetime.now(timezone.utc)
        else:
            raise HTTPException(status_code=400, detail="Invalid action. Must be APPROVE or REJECT")
            
        db.commit()
        return {"status": "success", "recommendation_status": rec.status}
    except StaleDataError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Concurrency conflict. Recommendation or Asset was modified.")

@app.put("/v1/assets/{asset_id}/status")
async def update_asset_status(
    asset_id: str,
    update: AssetStatusUpdate,
    user: Dict[str, Any] = Depends(check_policy(action="asset:update", resource="asset")),
    db: Session = Depends(get_db)
):
    from apps.api.database import Asset, OutboxEvent
    from sqlalchemy.orm.exc import StaleDataError
    import uuid
    import json
    
    asset = db.query(Asset).filter(Asset.asset_id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
        
    new_status = update.status.upper()
    valid_states = {"OFFLINE", "IDLE", "EN_ROUTE", "ON_SCENE", "RETURNING", "MAINTENANCE"}
    if new_status not in valid_states:
        raise HTTPException(status_code=400, detail=f"Invalid state. Must be one of {valid_states}")
        
    try:
        asset.status = new_status
        if update.latitude is not None:
            asset.latitude = update.latitude
        if update.longitude is not None:
            asset.longitude = update.longitude
            
        if new_status in ("IDLE", "OFFLINE", "MAINTENANCE"):
            asset.target_incident_id = None # Clear current target if any
            
        # Emit state change event for CRDT mesh/clients
        event = {
            "event_id": f"evt-{uuid.uuid4()}",
            "event_type": "asset.status_changed",
            "asset_id": asset.asset_id,
            "new_status": new_status,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        db.add(OutboxEvent(id=event["event_id"], topic="asset.status", payload=json.dumps(event)))
        
        db.commit()
        return {"status": "success", "asset_id": asset.asset_id, "new_status": new_status}
    except StaleDataError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Concurrency conflict. The asset state was modified by another transaction.")




