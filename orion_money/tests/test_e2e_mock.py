"""End-to-end mock lifecycle test for ORION (offline, no network).

Walks the full dry-run path a fresh install takes: seed capital, discover
and score offers from the mock connector, propose/activate a strategy,
dry-run auto-approval, guardrailed spend, verified revenue, kill switch
gating, and ledger persistence across a simulated process restart.
"""

from __future__ import annotations

import pytest

from orion import ledger
from orion.config import get_config
from orion.connectors import MockConnector
from orion.db import _reset_engine, get_session, init_db
from orion.discovery import DiscoveryService, OpportunityStatus
from orion.safety import ApprovalService, Decision, SafetyEngine
from orion.scoring import OpportunityScorer, detect_suspicious
from orion.security import KillSwitchService
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


def test_mock_end_to_end(db):
    catalog = MockConnector().catalog()
    assert len(catalog) >= 10  # mock catalog is the offline offer source

    with get_session() as session:
        # --- 1. seed capital (idempotent) -------------------------------
        ledger.seed_capital(session, 20000)
        ledger.seed_capital(session, 20000)  # second seed adds nothing
        balance = ledger.get_balance(session)
        assert balance["capital"] == 20000
        assert balance["available_cash"] == 20000

        # --- 2. discovery: scan + score every offer ---------------------
        new_rows = DiscoveryService().scan(session)
        assert len(new_rows) == len(catalog)
        assert len(new_rows) >= 10

        scorer = OpportunityScorer()
        scams = [o for o in catalog if detect_suspicious(o)]
        assert scams, "mock catalog must contain at least one scam bait"
        for offer in catalog:
            row = scorer.score_opportunity_from_offer(offer, session)
            assert row.score_0_100 is not None
            assert 0.0 <= row.score_0_100 <= 100.0
            if offer in scams:
                # suspicious offers are rejected at scoring, never pending
                assert row.suspicious is True
                assert row.status == OpportunityStatus.REJECTED.value
            else:
                assert row.suspicious is False
                assert row.status == OpportunityStatus.SCORED.value

        statuses = {
            r.status for r in DiscoveryService().list_opportunities(session=session)
        }
        assert OpportunityStatus.PENDING.value not in statuses
        assert OpportunityStatus.REJECTED.value in statuses

        # --- 3. strategy: propose -> activate ---------------------------
        svc = StrategyService()
        strategy = svc.propose(
            "micro-affiliate-mock",
            "offline e2e strategy",
            50000,
            ["python"],
            "manual",
            "L2",
            50.0,
            1000,
            ["L1", "L2"],
            session=session,
        )
        assert strategy.status == "PROPOSED"
        svc.activate(strategy.id, session=session)
        assert strategy.status == "ACTIVE"

        # --- 4. approval: dry run auto-approves, no ledger side effect --
        entries_before = ledger.summary(session)["entry_count"]
        approvals = ApprovalService()
        approval = approvals.request(
            "spend",
            why="e2e test spend",
            cost_paise=100,
            risk_level="L2",
            proposed_payload={"category": "tooling", "amount_paise": 100},
            destination="mock-vendor",
            session=session,
        )
        assert approval.status == "APPROVED"
        assert approval.decision == "dry_run_auto_approve"
        assert ledger.summary(session)["entry_count"] == entries_before

        # --- 5. safety engine: spend allowed pre-kill -------------------
        engine = SafetyEngine()
        verdict = engine.evaluate(
            {"action": "spend", "amount_paise": 100, "category": "tooling"},
            session=session,
        )
        assert verdict.decision == Decision.APPROVAL
        assert verdict.requires_approval is True

        # --- 6. ledger: spend within guardrails -------------------------
        ledger.spend(session, 100, destination="mock-vendor")

        # --- 7. verified revenue ---------------------------------------
        entry = ledger.record_revenue(
            session,
            1500,
            source="mock-gig",
            reference="e2e-rev-1",
            verification_method="payout-confirmed",
            confidence=0.95,
        )
        assert entry.status == "VERIFIED"

        summary = ledger.summary(session)
        assert summary["spent"] == 100
        assert summary["verified_revenue"] == 1500
        assert summary["pending_revenue"] == 0
        assert summary["net_profit"] == 1400  # 1500 - 100
        assert summary["net_profit"] > 0
        assert summary["entry_count"] == 3  # seed + spend + revenue

        # --- 8. invariant holds after every write -----------------------
        ledger.assert_invariant(ledger.get_balance(session))

        # --- 9. kill switch blocks everything, lift restores ------------
        kill = KillSwitchService()
        assert kill.kill(reason="e2e drill", session=session)["active"] is True
        blocked = engine.evaluate(
            {"action": "spend", "amount_paise": 100, "category": "tooling"},
            session=session,
        )
        assert blocked.decision == Decision.BLOCKED
        assert "kill switch active" in blocked.reasons
        assert kill.lift(reason="drill over", session=session)["active"] is False
        restored = engine.evaluate(
            {"action": "spend", "amount_paise": 100, "category": "tooling"},
            session=session,
        )
        assert restored.decision != Decision.BLOCKED

        before_restart = {
            k: summary[k]
            for k in (
                "capital",
                "available_cash",
                "reserved_cash",
                "spent",
                "verified_revenue",
                "pending_revenue",
                "net_profit",
                "entry_count",
            )
        }

    # --- 10. persistence: simulate a process restart -------------------
    _reset_engine()
    init_db()
    with get_session() as session:
        after = ledger.summary(session)
        ledger.assert_invariant(ledger.get_balance(session))
    for key, value in before_restart.items():
        assert after[key] == value, f"{key} did not survive restart"
