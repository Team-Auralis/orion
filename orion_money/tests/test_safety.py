"""Tests for orion.safety — risk matrix, kill switch gating, approval queue,
and dry-run auto-approve. Fresh SQLite DB per test.
"""

from __future__ import annotations

import pytest

from orion.config import get_config
from orion.db import _reset_engine, get_session, init_db
from orion.models import ApprovalRequest
from orion.safety import (
    ApprovalService,
    Decision,
    RiskLevel,
    SafetyEngine,
    matrix,
)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("ORION_DATA_DIR", str(tmp_path))
    _reset_engine()
    get_config(force_reload=True)
    init_db()
    yield
    _reset_engine()


def set_mode(monkeypatch, mode: str):
    """Switch autonomy mode and reload config (fixtures call after db())."""
    monkeypatch.setenv("ORION_AUTONOMY_MODE", mode)
    get_config(force_reload=True)


# ---------------------------------------------------------------------------
# Risk matrix
# ---------------------------------------------------------------------------


def test_matrix_contains_expected_actions(db):
    m = matrix()
    for action in (
        "research",
        "browser_read",
        "create_file",
        "run_test",
        "send_message",
        "publish",
        "spend",
        "contract",
        "create_account",
    ):
        assert action in m, f"{action!r} missing from risk matrix"
    assert m["research"].level == RiskLevel.L0
    assert m["create_file"].level == RiskLevel.L1
    assert m["send_message"].level == RiskLevel.L2
    assert m["spend"].level == RiskLevel.L2
    assert m["publish"].level == RiskLevel.L3
    assert m["contract"].level == RiskLevel.L3
    assert m["create_account"].level == RiskLevel.L4


def test_decision_per_level(db):
    """Defaults: L0-L1 AUTO, L2-L3 APPROVAL, L4 BLOCKED."""
    engine = SafetyEngine()
    cases = [
        ({"action": "research"}, RiskLevel.L0, Decision.AUTO, False),
        ({"action": "run_test"}, RiskLevel.L1, Decision.AUTO, False),
        ({"action": "send_message"}, RiskLevel.L2, Decision.APPROVAL, True),
        (
            {"action": "contract", "cost_paise": 100},
            RiskLevel.L3,
            Decision.APPROVAL,
            True,
        ),
        ({"action": "create_account"}, RiskLevel.L4, Decision.BLOCKED, False),
    ]
    for action, level, decision, requires in cases:
        result = engine.evaluate(action)
        assert result.level == level, action
        assert result.decision == decision, action
        assert result.requires_approval == requires, action


def test_unknown_action_conservative_default(db):
    engine = SafetyEngine()
    result = engine.evaluate({"action": "some_unknown_thing"})
    assert result.level == RiskLevel.L2
    assert result.decision == Decision.APPROVAL
    assert result.requires_approval is True


def test_action_key_aliases(db):
    engine = SafetyEngine()
    for key in ("action", "tool", "name"):
        assert engine.evaluate({key: "send_message"}).decision == Decision.APPROVAL


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


def test_kill_switch_blocks_everything(db):
    from orion.security import KillSwitchService

    ks = KillSwitchService()
    ks.kill(
        "test emergency",
    )
    engine = SafetyEngine(kill_switch=ks)
    for action in (
        {"action": "research"},
        {"action": "send_message"},
        {"action": "spend", "amount_paise": 100},
        {"action": "create_account"},
    ):
        result = engine.evaluate(action)
        assert result.decision == Decision.BLOCKED, action
        assert result.requires_approval is False
        assert "kill switch active" in result.reasons

    ks.lift("all clear")
    assert engine.evaluate({"action": "research"}).decision == Decision.AUTO


# ---------------------------------------------------------------------------
# Financial actions route through BudgetPolicy
# ---------------------------------------------------------------------------


def test_financial_action_denied_by_budget(db):
    engine = SafetyEngine()
    # spend 2500 paise > max_single_spend (2000) => hard BLOCKED, not approval
    result = engine.evaluate({"action": "spend", "amount_paise": 2500})
    assert result.decision == Decision.BLOCKED
    assert result.requires_approval is False
    assert any("single-spend cap" in r for r in result.reasons)


def test_financial_action_missing_amount_blocked(db):
    engine = SafetyEngine()
    result = engine.evaluate({"action": "spend"})
    assert result.decision == Decision.BLOCKED
    assert any("missing amount_paise" in r for r in result.reasons)


def test_financial_action_within_budget_keeps_matrix_decision(db):
    engine = SafetyEngine()
    result = engine.evaluate({"action": "spend", "amount_paise": 500})
    assert result.decision == Decision.APPROVAL  # spend is L2 -> APPROVAL
    assert result.requires_approval is True
    assert any("budget ok" in r for r in result.reasons)
    # purchase is L3 -> APPROVAL and budget-checked too
    result2 = engine.evaluate({"action": "purchase", "cost_paise": 300})
    assert result2.decision == Decision.APPROVAL
    assert any("budget ok" in r for r in result2.reasons)


# ---------------------------------------------------------------------------
# Approval lifecycle (manual mode)
# ---------------------------------------------------------------------------


def test_approval_lifecycle(db, monkeypatch):
    set_mode(monkeypatch, "manual")
    service = ApprovalService()
    with get_session() as session:
        req = service.request(
            "spend",
            why="buy api credits",
            cost_paise=1500,
            potential_revenue_paise=5000,
            risk_level="L2",
            proposed_payload={"vendor": "acme", "qty": 1},
            destination="acme-api",
            correlation_id="corr-1",
            ttl_hours=24,
            session=session,
        )
        assert req.status == "PENDING"
        assert req.kind == "spend"
        assert req.cost_paise == 1500
        assert req.potential_revenue_paise == 5000
        assert req.risk_level == "L2"
        assert req.destination == "acme-api"
        assert req.correlation_id == "corr-1"
        assert req.payload_json is not None

        assert service.pending(session=session) == [req]

        service.approve(req.id, reason="reviewed and fine", session=session)
        updated = session.get(ApprovalRequest, req.id)
        assert updated.status == "APPROVED"
        assert updated.decision == "APPROVED"
        assert updated.decision_reason == "reviewed and fine"
        assert updated.decided_at is not None
        assert service.pending(session=session) == []


def test_approval_reject_requires_reason_and_terminal(db, monkeypatch):
    set_mode(monkeypatch, "manual")
    service = ApprovalService()
    with get_session() as session:
        req = service.request(
            "send_message", why="hi", risk_level="L2", session=session
        )
        with pytest.raises(ValueError):
            service.reject(req.id, reason="", session=session)
        service.reject(req.id, reason="spam", session=session)
        updated = session.get(ApprovalRequest, req.id)
        assert updated.status == "REJECTED"
        assert updated.decision == "REJECTED"
        # a decided request cannot be re-decided
        with pytest.raises(ValueError):
            service.approve(req.id, session=session)
        with pytest.raises(ValueError):
            service.reject(req.id, reason="again", session=session)


def test_approval_ttl_expiry(db, monkeypatch):
    set_mode(monkeypatch, "manual")
    service = ApprovalService()
    with get_session() as session:
        stale = service.request("publish", why="old", ttl_hours=0, session=session)
        fresh = service.request("publish", why="new", ttl_hours=24, session=session)
        assert service.expire_stale(session=session) == 1
        assert session.get(ApprovalRequest, stale.id).status == "EXPIRED"
        assert session.get(ApprovalRequest, fresh.id).status == "PENDING"
        # an expired request can no longer be approved
        with pytest.raises(ValueError):
            service.approve(stale.id, session=session)
        assert service.pending(session=session) == [fresh]


def test_approval_history(db, monkeypatch):
    set_mode(monkeypatch, "manual")
    service = ApprovalService()
    with get_session() as session:
        a = service.request("send_message", why="one", risk_level="L2", session=session)
        b = service.request("publish", why="two", risk_level="L3", session=session)
        service.approve(a.id, session=session)
        history = service.history(session=session)
        assert len(history) == 2
        assert {r.status for r in history} == {"APPROVED", "PENDING"}
        assert history[0].id == b.id  # newest first


def test_approve_unknown_id_raises(db, monkeypatch):
    set_mode(monkeypatch, "manual")
    service = ApprovalService()
    with get_session() as session:
        with pytest.raises(ValueError):
            service.approve(9999, session=session)


# ---------------------------------------------------------------------------
# Dry-run auto-approve
# ---------------------------------------------------------------------------


def test_dry_run_auto_approves(db, monkeypatch):
    set_mode(monkeypatch, "dry_run")  # also the shipped default
    assert get_config().autonomy.default_mode == "dry_run"
    service = ApprovalService()
    with get_session() as session:
        req = service.request(
            "spend",
            why="simulated purchase",
            cost_paise=1500,
            risk_level="L2",
            session=session,
        )
        assert req.status == "APPROVED"
        assert req.decision == "dry_run_auto_approve"
        assert req.decision_reason == "dry_run_auto_approve"
        # no PENDING record exists behind the auto-approval
        assert service.pending(session=session) == []


def test_manual_mode_not_auto_approved(db, monkeypatch):
    set_mode(monkeypatch, "manual")
    service = ApprovalService()
    with get_session() as session:
        req = service.request(
            "send_message", why="real", risk_level="L2", session=session
        )
        assert req.status == "PENDING"
        assert req.decision is None
