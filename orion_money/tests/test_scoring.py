"""Tests for orion.scoring — range, weight-driven reordering, suspicious
hard-cap, and one hand-computed formula case. Pure numeric, never an LLM.
"""

from __future__ import annotations

import pytest

from orion.config import get_config
from orion.connectors import MockConnector, SourceOffer
from orion.db import _reset_engine, init_db
from orion.scoring import (
    EV_CAP_Paise,
    PAYOUT_SANITY_CAP_Paise,
    SUSPICIOUS_SCORE_CAP,
    OpportunityScorer,
    detect_suspicious,
)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("ORION_DATA_DIR", str(tmp_path))
    _reset_engine()
    get_config(force_reload=True)
    init_db()
    yield
    _reset_engine()


def _offer(**kw) -> SourceOffer:
    base = dict(
        title="clean gig",
        source="test",
        estimated_value_paise=1000,
        cost_paise=0,
        demand_hint=0.5,
        confidence=1.0,
        competition_hint=0.5,
        automation_allowed=True,
        deadline=None,
    )
    base.update(kw)
    return SourceOffer(**base)


# ---------------------------------------------------------------------------
# Range
# ---------------------------------------------------------------------------


def test_all_mock_offers_score_in_0_100(db):
    scorer = OpportunityScorer()
    for offer in MockConnector().catalog():
        b = scorer.score(offer)
        assert 0.0 <= b.score_0_100 <= 100.0, offer.title
        assert set(b.factors) == set(scorer.weights)
        for v in b.factors.values():
            assert 0.0 <= v <= 1.0, (offer.title, v)


def test_extremes_stay_in_range(db):
    scorer = OpportunityScorer()
    best = _offer(
        estimated_value_paise=EV_CAP_Paise,
        demand_hint=1.0,
        competition_hint=0.0,
        confidence=1.0,
    )
    worst = _offer(
        estimated_value_paise=0,
        cost_paise=10_000_000,
        demand_hint=0.0,
        competition_hint=1.0,
        confidence=0.0,
        automation_allowed=False,
    )
    assert 0.0 <= scorer.score(worst).score_0_100 <= 100.0
    assert scorer.score(best).score_0_100 >= 90.0
    assert scorer.score(worst).score_0_100 <= 30.0


# ---------------------------------------------------------------------------
# Hand-computed formula case
# ---------------------------------------------------------------------------


def test_hand_computed_formula_case(db):
    """value=5000, cost=0, demand=0.8, conf=0.9, comp=0.3, clean, no deadline.

    factors: expected_value = 5000/5000 = 1.0
             demand_confidence = 0.8 * 0.9 = 0.72
             competition_risk = 1 - 0.3 = 0.7
             execution_cost = 1 - 0/1000 = 1.0
             safety_compat = 1.0, time_to_revenue = 1.0,
             automation_feasibility = 1.0
    score = 100 * (30*1.0 + 15*0.72 + 10*0.7 + 10*1.0 + 15*1.0
                   + 10*1.0 + 10*1.0) / 100
          = 30 + 10.8 + 7 + 10 + 15 + 10 + 10 = 92.8
    """
    offer = _offer(
        estimated_value_paise=5000,
        cost_paise=0,
        demand_hint=0.8,
        confidence=0.9,
        competition_hint=0.3,
    )
    scorer = OpportunityScorer()  # default weights sum to 100
    b = scorer.score(offer)

    assert b.factors["expected_value"] == pytest.approx(1.0)
    assert b.factors["demand_confidence"] == pytest.approx(0.72)
    assert b.factors["competition_risk"] == pytest.approx(0.7)
    assert b.factors["execution_cost"] == pytest.approx(1.0)
    assert b.factors["safety_compat"] == pytest.approx(1.0)
    assert b.factors["time_to_revenue"] == pytest.approx(1.0)
    assert b.factors["automation_feasibility"] == pytest.approx(1.0)

    weights = get_config().scoring.as_weights()
    assert sum(weights.values()) == pytest.approx(100.0)
    hand = sum(weights[k] * b.factors[k] for k in weights)  # /100 * 100
    assert b.score_0_100 == pytest.approx(92.8, abs=0.01)
    assert b.score_0_100 == pytest.approx(hand, abs=0.01)
    assert b.suspicious is False
    assert b.rejected_reason == ""


# ---------------------------------------------------------------------------
# Weight changes reorder predictably
# ---------------------------------------------------------------------------


def test_scaling_money_weight_reorders_two_offers(db):
    """A = cheap+high-demand, B = rich+low-demand.

    Default weights (expected_value=30): B wins (money dominates).
    Scaled money weight (expected_value=1): A wins (demand dominates).
    """
    a = _offer(
        title="A cheap hot",
        estimated_value_paise=500,
        demand_hint=0.9,
        confidence=1.0,
    )
    b = _offer(
        title="B rich cold",
        estimated_value_paise=5000,
        demand_hint=0.2,
        confidence=1.0,
    )
    default = OpportunityScorer()
    scaled = OpportunityScorer(weights={"expected_value": 1})

    sa, sb = default.score(a).score_0_100, default.score(b).score_0_100
    assert sb > sa  # money-heavy default favours the rich offer

    sa2, sb2 = scaled.score(a).score_0_100, scaled.score(b).score_0_100
    assert sa2 > sb2  # order flips when the money weight is scaled down
    assert sa2 > sa and sb2 < sb


def test_unknown_weight_rejected(db):
    with pytest.raises(ValueError):
        OpportunityScorer(weights={"bogus_factor": 10})


# ---------------------------------------------------------------------------
# Suspicious detection: hard cap + rejection reason
# ---------------------------------------------------------------------------


def test_scam_baits_hard_capped_and_flagged(db):
    scorer = OpportunityScorer()
    scams = [o for o in MockConnector().catalog() if detect_suspicious(o)]
    assert len(scams) >= 2
    for offer in scams:
        b = scorer.score(offer)
        assert b.suspicious is True, offer.title
        assert b.suspicious_reason, offer.title
        assert b.rejected_reason == b.suspicious_reason
        assert b.score_0_100 <= SUSPICIOUS_SCORE_CAP
        assert b.score_0_100 <= 10.0


def test_scam_markers_hard_coded(db):
    """Each planted scam keyword is caught without any LLM."""
    cases = [
        ("Guaranteed returns with zero risk", "guaranteed_returns"),
        ("Pay 500 to unlock the job", "pay_to_unlock"),
        ("Crypto trader guaranteed profit", "guaranteed_profit"),
        ("Get rich quick with our system", "get_rich"),
        ("Double your money this week", "double_your_money"),
    ]
    for text, marker in cases:
        reason = detect_suspicious(_offer(title=text, estimated_value_paise=100))
        assert reason, text
        assert marker in reason, (text, reason)


def test_payout_sanity_ratio_flagged(db):
    """A huge payout on a trivial effort is suspicious even without keywords."""
    reason = detect_suspicious(
        _offer(
            title="do a tiny task",
            estimated_value_paise=PAYOUT_SANITY_CAP_Paise + 1,
        )
    )
    assert "payout-effort implausible" in reason
    # clean small offer passes
    assert (
        detect_suspicious(_offer(title="do a tiny task", estimated_value_paise=4000))
        == ""
    )


def test_suspicious_safety_factor_zero(db):
    b = OpportunityScorer().score(
        _offer(title="crypto guaranteed returns", estimated_value_paise=100)
    )
    assert b.suspicious is True
    assert b.factors["safety_compat"] == 0.0  # automation_allowed & !suspicious
