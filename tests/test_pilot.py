import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

import pilot as pilot_module
from pilot import enforce_pilot_constraints

from apps.api.main import app, get_current_user
from apps.api.main import get_db as main_get_db

GEOFENCE = "34.0,-118.3,34.2,-117.9"  # min_lat,min_lon,max_lat,max_lon


@pytest.fixture(autouse=True)
def clean_pilot_state(monkeypatch):
    monkeypatch.delenv("PILOT_MODE", raising=False)
    monkeypatch.delenv("PILOT_GEOFENCE", raising=False)
    yield
    pilot_module._suspended = False
    pilot_module._suspended_by = None
    pilot_module._suspension_reason = None


# --- Gate unit tests ---

def test_gate_noop_when_pilot_mode_off():
    enforce_pilot_constraints(0.0, 0.0)


def test_gate_allows_inside_geofence(monkeypatch):
    monkeypatch.setenv("PILOT_MODE", "1")
    monkeypatch.setenv("PILOT_GEOFENCE", GEOFENCE)
    enforce_pilot_constraints(34.1, -118.1)


def test_gate_rejects_outside_geofence(monkeypatch):
    monkeypatch.setenv("PILOT_MODE", "1")
    monkeypatch.setenv("PILOT_GEOFENCE", GEOFENCE)
    with pytest.raises(HTTPException) as exc:
        enforce_pilot_constraints(40.7, -74.0)
    assert exc.value.status_code == 403
    assert "geofence" in exc.value.detail.lower()


def test_gate_fails_closed_on_bad_config(monkeypatch):
    monkeypatch.setenv("PILOT_MODE", "1")
    monkeypatch.setenv("PILOT_GEOFENCE", "not-a-box")
    with pytest.raises(HTTPException) as exc:
        enforce_pilot_constraints(34.1, -118.1)
    assert exc.value.status_code == 503


def test_gate_blocked_entirely_when_suspended(monkeypatch):
    monkeypatch.setenv("PILOT_MODE", "1")
    monkeypatch.setenv("PILOT_GEOFENCE", GEOFENCE)
    pilot_module.suspend_pilot("test-operator", "Drill: simulated integrity failure")
    with pytest.raises(HTTPException) as exc:
        enforce_pilot_constraints(34.1, -118.1)
    assert exc.value.status_code == 503


def test_suspension_applies_even_with_pilot_off():
    pilot_module.suspend_pilot("test-operator", "Kill switch engaged during incident")
    with pytest.raises(HTTPException) as exc:
        enforce_pilot_constraints(34.1, -118.1)
    assert exc.value.status_code == 503


# --- API integration tests ---

@pytest.fixture
def client(monkeypatch):
    saved = dict(app.dependency_overrides)
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None

    def override_get_db():
        yield mock_db

    def override_user():
        return {"subject": "op-123", "role": "operator"}

    app.dependency_overrides[main_get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_user

    # Bypass OPA (same approach as test_api_unit.py: the policy dependency
    # closure is bound at route definition time, so patch its HTTP call).
    async def fake_opa_post(self, url, **kwargs):
        resp = MagicMock()
        resp.json.return_value = {"result": True}
        return resp

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_opa_post)
    monkeypatch.setattr("apps.api.main.redis_client", None)

    yield TestClient(app)

    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)


SOS_INSIDE = {
    "type": "SOS",
    "location": {"latitude": 34.1, "longitude": -118.1},
    "message": "pilot test",
    "source": "civilian",
}


def test_api_ingestion_allowed_within_fence(client, monkeypatch):
    monkeypatch.setenv("PILOT_MODE", "1")
    monkeypatch.setenv("PILOT_GEOFENCE", GEOFENCE)
    resp = client.post("/v1/incidents", json=SOS_INSIDE)
    assert resp.status_code == 200
    assert resp.json()["status"] == "CREATED"


def test_api_ingestion_rejected_outside_fence(client, monkeypatch):
    monkeypatch.setenv("PILOT_MODE", "1")
    monkeypatch.setenv("PILOT_GEOFENCE", GEOFENCE)
    payload = {**SOS_INSIDE, "location": {"latitude": 48.85, "longitude": 2.35}}
    resp = client.post("/v1/incidents", json=payload)
    assert resp.status_code == 403


def test_api_suspend_resume_lifecycle(client):
    reason = "Anomaly detected: dispatch loop suspected in sector 7"
    resp = client.post("/v1/pilot/suspend", json={"reason": reason})
    assert resp.status_code == 200
    assert resp.json()["status"] == "suspended"

    status = client.get("/v1/pilot/status").json()
    assert status["suspended"] is True
    assert status["suspended_by"] == "op-123"

    resp = client.post("/v1/incidents", json=SOS_INSIDE)
    assert resp.status_code == 503

    resp = client.post("/v1/pilot/resume")
    assert resp.status_code == 200
    assert client.get("/v1/pilot/status").json()["suspended"] is False


def test_api_suspend_requires_detailed_reason(client):
    resp = client.post("/v1/pilot/suspend", json={"reason": "short"})
    assert resp.status_code == 400


def test_api_pilot_status_reports_config_error(client, monkeypatch):
    monkeypatch.setenv("PILOT_MODE", "1")
    monkeypatch.setenv("PILOT_GEOFENCE", "1,2,3")
    status = client.get("/v1/pilot/status").json()
    assert status["config_error"] is not None
