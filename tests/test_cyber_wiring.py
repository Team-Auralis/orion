import json
import os
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from services.cyber.emitter import emit


@pytest.fixture()
def sink(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("FORGE_CYBER_EVENTS", str(path))
    yield path
    if os.path.exists(path):
        os.remove(path)


def _records(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_emit_noop_when_env_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("FORGE_CYBER_EVENTS", raising=False)
    emit("auth.failure")  # must not raise, must not create files
    assert not list(tmp_path.iterdir())


def test_emit_writes_jsonl_record(sink):
    emit("pilot.killswitch", source="api", actor={"id": "op-1"},
         outcome="suspended", reason="drill")
    recs = _records(sink)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["category"] == "pilot.killswitch"
    assert rec["actor"] == {"id": "op-1"}
    assert rec["outcome"] == "suspended"
    assert rec["attributes"]["reason"] == "drill"
    assert "timestamp" in rec


def test_emit_swallows_unwritable_sink(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    # A file used as a parent 'directory' makes open() fail immediately.
    monkeypatch.setenv("FORGE_CYBER_EVENTS", str(blocker / "sub" / "events.jsonl"))
    emit("auth.failure")  # must not raise


def test_auth_failure_emits_event(sink):
    client = TestClient(app)
    resp = client.get("/v1/assets")  # no Authorization header
    assert resp.status_code == 403
    recs = _records(sink)
    assert any(r["category"] == "auth.failure" and r["outcome"] == "denied"
               for r in recs)


def test_civilian_incident_path_emits_nothing(sink):
    from unittest.mock import MagicMock
    import httpx
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from apps.api.main import get_db as main_get_db
    from apps.api.database import Base as _Base
    import apps.api.main as main_module

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    _Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    async def fake_opa_post(self, url, **kwargs):
        resp = MagicMock()
        resp.json.return_value = {"result": True}
        return resp

    saved_overrides = dict(app.dependency_overrides)
    saved_post = httpx.AsyncClient.post
    saved_redis = main_module.redis_client
    httpx.AsyncClient.post = fake_opa_post
    main_module.redis_client = None
    app.dependency_overrides[main_get_db] = override_get_db
    try:
        client = TestClient(app)
        resp = client.post("/v1/incidents", headers={}, json={
            "type": "SOS",
            "location": {"latitude": 34.1, "longitude": -118.1},
            "message": "hello",
            "source": "civilian",
        })
        assert resp.status_code == 200
    finally:
        httpx.AsyncClient.post = saved_post
        main_module.redis_client = saved_redis
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved_overrides)

    # Civilian ingestion is a legitimate anonymous path: no security event.
    assert _records(sink) == []
