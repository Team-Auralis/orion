"""Tests for the SQL-backed memory subsystem (facts/beliefs/hypotheses/evidence).

Every test runs against a private SQLite DB in a pytest tmp dir so tests never
pollute the real data/orion.db.
"""

from __future__ import annotations

import json

import pytest

from orion import memory
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
# Roundtrips
# ---------------------------------------------------------------------------


def test_roundtrip_fact(db):
    with get_session() as session:
        fact = memory.add_fact(
            session,
            "Ledger was seeded with 20000 paise",
            verified=True,
            source="ledger",
        )
        assert fact.kind == memory.MemoryKind.FACT.value
        assert fact.verified is True
        rows = memory.query(session, category="fact")
        assert len(rows) == 1
        assert rows[0].id == fact.id


def test_roundtrip_belief(db):
    with get_session() as session:
        belief = memory.add_belief(session, "UPI payouts settle in minutes", weight=0.7)
        assert belief.kind == memory.MemoryKind.BELIEF.value
        assert belief.confidence == 0.7
        rows = memory.query(session, category="belief")
        assert len(rows) == 1
        assert rows[0].id == belief.id


def test_roundtrip_hypothesis(db):
    with get_session() as session:
        hyp = memory.add_hypothesis(
            session,
            "Weekly sweep reduces double-spend risk",
            params_json={"interval": "7d"},
        )
        assert hyp.kind == memory.MemoryKind.HYPOTHESIS.value
        assert hyp.status == memory.HypothesisStatus.PROPOSED.value
        rows = memory.query(session, category="hypothesis")
        assert len(rows) == 1
        assert json.loads(rows[0].payload_json) == {"interval": "7d"}


def test_roundtrip_evidence(db):
    with get_session() as session:
        ev = memory.add_evidence(
            session,
            "Payout confirmed in bank statement",
            claim_kind="revenue-speed",
            direction=memory.EvidenceDirection.SUPPORTS.value,
            reference="ledger:9",
        )
        assert ev.kind == memory.MemoryKind.EVIDENCE.value
        assert ev.direction == memory.EvidenceDirection.SUPPORTS.value
        assert ev.reference == "ledger:9"
        assert json.loads(ev.payload_json)["claim_kind"] == "revenue-speed"
        rows = memory.query(session, category="evidence")
        assert len(rows) == 1


def test_query_text_contains_and_limit(db):
    with get_session() as session:
        memory.add_fact(session, "UPI payout confirmed in statement", verified=True)
        memory.add_belief(session, "UPI payouts are fast", weight=0.6)
        memory.add_belief(session, "Cheques are slow", weight=0.4)

        rows = memory.query(session, text_contains="upi")
        assert len(rows) == 2
        rows = memory.query(session, category="belief", text_contains="upi")
        assert len(rows) == 1
        assert rows[0].content.startswith("UPI")
        rows = memory.query(session, limit=1)
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# Anti-hallucination guards
# ---------------------------------------------------------------------------


def test_fact_requires_verification_or_evidence(db):
    with get_session() as session:
        with pytest.raises(ValueError):
            memory.add_fact(session, "unverified claim with no evidence")


def test_fact_with_evidence_reference_is_verified(db):
    with get_session() as session:
        fact = memory.add_fact(
            session,
            "Revenue received",
            evidence_reference="evidence:7",
            source="ledger",
        )
        assert fact.verified is True
        assert fact.reference == "evidence:7"


def test_belief_weight_validated(db):
    with get_session() as session:
        with pytest.raises(ValueError):
            memory.add_belief(session, "overconfident", weight=1.5)


def test_promote_refuses_without_supporting_evidence(db):
    with get_session() as session:
        hyp = memory.add_hypothesis(session, "Sweep hypothesis A")

        # No evidence rows at all.
        with pytest.raises(ValueError):
            memory.promote_hypothesis_to_fact(session, hyp.id, 999_999)

        # A contradicting evidence row must not promote.
        ev = memory.add_evidence(
            session,
            "double spends observed",
            claim_kind="sweep",
            direction=memory.EvidenceDirection.CONTRADICTS.value,
            reference="ledger:1",
        )
        with pytest.raises(ValueError):
            memory.promote_hypothesis_to_fact(session, hyp.id, ev.id)


def test_promote_succeeds_with_supporting_evidence(db):
    with get_session() as session:
        hyp = memory.add_hypothesis(
            session, "Weekly sweep works", params_json={"interval": "7d"}
        )
        ev = memory.add_evidence(
            session,
            "two sweeps ran, no double spends",
            claim_kind="sweep",
            direction=memory.EvidenceDirection.SUPPORTS.value,
            reference="ledger:5",
        )
        fact = memory.promote_hypothesis_to_fact(session, hyp.id, ev.id)
        assert fact.kind == memory.MemoryKind.FACT.value
        assert fact.verified is True
        assert fact.reference == f"evidence:{ev.id}"

        # The hypothesis is now confirmed; the fact is queryable.
        hyps = memory.query(session, category="hypothesis")
        assert hyps[0].status == memory.HypothesisStatus.CONFIRMED.value
        facts = memory.query(session, category="fact")
        assert any(f.id == fact.id for f in facts)


def test_belief_cannot_be_promoted_to_fact(db):
    """Beliefs have no promotion path: promote refuses non-hypothesis rows."""
    with get_session() as session:
        belief = memory.add_belief(session, "Belief that feels true", weight=0.9)
        with pytest.raises(ValueError):
            memory.promote_hypothesis_to_fact(session, belief.id, belief.id)


# ---------------------------------------------------------------------------
# Lifecycle & persistence
# ---------------------------------------------------------------------------


def test_update_hypothesis_persists_across_fresh_sessions(db):
    """update_hypothesis writes through to the DB: a fresh session sees it."""
    hyp_id: int | None = None
    with get_session() as session:
        hyp = memory.add_hypothesis(
            session, "Sweep hypothesis", params_json={"interval": "7d"}
        )
        hyp_id = hyp.id

    with get_session() as session:  # fresh session, same DB path
        updated = memory.update_hypothesis(
            session, hyp_id, status="confirmed", observed_result="no double spends"
        )
        assert updated.status == "confirmed"

    with get_session() as session:  # another fresh session re-reads the row
        rows = memory.query(session, category="hypothesis")
        assert len(rows) == 1
        assert rows[0].status == "confirmed"
        payload = json.loads(rows[0].payload_json or "{}")
        assert payload["interval"] == "7d"
        assert payload["observed_result"] == "no double spends"


def test_get_summary(db):
    with get_session() as session:
        memory.add_fact(session, "f1", verified=True)
        memory.add_belief(session, "b1", weight=0.5)
        memory.add_belief(session, "b2", weight=0.9)
        memory.add_hypothesis(session, "h1")
        memory.add_evidence(
            session,
            "e1",
            claim_kind="k",
            direction=memory.EvidenceDirection.SUPPORTS.value,
            reference="ledger:1",
        )
        summary = memory.get_summary(session)
        assert summary["total"] == 5
        assert summary["counts"]["fact"] == 1
        assert summary["counts"]["belief"] == 2
        assert summary["verified_facts"] == 1
        assert summary["belief_avg_weight"] == pytest.approx(0.7)
        assert summary["hypotheses_by_status"]["proposed"] == 1
        assert summary["evidence_by_direction"]["supports"] == 1
