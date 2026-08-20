import uuid
import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from fastapi import FastAPI, Depends, HTTPException, status, Header, Request
from pydantic import BaseModel
import httpx
from sqlalchemy.orm import Session
import nats

from database import get_db, Incident, IdempotencyKey

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="ORION API", version="0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to the dashboard URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

def get_jwks():
    try:
        resp = httpx.get(JWKS_URL, timeout=5.0)
        return resp.json()
    except Exception as e:
        print(f"Failed to fetch JWKS: {e}")
        return {}

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

def check_policy(action: str, resource: str, resource_attributes: Dict[str, Any] = None):
    async def dependency(user: Dict[str, Any] = Depends(get_current_user)):
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
            
        print(f"OPA Input: {input_data}")
        try:
            with httpx.Client() as client:
                resp = client.post(OPA_URL, json=input_data, timeout=2.0)
                print(f"OPA Output: {resp.json()}")
                if resp.status_code == 200 and resp.json().get("result") is True:
                    return user
        except Exception as e:
            print(f"OPA check failed: {e}")
            
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden by policy firewall"
        )
    return dependency

# --- Endpoints ---

@app.post("/v1/incidents", response_model=IncidentResponse)
async def create_incident(
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
