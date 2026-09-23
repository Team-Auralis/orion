import json

import httpx as real_httpx
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.database import Base, ForgeExperiment
from services.forge.engine import ForgeEngine
from services.mathsage.coprocessor import MathCoprocessor


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        return self._json


def fake_ollama(monkeypatch, *, models=None, response=None,
                raise_timeout=False):
    """Swap the real Ollama HTTP client for a scripted fake."""
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            return FakeResponse(
                json_data={"models": models or [{"name": "mathstral:7b"}]}
            )

        def post(self, url, json=None):
            if raise_timeout:
                raise real_httpx.ReadTimeout("inference too slow")
            if isinstance(response, Exception):
                raise response
            return FakeResponse(json_data={"response": response})

    monkeypatch.setattr("services.mathsage.coprocessor.httpx.Client",
                        FakeClient)


@pytest.fixture
def forge_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


def test_reason_success_json(monkeypatch):
    fake_ollama(monkeypatch, response=(
        '{"verdict": "SUPPORTED", "confidence": 0.9, '
        '"reasoning": "numbers are internally coherent"}'
    ))
    result = MathCoprocessor().reason("Is 12*13 = 156?", "{\"n\": 156}")
    assert result["verdict"] == "SUPPORTED"
    assert result["confidence"] == 0.9
    assert result["coprocessor_active"] is True
    assert result["fallback_reason"] is None


def test_reason_extracts_json_from_verbose_output(monkeypatch):
    fake_ollama(monkeypatch, response=(
        "Let me compute step by step...\n"
        '{"verdict": "CHALLENGED", "confidence": 0.4, '
        '"reasoning": "score seems too high"}\n'
        "Therefore I conclude."
    ))
    result = MathCoprocessor().reason("q", "ctx")
    assert result["verdict"] == "CHALLENGED"
    assert result["confidence"] == 0.4
    assert result["coprocessor_active"] is True


def test_reason_missing_model_falls_back(monkeypatch):
    fake_ollama(monkeypatch, models=[{"name": "qwen2:0.5b"}])
    result = MathCoprocessor().reason("q", "ctx")
    assert result["verdict"] == "UNAVAILABLE"
    assert result["coprocessor_active"] is False
    assert "MODEL_NOT_FOUND" in result["fallback_reason"]


def test_reason_timeout_falls_back(monkeypatch):
    fake_ollama(monkeypatch, raise_timeout=True)
    result = MathCoprocessor().reason("q", "ctx")
    assert result["verdict"] == "UNAVAILABLE"
    assert result["coprocessor_active"] is False
    assert "timed out" in result["fallback_reason"]


def test_reason_unparseable_output_reported(monkeypatch):
    fake_ollama(monkeypatch, response="I cannot produce JSON today.")
    result = MathCoprocessor().reason("q", "ctx")
    assert result["verdict"] == "INCONCLUSIVE"
    assert result["coprocessor_active"] is True
    assert "not parseable JSON" in result["fallback_reason"]


def test_forge_skips_review_when_disabled(forge_db, monkeypatch):
    monkeypatch.setattr(MathCoprocessor, "enabled",
                        staticmethod(lambda: False))
    forge = ForgeEngine(forge_db)
    exp_id = forge.propose_hypothesis("H", {"vars": {}})
    forge.record_result(exp_id, {"fixed": True}, 0.85)
    stored = json.loads(forge_db.query(ForgeExperiment).first().result_data)
    assert "math_coprocessor_review" not in stored


def test_forge_records_review_from_injected_coprocessor(forge_db):
    class StubCoprocessor:
        def review_experiment(self, hypothesis, design, result,
                              evaluation_score):
            return {
                "model_used": "mathstral:7b",
                "model_role": "MATH_COPROCESSOR",
                "coprocessor_active": True,
                "fallback_reason": None,
                "verdict": "SUPPORTED",
                "confidence": 0.9,
                "reasoning": "results match the hypothesis",
            }

    forge = ForgeEngine(forge_db, math_coprocessor=StubCoprocessor())
    exp_id = forge.propose_hypothesis("H", {"vars": {}})
    forge.record_result(exp_id, {"renewables_increase": 3.5}, 0.9)
    stored = json.loads(forge_db.query(ForgeExperiment).first().result_data)
    assert stored["math_coprocessor_review"]["verdict"] == "SUPPORTED"
    assert stored["math_coprocessor_review"]["confidence"] == 0.9


def test_forge_survives_coprocessor_failure(forge_db):
    class BomberCoprocessor:
        def review_experiment(self, **kwargs):
            raise RuntimeError("crash")

    forge = ForgeEngine(forge_db, math_coprocessor=BomberCoprocessor())
    exp_id = forge.propose_hypothesis("H", {"vars": {}})
    forge.record_result(exp_id, {"fixed": True}, 0.8)
    row = forge_db.query(ForgeExperiment).first()
    stored = json.loads(row.result_data)
    assert row.status == "EVALUATED"
    assert stored["math_coprocessor_review"]["verdict"] == "INCONCLUSIVE"
    assert "Unhandled error" in stored["math_coprocessor_review"]["fallback_reason"]