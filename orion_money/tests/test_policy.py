"""Tests for BudgetPolicy — the hard money guardrails.

Proves budget bypass is impossible: single-spend cap, daily accumulation,
total-loss cap (cumulative spend - cumulative verified revenue), and
category bans (borrowing / leverage / gambling / secret). Each test runs
against a private SQLite DB in a pytest tmp dir.
"""

from __future__ import annotations

import pytest

from orion import ledger
from orion.config import get_config
from orion.db import _reset_engine, get_session, init_db
from orion.models import LedgerEntry, utc_now_iso
from orion.policy import BudgetPolicy, PolicyDecision


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Point ORION at a temp data dir and bootstrap a fresh database."""
    monkeypatch.setenv("ORION_DATA_DIR", str(tmp_path))
    _reset_engine()
    get_config(force_reload=True)
    init_db()
    yield
    _reset_engine()


def add_spend(session, amount_paise, day=None):
    """Insert a SPEND entry directly (bypasses ledger.spend's own caps so a
    test can construct arbitrary ledger states; day controls created_at)."""
    entry = LedgerEntry(
        type=ledger.EventType.SPEND,
        amount_paise=amount_paise,
        source="orion",
        destination="test",
        status="COMPLETED",
        created_at=day or utc_now_iso(),
        updated_at=day or utc_now_iso(),
    )
    session.add(entry)
    session.flush()
    return entry


def seed(session, amount=20000):
    ledger.seed_capital(session, amount)


# ---------------------------------------------------------------------------
# Single-spend cap
# ---------------------------------------------------------------------------


def test_spend_exactly_at_single_cap_passes(db):
    with get_session() as session:
        seed(session)
        policy = BudgetPolicy()
        decision = policy.can_spend(2000, "tooling", session=session)
        assert decision.allow is True
        assert decision.remaining_single == 0  # cap fully consumed
        assert "budget ok" in decision.reasons


def test_spend_over_single_cap_denied_even_with_full_budget(db):
    with get_session() as session:
        seed(session)
        policy = BudgetPolicy()
        decision = policy.can_spend(2001, "tooling", session=session)
        assert decision.allow is False
        assert any("single-spend cap exceeded" in r for r in decision.reasons)
        assert decision.remaining_single == 0


# ---------------------------------------------------------------------------
# Daily accumulation (sum of today's SPEND events)
# ---------------------------------------------------------------------------


def test_budget_bypass_attempt_denied_by_daily_cap(db):
    """Spend near the daily cap via the real path, then attempt an
    over-cap spend: the bypass attempt must be denied."""
    with get_session() as session:
        seed(session)
        ledger.spend(session, 2000, destination="a")
        ledger.spend(session, 2000, destination="b")  # today = 4000 paise
        policy = BudgetPolicy()
        decision = policy.can_spend(1500, "tooling", session=session)
        assert decision.allow is False
        assert any("daily-spend cap exceeded" in r for r in decision.reasons)
        assert decision.remaining_daily == 0
        # single cap has headroom left (1500 <= 2000), so the ONLY reason
        # must be the daily cap.
        assert not any("single-spend cap" in r for r in decision.reasons)


def test_spend_up_to_daily_cap_passes(db):
    with get_session() as session:
        seed(session)
        ledger.spend(session, 2000, destination="a")
        ledger.spend(session, 2000, destination="b")
        policy = BudgetPolicy()
        decision = policy.can_spend(1000, "tooling", session=session)
        assert decision.allow is True
        assert decision.remaining_daily == 0  # 5000 - 4000 - 1000


def test_daily_cap_is_per_day_not_cumulative(db):
    """Spends on a different day do not count toward 'today'."""
    with get_session() as session:
        seed(session)
        add_spend(session, 4900, day="2026-09-01T10:00:00+00:00")
        policy = BudgetPolicy()
        decision = policy.can_spend(2000, "tooling", session=session)
        assert decision.allow is True  # yesterday's spend doesn't bind today
        decision2 = policy.can_spend(
            2000, "tooling", when="2026-09-01", session=session
        )
        assert decision2.allow is False  # but it binds that day


# ---------------------------------------------------------------------------
# Total-loss cap: cumulative spend - cumulative VERIFIED revenue
# ---------------------------------------------------------------------------


def test_total_loss_cap_denies_over_cap(db):
    """10x1900 spread across days = 19000 loss; a fresh 2000 breaks the cap."""
    with get_session() as session:
        seed(session)
        for i in range(10):
            add_spend(session, 1900, day=f"2026-09-{i + 1:02d}T10:00:00+00:00")
        policy = BudgetPolicy()
        decision = policy.can_spend(2000, "tooling", session=session)
        assert decision.allow is False
        assert any("total-loss cap exceeded" in r for r in decision.reasons)
        assert decision.remaining_loss == 0


def test_verified_revenue_offsets_loss(db):
    """Formula: total_loss = spend - verified_revenue. Verified revenue
    restores headroom; PENDING/ESTIMATED revenue does not."""
    with get_session() as session:
        seed(session)
        for i in range(10):
            add_spend(session, 1900, day=f"2026-09-{i + 1:02d}T10:00:00+00:00")

        # PENDING revenue (method but confidence < 0.9) must NOT offset loss.
        ledger.record_revenue(
            session,
            10000,
            source="gig",
            reference="pending-1",
            verification_method="payout",
            confidence=0.5,
        )
        policy = BudgetPolicy()
        assert policy.can_spend(2000, "tooling", session=session).allow is False

        # VERIFIED revenue now offsets the loss: 19000 - 5000 = 14000.
        ledger.record_revenue(
            session,
            5000,
            source="gig",
            reference="verified-1",
            verification_method="payout-confirmed",
            confidence=0.95,
        )
        decision = policy.can_spend(2000, "tooling", session=session)
        assert decision.allow is True
        assert decision.remaining_loss == 20000 - 14000 - 2000  # 4000


# ---------------------------------------------------------------------------
# Category bans
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("category", ["borrowing", "leverage", "gambling"])
def test_banned_categories_denied_regardless_of_amount(db, category):
    with get_session() as session:
        seed(session)
        policy = BudgetPolicy()
        for amount in (1, 500, 2000):
            decision = policy.can_spend(amount, category, session=session)
            assert decision.allow is False, f"{category} {amount} must be denied"
            assert any(category in r for r in decision.reasons)
        # category check is case-insensitive
        assert policy.can_spend(1, category.upper(), session=session).allow is False


def test_secret_spend_hard_banned(db):
    with get_session() as session:
        seed(session)
        policy = BudgetPolicy()
        decision = policy.can_spend(1, "secret", session=session)
        assert decision.allow is False
        assert any("secret" in r and "hard-banned" in r for r in decision.reasons)


# ---------------------------------------------------------------------------
# Legitimate spends pass
# ---------------------------------------------------------------------------


def test_legitimate_spend_passes(db):
    with get_session() as session:
        seed(session)
        policy = BudgetPolicy()
        decision = policy.can_spend(1500, "tooling", session=session)
        assert decision.allow is True
        assert decision.remaining_single == 500
        assert decision.remaining_daily == 5000 - 1500  # 3500
        assert decision.remaining_loss == 20000 - 1500  # 18500
        # every money value is integer paise
        for value in (
            decision.remaining_single,
            decision.remaining_daily,
            decision.remaining_loss,
        ):
            assert isinstance(value, int)


def test_invalid_amount_denied(db):
    with get_session() as session:
        seed(session)
        policy = BudgetPolicy()
        assert policy.can_spend(0, "tooling", session=session).allow is False
        assert policy.can_spend(-5, "tooling", session=session).allow is False
        assert policy.can_spend(1500.5, "tooling", session=session).allow is False
        assert policy.can_spend(True, "tooling", session=session).allow is False


# ---------------------------------------------------------------------------
# Reporters
# ---------------------------------------------------------------------------


def test_remaining_budget_reporters(db):
    with get_session() as session:
        seed(session)
        ledger.spend(session, 2000, destination="a")
        ledger.spend(session, 1000, destination="b")
        policy = BudgetPolicy()
        assert policy.remaining_daily_budget(session=session) == 2000  # 5000-3000
        assert policy.remaining_loss_budget(session=session) == 17000  # 20000-3000


def test_guardrail_summary(db):
    with get_session() as session:
        seed(session)
        ledger.spend(session, 1000, destination="a")
        policy = BudgetPolicy()
        summary = policy.guardrail_summary(session=session)
        assert summary["max_single_spend"] == 2000
        assert summary["max_daily_spend"] == 5000
        assert summary["max_total_loss"] == 20000
        assert summary["borrowing_allowed"] is False
        assert summary["leverage_allowed"] is False
        assert summary["gambling_allowed"] is False
        assert summary["secret_spending_allowed"] is False
        assert summary["spent_today"] == 1000
        assert summary["total_loss"] == 1000
        assert summary["remaining_daily"] == 4000
        assert summary["remaining_loss"] == 19000


def test_budget_policy_decisions_are_pure(db):
    """Same ledger state + config => same decision, across instances."""
    with get_session() as session:
        seed(session)
        ledger.spend(session, 1200, destination="a")
        first = BudgetPolicy().can_spend(800, "tooling", session=session)
        second = BudgetPolicy().can_spend(800, "tooling", session=session)
        assert isinstance(first, PolicyDecision)
        assert first == second
