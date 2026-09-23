"""Tests for the ORION ledger and DB bootstrap.

Each test runs against a private SQLite DB in a pytest tmp dir so tests never
pollute the real data/orion.db.
"""

from __future__ import annotations

import random

import pytest

from orion import ledger
from orion.config import get_config
from orion.db import _reset_engine, get_session, init_db


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Point ORION at a temp data dir and bootstrap a fresh database."""
    monkeypatch.setenv("ORION_DATA_DIR", str(tmp_path))
    _reset_engine()
    get_config(force_reload=True)
    init_db()
    yield
    _reset_engine()


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def test_init_db_idempotent(db):
    """Calling init_db() twice must not error and records one schema row."""
    init_db()  # second call
    with get_session() as session:
        from orion.models import SchemaVersion

        rows = session.query(SchemaVersion).all()
        assert len(rows) == 1
        assert rows[0].version == 2


# ---------------------------------------------------------------------------
# Basic flows
# ---------------------------------------------------------------------------


def test_deposit_seeds_capital(db):
    with get_session() as session:
        ledger.seed_capital(session, 20000)
        balance = ledger.get_balance(session)
        assert balance["capital"] == 20000
        assert balance["available_cash"] == 20000
        assert balance["reserved_cash"] == 0

        # Idempotent: a second seed adds nothing.
        ledger.seed_capital(session, 20000)
        balance = ledger.get_balance(session)
        assert balance["capital"] == 20000
        assert balance["available_cash"] == 20000


def test_reserve_then_spend(db):
    with get_session() as session:
        ledger.seed_capital(session, 20000)
        ledger.reserve(session, 1500, destination="tool-subscription")
        balance = ledger.get_balance(session)
        assert balance["available_cash"] == 18500
        assert balance["reserved_cash"] == 1500

        ledger.spend(session, 1500, destination="tool-subscription")
        balance = ledger.get_balance(session)
        assert balance["reserved_cash"] == 0
        assert balance["spent"] == 1500
        assert balance["available_cash"] == 18500
        assert ledger.summary(session)["net_profit"] == -1500


def test_expense_reduces_available(db):
    with get_session() as session:
        ledger.seed_capital(session, 20000)
        ledger.spend(session, 1200, destination="api-credits")
        balance = ledger.get_balance(session)
        assert balance["available_cash"] == 18800
        assert balance["spent"] == 1200


def test_spend_exceeding_available_rejected(db):
    with get_session() as session:
        ledger.seed_capital(session, 1000)
        with pytest.raises(ValueError):
            ledger.spend(session, 2000, destination="too-much")


# ---------------------------------------------------------------------------
# Revenue
# ---------------------------------------------------------------------------


def test_revenue_not_verified_without_evidence(db):
    with get_session() as session:
        ledger.seed_capital(session, 20000)
        entry = ledger.record_revenue(session, 1000, source="gig", reference="gig-1")
        assert entry.status == ledger.RevenueStatus.ESTIMATED
        balance = ledger.get_balance(session)
        assert balance["verified_revenue"] == 0
        assert balance["pending_revenue"] == 1000
        assert balance["available_cash"] == 20000  # unrealized revenue untouched


def test_revenue_pending_with_low_confidence(db):
    with get_session() as session:
        ledger.seed_capital(session, 20000)
        entry = ledger.record_revenue(
            session,
            1000,
            source="gig",
            reference="gig-2",
            verification_method="ledger",
            confidence=0.5,
        )
        assert entry.status == ledger.RevenueStatus.PENDING


def test_revenue_verified_with_evidence(db):
    with get_session() as session:
        ledger.seed_capital(session, 20000)
        entry = ledger.record_revenue(
            session,
            1000,
            source="gig",
            reference="gig-3",
            verification_method="payout-confirmed",
            confidence=0.95,
        )
        assert entry.status == ledger.RevenueStatus.VERIFIED
        balance = ledger.get_balance(session)
        assert balance["verified_revenue"] == 1000
        assert balance["available_cash"] == 21000


# ---------------------------------------------------------------------------
# Refund / dispute reconstruction
# ---------------------------------------------------------------------------


def test_refund_reconstruction(db):
    """A refund reverses the spend: net spent drops, refunds are reported."""
    with get_session() as session:
        ledger.seed_capital(session, 20000)
        ledger.reserve(session, 1500, destination="campaign")
        ledger.spend(session, 1500, destination="campaign")

        ledger.record_refund(session, 600, source="campaign")
        balance = ledger.get_balance(session)
        assert balance["spent"] == 900
        assert balance["refunds"] == 600
        assert balance["available_cash"] == 18500  # unchanged by the refund
        assert (
            ledger.summary(session)["net_profit"] == -300
        )  # -900 spent + 600 refunded

        types = [e.type for e in ledger.get_ledger(session)]
        assert types[0] == ledger.EventType.REFUND
        assert ledger.EventType.SPEND in types


def test_dispute_flow(db):
    """A disputed verified revenue is retracted from cash and recognition."""
    with get_session() as session:
        ledger.seed_capital(session, 20000)
        revenue = ledger.record_revenue(
            session,
            1000,
            source="gig",
            reference="gig-4",
            verification_method="payout-confirmed",
            confidence=0.95,
        )
        assert ledger.get_balance(session)["available_cash"] == 21000

        ledger.record_dispute(
            session, 1000, revenue_reference="gig-4", reason="client-chargeback"
        )
        balance = ledger.get_balance(session)
        assert balance["verified_revenue"] == 0
        assert balance["available_cash"] == 20000

        # audit trail: the original revenue entry is now DISPUTED
        fresh = ledger.get_ledger(session, limit=20)
        revenue_row = next(e for e in fresh if e.id == revenue.id)
        assert revenue_row.status == ledger.RevenueStatus.DISPUTED


def test_dispute_requires_verified_revenue(db):
    with get_session() as session:
        ledger.seed_capital(session, 20000)
        ledger.record_revenue(session, 1000, source="gig", reference="gig-5")
        with pytest.raises(ValueError):
            ledger.record_dispute(session, 1000, revenue_reference="gig-5")


# ---------------------------------------------------------------------------
# Fees & adjustments
# ---------------------------------------------------------------------------


def test_fee_charges_verified_revenue(db):
    with get_session() as session:
        ledger.seed_capital(session, 20000)
        ledger.record_revenue(
            session,
            5000,
            source="platform",
            reference="rev-1",
            verification_method="payout",
            confidence=1.0,
        )
        ledger.record_fee(session, 500, source="platform-fee", reference="rev-1")
        balance = ledger.get_balance(session)
        assert balance["verified_revenue"] == 4500
        assert balance["fees"] == 500
        assert balance["available_cash"] == 25000  # fee never touched cash
        assert ledger.summary(session)["net_profit"] == 4000


def test_fee_exceeding_revenue_rejected(db):
    with get_session() as session:
        ledger.seed_capital(session, 20000)
        with pytest.raises(ValueError):
            ledger.record_fee(session, 100, source="platform-fee")


def test_adjustment_signed(db):
    with get_session() as session:
        ledger.seed_capital(session, 20000)
        ledger.record_adjustment(session, 500, source="ops", reference="found-money")
        assert ledger.get_balance(session)["capital"] == 20500
        ledger.record_adjustment(session, -300, source="ops", reference="book-cleanup")
        assert ledger.get_balance(session)["capital"] == 20200


# ---------------------------------------------------------------------------
# Invariant under randomized load
# ---------------------------------------------------------------------------


def test_invariant_survives_100_randomized_ops(db):
    """Random deposits/expenses/revenues within guardrails keep the equation."""
    from orion.models import utc_now_iso

    rng = random.Random(20260923)
    with get_session() as session:
        ledger.seed_capital(session, 20000)
        guardrails = get_config().risk_guardrails

        for _ in range(100):
            balance = ledger.get_balance(session)
            op = rng.choice(["deposit", "expense", "revenue"])
            if op == "deposit":
                ledger.deposit(session, rng.randint(1, 10_000), source="external")
            elif op == "expense":
                # Respect every guardrail the ledger enforces so random ops
                # always stay "within guardrails" (single/daily/total-loss).
                today = utc_now_iso()[:10]
                today_spent = sum(
                    e.amount_paise
                    for e in ledger.get_ledger(session)
                    if e.type == ledger.EventType.SPEND and e.created_at[:10] == today
                )
                ceiling = min(
                    guardrails.max_single_spend,
                    balance["available_cash"],
                    guardrails.max_daily_spend - today_spent,
                    guardrails.max_total_loss - (balance["spent"] - balance["refunds"]),
                )
                if ceiling > 0:
                    ledger.spend(
                        session, rng.randint(1, ceiling), destination="random-expense"
                    )
            else:
                ledger.record_revenue(
                    session,
                    rng.randint(1, 5_000),
                    source="random-source",
                    reference=f"rand-{_}",
                    verification_method="test-check",
                    confidence=0.95,
                )
            ledger.assert_invariant(ledger.get_balance(session))

        final = ledger.get_balance(session)
        assert final["available_cash"] >= 0
        ledger.assert_invariant(final)


def test_money_is_integer_paise(db):
    """Every visible balance value must be an int (no floats anywhere)."""
    with get_session() as session:
        ledger.seed_capital(session, 20000)
        summary = ledger.summary(session)
        money_keys = [
            "capital",
            "available_cash",
            "reserved_cash",
            "spent",
            "revenue",
            "verified_revenue",
            "pending_revenue",
            "total_revenue",
            "fees",
            "refunds",
            "net_profit",
        ]
        for key in money_keys:
            assert isinstance(summary[key], int), (
                f"{key} is not an int: {summary[key]!r}"
            )
