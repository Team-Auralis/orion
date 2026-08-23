import pytest
import json
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import MagicMock
from apps.api.main import app, get_db, get_current_user
from apps.api.database import Base, OutboxEvent, Incident

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

def override_get_current_user():
    return {"subject": "chaos-operator", "role": "operator"}

@pytest.fixture(autouse=True)
def isolated_overrides(monkeypatch):
    saved = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    async def allow_opa(self, url, **kwargs):
        resp = MagicMock()
        resp.json.return_value = {"result": True}
        return resp

    monkeypatch.setattr("apps.api.main.httpx.AsyncClient.post", allow_opa)
    monkeypatch.setattr("apps.api.main.redis_client", None)
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)

client = TestClient(app)

def test_outbox_event_creation():
    inc_payload = {
        "type": "SOS",
        "location": {"latitude": 34.1, "longitude": -118.1},
        "message": "Outbox Chaos Test",
        "source": "mobile"
    }

    # 1. Post an incident
    resp = client.post("/v1/incidents", json=inc_payload)

    # 2. Verify response
    assert resp.status_code == 200, resp.text
    incident_id = resp.json()["incident_id"]

    # 3. Verify it is in DB
    db = TestingSessionLocal()
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    assert incident is not None

    # 4. Verify Outbox event was created atomically in the same commit
    outbox_events = db.query(OutboxEvent).filter(OutboxEvent.published == False).all()
    assert len(outbox_events) > 0

    found = False
    for ev in outbox_events:
        payload = json.loads(ev.payload)
        if payload.get("incident_id") == incident_id and payload.get("event_type") == "incident.created":
            found = True

    assert found, "Outbox event not found!"
