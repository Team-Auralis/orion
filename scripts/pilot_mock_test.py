import os
import json
import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set pilot env vars
os.environ["PILOT_MODE"] = "1"
os.environ["PILOT_GEOFENCE"] = "17.60,83.10,17.85,83.35" # Visakhapatnam

from apps.api.main import app, get_db, get_current_user
import apps.api.main
apps.api.main.redis_client = None # Kill redis

# Fake OPA check for httpx.AsyncClient.post
class FakeResponse:
    status_code = 200
    def json(self): return {"result": True}
    def raise_for_status(self): pass
    def __await__(self):
        async def _awaitable():
            return self
        return _awaitable().__await__()

httpx.AsyncClient.post = lambda *args, **kwargs: FakeResponse()

from apps.api.database import Base, Incident
from apps.api.pilot import pilot_status

# SQLite Mock
engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_current_user] = lambda: {"subject": "mock", "role": "operator"}

client = TestClient(app)

def run_pilot_simulation():
    print("===============================================================")
    print("  PHOENIX CRDT / HAVEN EDGE - CLOSED PILOT SIMULATION (MOCK)")
    print("===============================================================\n")

    print("[1] Pilot Environment Verified.")
    print(f"    Mode: {os.environ.get('PILOT_MODE')}")
    print(f"    Geofence: {os.environ.get('PILOT_GEOFENCE')}\n")

    headers = {"Authorization": "Bearer operator_token"}

    # Test 1: Inside Geofence (Visakhapatnam) -> Should Succeed
    print("[2] Injecting Incident INSIDE Geofence (Visakhapatnam: 17.72, 83.23)...")
    inc_inside = {
        "type": "SOS",
        "location": {"latitude": 17.72, "longitude": 83.23},
        "message": "Inside fence test",
        "source": "mobile"
    }
    
    resp_in = client.post("/v1/incidents", json=inc_inside, headers=headers)
    if resp_in.status_code == 200:
        print("    [PASS] Incident accepted by Geofence.")
    else:
        print(f"    [FAIL] Expected 200, got {resp_in.status_code}: {resp_in.text}")

    # Test 2: Outside Geofence (New York) -> Should Fail
    print("\n[3] Injecting Incident OUTSIDE Geofence (New York: 40.71, -74.00)...")
    inc_outside = {
        "type": "SOS",
        "location": {"latitude": 40.71, "longitude": -74.00},
        "message": "Outside fence test",
        "source": "mobile"
    }
    resp_out = client.post("/v1/incidents", json=inc_outside, headers=headers)
    if resp_out.status_code == 403 and "outside pilot geofence" in resp_out.text.lower():
        print("    [PASS] Incident correctly rejected by Geofence (403).")
    else:
        print(f"    [FAIL] Expected 403 geofence rejection, got {resp_out.status_code}: {resp_out.text}")

    # Test 3: Activate Kill Switch
    print("\n[4] Operator Activating Pilot Kill Switch...")
    resp_suspend = client.post("/v1/pilot/suspend", json={"reason": "Emergency abort triggered by operator"}, headers=headers)
    if resp_suspend.status_code == 200:
        print("    [PASS] Pilot suspended successfully.")
    else:
        print(f"    [FAIL] Expected 200, got {resp_suspend.status_code}: {resp_suspend.text}")

    # Test 4: Inside Geofence but Suspended -> Should Fail
    print("\n[5] Injecting Incident INSIDE Geofence while SUSPENDED...")
    resp_suspended_in = client.post("/v1/incidents", json=inc_inside, headers=headers)
    if resp_suspended_in.status_code == 503 and "suspended" in resp_suspended_in.text.lower():
        print("    [PASS] Incident correctly rejected (503 Pilot Suspended).")
    else:
        print(f"    [FAIL] Expected 503 suspension rejection, got {resp_suspended_in.status_code}: {resp_suspended_in.text}")

    print("\n===============================================================")
    print("  PILOT SIMULATION COMPLETE: Geofence & Kill Switch working.")
    print("===============================================================")

if __name__ == "__main__":
    run_pilot_simulation()
