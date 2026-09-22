import math
import json as _json
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from apps.api.main import (
    app,
    get_db as main_get_db,
    get_current_user,
    get_rate_limit_key,
    get_real_ip,
    limiter,
)
from apps.api.database import Base as _Base
import apps.api.main as main_module

import jwt as pyjwt


_ENGINE = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
_Base.metadata.create_all(_ENGINE)
_Session = sessionmaker(bind=_ENGINE)


@pytest.fixture(autouse=True)
def isolated_environment():
    saved_overrides = dict(app.dependency_overrides)
    saved_post = __import__("httpx").AsyncClient.post
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

    import httpx

    httpx.AsyncClient.post = fake_opa_post
    main_module.redis_client = None

    app.dependency_overrides[main_get_db] = override_get_db
    limiter.reset()
    yield
    httpx.AsyncClient.post = saved_post
    main_module.redis_client = saved_main_redis
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved_overrides)


@pytest.fixture()
def citizen_client(isolated_environment):
    app.dependency_overrides[get_current_user] = lambda: {
        "subject": "citizen-r07",
        "role": "citizen",
    }
    return TestClient(app)


@pytest.fixture()
def operator_client(isolated_environment):
    app.dependency_overrides[get_current_user] = lambda: {
        "subject": "operator-r07",
        "role": "operator",
    }
    return TestClient(app)


def _post_raw(client, path, payload):
    # httpx refuses NaN/Infinity in its own JSON encoder; send raw body so the
    # SERVER-side validator is what gets exercised.
    return client.post(
        path,
        content=_json.dumps(payload, allow_nan=True),
        headers={"Content-Type": "application/json"},
    )


# --- R-07: NaN / Infinity / out-of-range coordinates must be rejected ---


def test_incident_rejects_nan_latitude(citizen_client):
    resp = _post_raw(
        citizen_client,
        "/v1/incidents",
        {
            "type": "SOS",
            "location": {"latitude": float("nan"), "longitude": -118.1},
            "message": "nan probe",
            "source": "civilian",
        },
    )
    assert resp.status_code == 422


def test_incident_rejects_out_of_range_longitude(citizen_client):
    resp = _post_raw(
        citizen_client,
        "/v1/incidents",
        {
            "type": "SOS",
            "location": {"latitude": 34.1, "longitude": 999.0},
            "message": "range probe",
            "source": "civilian",
        },
    )
    assert resp.status_code == 422


def test_asset_status_rejects_infinite_latitude(operator_client):
    resp = operator_client.put(
        "/v1/assets/AST-001/status",
        json={
            "status": "EN_ROUTE",
            "latitude": 34.1,
            "longitude": -118.1,
        },
    )
    assert resp.status_code != 500
    resp_bad = operator_client.request(
        "PUT",
        "/v1/assets/AST-001/status",
        content=_json.dumps(
            {
                "status": "EN_ROUTE",
                "latitude": float("inf"),
                "longitude": -118.1,
            },
            allow_nan=True,
        ),
        headers={"Content-Type": "application/json"},
    )
    assert resp_bad.status_code == 422


def test_asset_status_rejects_nan_longitude_and_bad_range(operator_client):
    resp = operator_client.request(
        "PUT",
        "/v1/assets/AST-001/status",
        content=_json.dumps(
            {
                "status": "EN_ROUTE",
                "latitude": 34.1,
                "longitude": float("nan"),
            },
            allow_nan=True,
        ),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422
    resp2 = operator_client.put(
        "/v1/assets/AST-001/status",
        json={
            "status": "EN_ROUTE",
            "latitude": 120.0,
        },
    )
    assert resp2.status_code == 422


# --- R-09: rate-limit buckets are partitioned per authenticated subject ---


def _request_with_auth(token: str | None, ip: str = "10.0.0.9") -> Request:
    headers = []
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    return Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "query_string": b"",
            "client": (ip, 12345),
        }
    )


def test_rate_key_partitions_by_subject():
    t_alice = pyjwt.encode({"sub": "alice"}, "k", algorithm="HS256")
    t_bob = pyjwt.encode({"sub": "bob"}, "k", algorithm="HS256")
    k_alice = get_rate_limit_key(_request_with_auth(t_alice))
    k_bob = get_rate_limit_key(_request_with_auth(t_bob))
    assert k_alice == "subj:alice"
    assert k_bob == "subj:bob"
    assert k_alice != k_bob


def test_rate_key_falls_back_to_ip_without_token():
    req = _request_with_auth(None)
    assert get_rate_limit_key(req) == "10.0.0.9"


def test_real_ip_ignores_spoofed_header_from_public_peer():
    from fastapi.requests import Request

    # A direct public client (no trusted proxy in front) cannot rotate its
    # rate-limit bucket by sending X-Real-IP.
    req = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-real-ip", b"203.0.113.7")],
            "query_string": b"",
            "client": ("8.8.8.8", 12345),
        }
    )
    assert get_real_ip(req) == "8.8.8.8"


def test_real_ip_honors_header_from_trusted_proxy():
    from fastapi.requests import Request

    # Nginx edge (docker private network) peers are trusted, so the header wins.
    req = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-real-ip", b"203.0.113.7")],
            "query_string": b"",
            "client": ("172.17.0.2", 12345),
        }
    )
    assert get_real_ip(req) == "203.0.113.7"


def test_rate_key_falls_back_to_ip_on_garbage_token():
    req = _request_with_auth("not-a-jwt")
    assert get_rate_limit_key(req) == "10.0.0.9"


def test_limiter_uses_subject_aware_key():
    assert limiter._key_func is get_rate_limit_key
