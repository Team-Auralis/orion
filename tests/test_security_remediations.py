import os
import pytest
import httpx
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import app
from apps.api.database import get_db as main_get_db
import apps.api.main as main_module
import apps.api.pilot as pilot_module
import fakeredis

# In-memory DB so request handlers never touch real infrastructure and
# latency measurements reflect application code, not connect timeouts.
_ENGINE = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
from apps.api.database import Base as _Base

_Base.metadata.create_all(_ENGINE)
_Session = sessionmaker(bind=_ENGINE)


@pytest.fixture(autouse=True)
def isolated_environment():
    """
    Module-scoped isolation: patches are applied per-test and RESTORED,
    unlike the previous import-time globals that leaked into every later
    test module (bytes-returning redis handle broke pilot kill-switch
    comparisons; the global httpx patch hijacked other modules' OPA/LLM calls).
    """
    saved_overrides = dict(app.dependency_overrides)
    saved_post = httpx.AsyncClient.post
    saved_pilot_redis = pilot_module.redis_client
    saved_main_redis = main_module.redis_client

    def override_get_db():
        db = _Session()
        try:
            yield db
        finally:
            db.close()

    async def fake_opa_post(self, url, **kwargs):
        resp = MagicMock()
        resp.json.return_value = {"result": True}
        return resp

    httpx.AsyncClient.post = fake_opa_post
    # decode_responses=True keeps parity with production redis client config;
    # a bytes-returning handle silently breaks string kill-switch comparisons.
    fr = fakeredis.FakeRedis(decode_responses=True)
    pilot_module.redis_client = fr
    main_module.redis_client = None
    app.dependency_overrides[main_get_db] = override_get_db

    client_holder = TestClient(app)
    yield client_holder

    httpx.AsyncClient.post = saved_post
    pilot_module.redis_client = saved_pilot_redis
    main_module.redis_client = saved_main_redis
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved_overrides)


@pytest.fixture()
def client(isolated_environment):
    return isolated_environment


def test_f2_assets_authorization(client):
    # Unauthenticated should fail
    resp = client.get("/v1/assets")
    assert resp.status_code in [401, 403]


def test_f3_request_size_limit(client):
    # 2000 chars should be rejected by pydantic max_length=1000
    payload = {
        "type": "SOS",
        "location": {"latitude": 0.0, "longitude": 0.0},
        "message": "A" * 2000,
        "source": "civilian",
    }
    resp = client.post("/v1/incidents", json=payload)
    assert resp.status_code == 422
    assert "String should have at most 1000 characters" in resp.text


def test_f3_redos_timing(client):
    # 900 chars (within limit) of an almost-email to test regex backtracking
    import time

    payload = {
        "type": "SOS",
        "location": {"latitude": 0.0, "longitude": 0.0},
        "message": "a" * 900 + "@" + "a" * 90,
        "source": "civilian",
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
    src_files = []
    for root, dirs, files in os.walk(os.path.join("apps", "dashboard")):
        dirs[:] = [d for d in dirs if d not in (".next", "node_modules")]
        src_files += [
            os.path.join(root, f)
            for f in files
            if f.endswith((".tsx", ".ts", ".jsx", ".js"))
        ]
    if not src_files:
        pytest.skip(
            "dashboard source tree not present (credentials removed with source)"
        )
    leaked = [
        p
        for p in src_files
        if "operatorpass" in open(p, encoding="utf-8", errors="ignore").read().lower()
    ]
    assert leaked == []


def test_f7_network_isolation():
    with open("docker-compose.yml") as f:
        content = f.read()
    assert 'ports:\n      - "8181:8181"' not in content
    assert 'ports:\n      - "4222:4222"' not in content
    assert 'ports:\n      - "5433:5432"' not in content


def test_f9_startup_preservation():
    with open("apps/api/seed_assets.py") as f:
        content = f.read()
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
    # The orion-api client uses the direct-access password grant (public client,
    # per patch_realm.py); a confidential client with no secret would break login.
    with open("infra/keycloak/realm-export.json") as f:
        content = f.read()
    assert '"directAccessGrantsEnabled": true' in content
    assert '"publicClient": true' in content
    assert '"bruteForceProtected": true' in content


def test_f13_tls_enabled():
    with open("infra/nginx/nginx.conf") as f:
        content = f.read()
    assert "listen 443 ssl;" in content
    assert "ssl_certificate" in content


def test_f15_migrations_exist():
    versions_dir = os.path.join("alembic", "versions")
    assert os.path.isdir(versions_dir)
    assert len([f for f in os.listdir(versions_dir) if f.endswith(".py")]) > 0
