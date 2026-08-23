import pytest
import os
import httpx
from fastapi.testclient import TestClient
from apps.api.main import app

from unittest.mock import MagicMock
client = TestClient(app)
import httpx
async def fake_opa_post(*args, **kwargs):
    resp = MagicMock()
    resp.json.return_value = {'result': True}
    return resp
httpx.AsyncClient.post = fake_opa_post
import apps.api.pilot as pilot_module
import fakeredis
pilot_module.redis_client = fakeredis.FakeRedis()
pilot_module.GEOFENCE = {"latitude": 48.8, "longitude": 2.3, "radius_km": 50}
import apps.api.main as main_module
main_module.redis_client = None

def test_f2_assets_authorization():
    # Unauthenticated should fail
    resp = client.get("/v1/assets")
    assert resp.status_code in [401, 403]

def test_f3_request_size_limit():
    # 2000 chars should be rejected by pydantic max_length=1000
    payload = {
        "type": "SOS",
        "location": {"latitude": 0.0, "longitude": 0.0},
        "message": "A" * 2000,
        "source": "civilian"
    }
    resp = client.post("/v1/incidents", json=payload)
    assert resp.status_code == 422
    assert "String should have at most 1000 characters" in resp.text

def test_f3_redos_timing():
    # 900 chars (within limit) of an almost-email to test regex backtracking
    import time
    payload = {
        "type": "SOS",
        "location": {"latitude": 0.0, "longitude": 0.0},
        "message": "a" * 900 + "@" + "a" * 90,
        "source": "civilian"
    }
    start = time.time()
    resp = client.post("/v1/incidents", json=payload)
    elapsed = time.time() - start
    assert elapsed < 0.5  # Should be near instantaneous now

def test_f5_secrets_detection():
    # Check if .env is git tracked
    status = os.popen("git ls-files .env").read().strip()
    assert status == ""

def test_f6_dashboard_credentials():
    with open("apps/dashboard/src/app/page.tsx") as f:
        content = f.read()
    assert "operatorpass" not in content
    assert "grant_type" not in content

def test_f7_network_isolation():
    with open("docker-compose.yml") as f:
        content = f.read()
    assert 'ports:\n      - "8181:8181"' not in content
    assert 'ports:\n      - "4222:4222"' not in content
    assert 'ports:\n      - "5433:5432"' not in content

def test_f9_startup_preservation():
    with open("apps/api/seed_assets.py") as f:
        content = f.read()
    assert "db.query(Asset).first()" in content
    assert "SEED_DB" in content

def test_f10_audit_token_leakage():
    with open("apps/api/main.py") as f:
        content = f.read()
    assert '"token": override_token' not in content
    assert '"token_hash": token_hash' in content

def test_f11_cors_wildcard():
    with open("apps/api/main.py") as f:
        content = f.read()
    assert 'allow_origins=["*"]' not in content

def test_f12_keycloak_hardened():
    with open("infra/keycloak/realm-export.json") as f:
        content = f.read()
    assert '"directAccessGrantsEnabled": false' in content
    assert '"publicClient": false' in content
    assert '"bruteForceProtected": true' in content

def test_f13_tls_enabled():
    with open("infra/nginx/nginx.conf") as f:
        content = f.read()
    assert 'listen 443 ssl;' in content
    assert 'ssl_certificate' in content

def test_f15_migrations_exist():
    assert len(os.listdir("alembic/versions")) > 0




