"""Tests for the ORION strategy engine (:mod:`orion.strategy`).

Lifecycle (PROPOSED -> ACTIVE), guardrail-gated activation, run aggregation,
and evidence-based ranking. Each test runs against a private SQLite DB in a
pytest tmp dir so tests never pollute the real data/orion.db.
"""

from __future__ import annotations

import json

import pytest

from orion.config import get_config
from orion.db import _reset_engine, get_session, init_db
from orion.strategy import StrategyService


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
def svc() -> StrategyService:
    return StrategyService()


def _propose(
    svc, session, name="alpha", risk="L2", min_score=50.0, max_spend=1000, allowed=None
):
    return svc.propose(
        name,
        "test strategy",
        100000,
        ["python"],
        "manual",
        risk,
        min_score,
        max_spend,
        [] if allowed is None else allowed,
        session=session,
    )


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_propose_creates_proposed(db, svc):
    with get_session() as s:
        st = _propose(svc, s)
        assert st.status == "PROPOSED"
        assert st.id is not None
        payload = json.loads(st.payload_json)
        assert payload["risk_level"] == "L2"
        assert payload["max_spend_paise"] == 1000
        assert payload["min_opportunity_score"] == 50.0
        assert payload["activation_reasons"] == []


def test_activate_succeeds_within_guardrails(db, svc):
    """L2 (APPROVAL in the matrix) + spend <= guardrail + real score tier."""
    with get_session() as s:
        st = _propose(svc, s, allowed=["L1", "L2"])
        svc.activate(st.id, session=s)
        assert st.status == "ACTIVE"
        reasons = json.loads(st.payload_json)["activation_reasons"]
        assert any("allowed" in r for r in reasons)


def test_activate_refuses_blocked_risk_level(db, svc):
    """L4 maps to BLOCKED in the policy matrix: stays PROPOSED, reason kept."""
    with get_session() as s:
        st = _propose(svc, s, risk="L4", allowed=["L4"])
        svc.activate(st.id, session=s)
        assert st.status == "PROPOSED"
        reasons = json.loads(st.payload_json)["activation_reasons"]
        assert any("BLOCKED default decision" in r for r in reasons)


def test_activate_refuses_oversized_spend(db, svc):
    """Spend above max_single_spend refuses even with an allowed risk level."""
    with get_session() as s:
        st = _propose(svc, s, max_spend=10_000_000)
        svc.activate(st.id, session=s)
        assert st.status == "PROPOSED"
        reasons = json.loads(st.payload_json)["activation_reasons"]
        assert any("exceeds max_single_spend" in r for r in reasons)


def test_activate_refuses_impossible_score_tier(db, svc):
    with get_session() as s:
        st = _propose(svc, s, min_score=150.0)
        svc.activate(st.id, session=s)
        assert st.status == "PROPOSED"
        reasons = json.loads(st.payload_json)["activation_reasons"]
        assert any("outside real score tier" in r for r in reasons)


# ---------------------------------------------------------------------------
# Execution evidence
# ---------------------------------------------------------------------------


def test_record_run_and_performance_summary(db, svc):
    """Hand-computed aggregation over a multi-run case."""
    with get_session() as s:
        st = _propose(svc, s)
        svc.activate(st.id, session=s)
        # run 1: profit 600 over 2h -> derived pph 300, failure 1/5 = 0.2
        svc.record_run(
            st.id,
            {
                "wins": 4,
                "losses": 1,
                "time_hours": 2.0,
                "profit_paise": 600,
                "revenue_paise": 900,
                "fees_paise": 100,
            },
            session=s,
        )
        # run 2: profit 800 over 4h -> derived pph 200, failure 2/4 = 0.5
        svc.record_run(
            st.id,
            {
                "wins": 2,
                "losses": 2,
                "time_hours": 4.0,
                "profit_paise": 800,
                "revenue_paise": 1200,
                "fees_paise": 200,
            },
            session=s,
        )
        perf = svc.performance_summary(st.id, session=s)

    assert perf["run_count"] == 2
    assert perf["total_profit_paise"] == 1400  # 600 + 800
    assert perf["total_revenue_paise"] == 2100  # 900 + 1200
    assert perf["total_fees_paise"] == 300  # 100 + 200
    assert perf["total_time_hours"] == 6.0  # 2 + 4
    assert perf["avg_profit_per_hour_paise"] == 250  # (300 + 200) / 2
    assert perf["win_rate"] == 0.6667  # 6 / 9, rounded
    assert perf["wins"] == 6
    assert perf["losses"] == 3


def test_record_run_derives_failure_rate_and_pph(db, svc):
    with get_session() as s:
        st = _propose(svc, s)
        run = svc.record_run(
            st.id,
            {"wins": 3, "losses": 1, "time_hours": 10.0, "profit_paise": 500},
            session=s,
        )
        assert run.profit_per_hour_paise == 50  # 500 / 10
        assert run.failure_rate == 0.25  # 1 / 4


def test_best_strategy_by_evidence_ranks_by_accumulated_pph(db, svc):
    """Ranking follows recorded evidence, never proposal order/recency."""
    with get_session() as s:
        old_strong = _propose(svc, s, name="old-strong")
        new_weak = _propose(svc, s, name="new-weak")
        newest_no_evidence = _propose(svc, s, name="newest-no-evidence")
        for st in (old_strong, new_weak, newest_no_evidence):
            svc.activate(st.id, session=s)

        # old-strong: two winning runs, total pph 1800
        svc.record_run(
            old_strong.id,
            {"wins": 1, "losses": 0, "time_hours": 1, "profit_paise": 900},
            session=s,
        )
        svc.record_run(
            old_strong.id,
            {"wins": 1, "losses": 0, "time_hours": 1, "profit_paise": 900},
            session=s,
        )
        # new-weak: proposed later but with far less evidence, total pph 100
        svc.record_run(
            new_weak.id,
            {"wins": 1, "losses": 0, "time_hours": 1, "profit_paise": 100},
            session=s,
        )
        # newest-no-evidence: zero runs — must never win

    best = svc.best_strategy_by_evidence()
    assert best is not None
    assert best.id == old_strong.id


def test_best_strategy_by_evidence_none_without_active_runs(db, svc):
    with get_session() as s:
        st = _propose(svc, s)  # still PROPOSED
        svc.record_run(
            st.id,
            {"wins": 1, "losses": 0, "time_hours": 1, "profit_paise": 500},
            session=s,
        )
    assert svc.best_strategy_by_evidence() is None  # not ACTIVE, not eligible
