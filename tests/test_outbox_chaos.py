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
        "source": "mobile",
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
        if (
            payload.get("incident_id") == incident_id
            and payload.get("event_type") == "incident.created"
        ):
            found = True

    assert found, "Outbox event not found!"


@pytest.mark.asyncio
async def test_outbox_publisher_does_not_mark_stuck_publish_published(monkeypatch):
    import asyncio
    import apps.api.main as m
    from apps.api.database import OutboxEvent

    class SlowNATS:
        is_connected = True

        async def publish(self, topic, payload, headers=None):
            await asyncio.sleep(30)  # hangs: simulates a wedged NATS connection

    fake_event = OutboxEvent(id="evt-slow", topic="incident.created", payload="{}")

    class FakeSession:
        def __init__(self):
            self.closed = False

        def query(self, model):
            return self

        def filter(self, *a, **k):
            return self

        def limit(self, n):
            return self

        def all(self):
            return [fake_event]

        def commit(self):
            pass

        def close(self):
            self.closed = True

    session = FakeSession()

    monkeypatch.setattr(m, "nc", SlowNATS())
    monkeypatch.setattr(m, "SessionLocal", lambda: session)
    # Break the infinite loop after one iteration. KeyboardInterrupt is a
    # BaseException so the loop's `except Exception` does not swallow it.
    monkeypatch.setattr(
        asyncio, "sleep", lambda s: (_ for _ in ()).throw(KeyboardInterrupt())
    )

    with pytest.raises(KeyboardInterrupt):
        await m.outbox_publisher_loop()

    # The publish hung; wait_for timed it out, so the event must NOT be marked
    # published — a later retry will pick it up.
    assert not fake_event.published
    assert session.closed is True
