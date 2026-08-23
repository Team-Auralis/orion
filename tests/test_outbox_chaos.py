import pytest
import json
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from apps.api.main import app, get_db
from apps.api.database import Base, OutboxEvent, Incident
from apps.api.security import mask_pii

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
client = TestClient(app)

def test_outbox_event_creation():
    # MOCK OPA so it doesn't fail on auth
    from unittest.mock import patch
    with patch("apps.api.main.httpx.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"result": True}
        
        inc_payload = {
            "type": "SOS",
            "location": {"latitude": 34.1, "longitude": -118.1},
            "message": "Outbox Chaos Test",
            "source": "mobile"
        }
        
        # 1. Post an incident
        resp = client.post("/v1/incidents", json=inc_payload, headers={"Authorization": "Bearer MOCK_TOKEN"})
        
        # 2. Verify response
        assert resp.status_code == 200, resp.text
        incident_id = resp.json()["incident_id"]

        # 3. Verify it is in DB
        db = TestingSessionLocal()
        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        assert incident is not None

        # 4. Verify Outbox event was created
        outbox_events = db.query(OutboxEvent).filter(OutboxEvent.published == False).all()
        assert len(outbox_events) > 0
        
        found = False
        for ev in outbox_events:
            payload = json.loads(ev.payload)
            if payload.get("event_id") == incident_id:
                found = True
        
        assert found, "Outbox event not found!"
        print("\\n[PASS] MOCK CHAOS DRILL: Outbox event successfully stored with published=False. Background sweep will replay this when NATS is back online.")
