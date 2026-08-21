import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from apps.api.main import app, get_db, get_current_user, check_policy

# Mock dependencies
def override_get_db():
    mock_db = MagicMock()
    yield mock_db

def override_get_current_user():
    return {"subject": "test-user-123", "role": "operator"}

def override_check_policy(action: str, resource: str):
    async def dependency():
        return {"subject": "test-user-123", "role": "operator"}
    return dependency

app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_current_user] = override_get_current_user

# For endpoints that use check_policy directly in router, we override it globally or patch
# But check_policy is a function returning a dependency. 
# We'll just patch the internal circuit breaker logic for isolated tests.

client = TestClient(app)

def test_health_check_or_metrics():
    # Prometheus instrumentator exposes /metrics
    response = client.get("/metrics")
    assert response.status_code == 200
    assert b"python_gc_objects_collected_total" in response.content or b"http_requests_total" in response.content

@patch("apps.api.main.redis_client")
def test_break_glass_auth_missing_reason(mock_redis):
    # Test missing reason (fails)
    response = client.post("/v1/auth/break-glass", json={"reason": "too short"})
    assert response.status_code == 400
    assert "explicit, detailed reason" in response.json()["detail"]

@patch("apps.api.main.redis_client")
def test_break_glass_auth_valid(mock_redis):
    # Use a different IP/client for the rate limiter by passing a header, or it might still block based on default IP.
    # Actually, we can just disable the rate limiter for tests by mocking it, or change the endpoint.
    # A quick way to bypass is to change the forwarded-for header.
    headers = {"X-Forwarded-For": "192.168.1.100"}
    response = client.post("/v1/auth/break-glass", json={"reason": "Emergency network partition active, overriding safely."}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "override_token" in data
    assert data["expires_in"] == "15m"

@patch("httpx.AsyncClient.post")
@patch("apps.api.main.redis_client", None)
def test_get_incidents_policy_enforcement(mock_post):
    # Mock OPA returning True
    mock_response = MagicMock()
    mock_response.json.return_value = {"result": True}
    mock_post.return_value = mock_response

    response = client.get("/v1/incidents")
    
    # Since the mock DB returns an empty iterator/MagicMock that FastAPI can serialize as [], 
    # it successfully returns a 200 OK. This proves auth bypassed the 403!
    assert response.status_code == 200
