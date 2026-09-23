import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from apps.api.main import app
from apps.api.main import get_db as main_get_db


def override_get_db():
    mock_db = MagicMock()
    yield mock_db


@pytest.fixture(autouse=True)
def api_dependencies():
    saved = dict(app.dependency_overrides)
    app.dependency_overrides[main_get_db] = override_get_db
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)


client = TestClient(app)

HAVEN_SOS_BODY = {
    "type": "SOS",
    "location": {"latitude": 34.0522, "longitude": -118.2437},
    "message": "House is flooding, water rising fast",
    "source": "haven_web_pwa"
}


def test_haven_sos_accepts_credential_free_sos():
    resp = client.post(
        "/v1/haven/sos",
        json=HAVEN_SOS_BODY,
        headers={"X-Forwarded-For": "10.0.0.1", "Idempotency-Key": "k-haven-1"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "CREATED"
    assert body["incident_id"].startswith("INC-")


def test_haven_sos_rejects_out_of_range_location():
    bad = dict(HAVEN_SOS_BODY)
    bad["location"] = {"latitude": 95.0, "longitude": -118.0}
    resp = client.post("/v1/haven/sos", json=bad, headers={"X-Forwarded-For": "10.0.0.2"})
    assert resp.status_code == 422


def test_haven_sos_rejects_empty_message():
    bad = dict(HAVEN_SOS_BODY)
    bad["message"] = ""
    resp = client.post("/v1/haven/sos", json=bad, headers={"X-Forwarded-For": "10.0.0.3"})
    assert resp.status_code == 422