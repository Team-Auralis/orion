import json
import pytest
from unittest.mock import MagicMock, patch


class _FakeMsg:
    def __init__(self, data: bytes, headers=None):
        self.data = data
        self.subject = "incident.created"
        self.headers = headers or {}
        self._client = MagicMock()
        self.acked = False
        self.termed = False
        self.nakked = False
        self.nak_delay = None

    async def ack(self):
        self.acked = True

    async def term(self):
        self.termed = True

    async def nak(self, delay=None):
        self.nakked = True
        self.nak_delay = delay


@pytest.fixture
def fake_event():
    return {
        "event_id": "evt-test-nak",
        "event_type": "incident.created",
        "incident_id": "INC-NAK-1",
        "message": "test",
    }


@pytest.mark.asyncio
async def test_worker_fails_open_when_redis_down(fake_event, monkeypatch):
    import services.worker.main as worker

    msg = _FakeMsg(json.dumps(fake_event).encode())

    def boom(*args, **kwargs):
        raise ConnectionError("redis unavailable")

    fake_redis = MagicMock()
    fake_redis.set.side_effect = boom
    monkeypatch.setattr(worker, "redis_client", fake_redis)
    monkeypatch.setattr(worker, "process_db_event", lambda e, t: None)
    monkeypatch.setattr(worker, "WORKER_DUPLICATES", MagicMock(), raising=False)
    monkeypatch.setattr(worker, "WORKER_SUCCESS", MagicMock(), raising=False)
    monkeypatch.setattr(worker, "WORKER_LATENCY", MagicMock(), raising=False)

    await worker.message_handler(msg)

    # Redis outage must not drop the event: it is processed and acked.
    assert msg.acked is True
    assert msg.termed is False
    assert msg.nakked is False


@pytest.mark.asyncio
async def test_worker_naks_transient_errors_instead_of_term(fake_event, monkeypatch):
    import services.worker.main as worker

    msg = _FakeMsg(json.dumps(fake_event).encode())

    def boom(event, event_type):
        raise RuntimeError("db down")

    monkeypatch.setattr(worker, "redis_client", None)
    monkeypatch.setattr(worker, "process_db_event", boom)
    monkeypatch.setattr(worker, "WORKER_DUPLICATES", MagicMock(), raising=False)
    monkeypatch.setattr(worker, "WORKER_SUCCESS", MagicMock(), raising=False)
    monkeypatch.setattr(worker, "WORKER_LATENCY", MagicMock(), raising=False)

    await worker.message_handler(msg)

    assert msg.termed is False
    assert msg.nakked is True
    assert msg.nak_delay == 5


@pytest.mark.asyncio
async def test_worker_terms_unparseable_message(fake_event, monkeypatch):
    import services.worker.main as worker

    msg = _FakeMsg(b"not-json{{")
    monkeypatch.setattr(worker, "redis_client", None)

    await worker.message_handler(msg)

    assert msg.termed is True
    assert msg.acked is False
