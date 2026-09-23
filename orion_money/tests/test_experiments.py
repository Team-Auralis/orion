"""Tests for the ORION experiment engine (:mod:`orion.experiments`).

Lifecycle, the evidence-supported delta rule (anti-hallucination), degraded
self-evaluation, and per-strategy result scoping. Each test runs against a
private SQLite DB in a pytest tmp dir.
"""

from __future__ import annotations

import json

import pytest

from orion import ledger
from orion.config import get_config
from orion.db import _reset_engine, get_session, init_db
from orion.experiments import EVALUATION_TEMPLATE, ExperimentService


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Point ORION at a temp data dir and bootstrap a fresh database."""
    monkeypatch.setenv("ORION_DATA_DIR", str(tmp_path))
    _reset_engine()
    get_config(force_reload=True)
    init_db()
    yield
    _reset_engine()


@pytest.fixture()
def svc() -> ExperimentService:
    return ExperimentService()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_start_opens_running(db, svc):
    with get_session() as s:
        exp = svc.start("hypothesis A", 1, 500, "expected +200paise", session=s)
        assert exp.status == "RUNNING"
        payload = json.loads(exp.payload_json)
        assert payload["hypothesis"] == "hypothesis A"
        assert payload["strategy_id"] == 1
        assert payload["params_paise"] == 500


# ---------------------------------------------------------------------------
# Results: evidence-gated deltas
# ---------------------------------------------------------------------------


def test_record_result_with_supporting_evidence_keeps_delta(db, svc):
    with get_session() as s:
        ledger.seed_capital(s, 20000)
        entry = ledger.record_revenue(s, 1000, source="gig", reference="ev-1")
        exp = svc.start("hypothesis B", 1, 500, "expected", session=s)

        result = svc.record_result(
            exp.id,
            "observed +1000",
            1000,
            supporting_evidence_id=entry.id,
            session=s,
        )
        assert result.delta_paise == 1000
        assert result.supporting_evidence_id == entry.id
        assert result.warning == ""
        assert exp.status == "COMPLETED"


def test_record_result_without_evidence_zeroes_delta(db, svc):
    """Anti-hallucination: an unsupported delta is never counted."""
    with get_session() as s:
        exp = svc.start("hypothesis C", 2, 300, "expected", session=s)
        result = svc.record_result(exp.id, "claimed +1000", 1000, session=s)
        assert result.delta_paise == 0
        assert result.supporting_evidence_id is None
        assert "anti-hallucination" in result.warning
        assert result.failure_reason is None
        assert exp.status == "COMPLETED"


def test_record_result_with_bogus_evidence_id_zeroes_delta(db, svc):
    """An id that resolves to nothing is the same as no evidence."""
    with get_session() as s:
        exp = svc.start("hypothesis D", 1, 100, "expected", session=s)
        result = svc.record_result(
            exp.id, "delta 42", 42, supporting_evidence_id=999_999, session=s
        )
        assert result.delta_paise == 0
        assert result.supporting_evidence_id is None
        assert "anti-hallucination" in result.warning


def test_record_result_failure_marks_failed(db, svc):
    with get_session() as s:
        exp = svc.start("hypothesis F", 1, 100, "expected", session=s)
        result = svc.record_result(
            exp.id, "broke", 0, failure_reason="infra down", session=s
        )
        assert result.failure_reason == "infra down"
        assert exp.status == "FAILED"


# ---------------------------------------------------------------------------
# Self-evaluation (degraded mode)
# ---------------------------------------------------------------------------


def test_evaluate_degraded_uses_template_no_fabrication(db, svc, monkeypatch):
    monkeypatch.setenv("ORION_FORCE_NO_OLLAMA", "1")
    with get_session() as s:
        exp = svc.start("hypothesis E", 1, 100, "expected", session=s)
        evaluation = svc.evaluate(exp.id, session=s)
        payload = json.loads(exp.payload_json)

    assert evaluation["degraded"] is True
    assert evaluation["verdict"] == EVALUATION_TEMPLATE
    assert evaluation["score_0_100"] == 0
    assert evaluation["lesson"] == ""
    # The stored evaluation matches the returned one — never a model verdict.
    stored = payload["evaluation"]
    assert stored["verdict"] == EVALUATION_TEMPLATE
    assert stored["score_0_100"] == 0


# ---------------------------------------------------------------------------
# Scoping
# ---------------------------------------------------------------------------


def test_results_for_returns_only_that_strategys_results(db, svc):
    with get_session() as s:
        e1 = svc.start("h1", 10, 100, "e", session=s)
        e2 = svc.start("h2", 10, 100, "e", session=s)
        e3 = svc.start("h3", 20, 100, "e", session=s)
        svc.record_result(e1.id, "o1", 50, session=s)
        svc.record_result(e2.id, "o2", 75, session=s)
        svc.record_result(e3.id, "o3", 99, session=s)

        results = svc.results_for(10, session=s)
        assert len(results) == 2
        assert {r.experiment_id for r in results} == {e1.id, e2.id}
        # strategy 20 keeps exactly its own single result
        assert {r.experiment_id for r in svc.results_for(20, session=s)} == {e3.id}
