"""Assisted-mode money loop tests.

assisted mode makes approvals real (no auto-approve outside dry_run), gates
ledger spends behind an approved + unconsumed approval, and lets a human
record VERIFIED payout income from evidence (record_verified_payout /
confirm-payout CLI+API).
"""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from orion import ledger
from orion.cli import main as cli_main
from orion.config import get_config
from orion.db import _reset_engine, get_session, init_db
from orion.models import ApprovalRequest
from orion.safety import ApprovalService


@pytest.fixture(autouse=True)
def _no_ollama(monkeypatch):
    """Fail the model router fast (no network in tests); DEGRADED is valid."""
    monkeypatch.setenv("ORION_FORCE_NO_OLLAMA", "1")


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
def client(db):
    """TestClient whose startup lifespan seeds capital + ensures workspace."""
    from orion.api import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def set_mode(monkeypatch):
    """Force an autonomy mode (config reloaded; DB survives)."""

    def _set(mode: str):
        monkeypatch.setenv("ORION_AUTONOMY_MODE", mode)
        _reset_engine()
        get_config(force_reload=True)
        init_db()

    return _set


def _revenue_entries(session):
    return [e for e in ledger.get_ledger(session) if e.type == "REVENUE"]


# ---------------------------------------------------------------------------
# Mode semantics: only dry_run auto-approves
# ---------------------------------------------------------------------------


def test_assisted_request_stays_pending(db, set_mode):
    set_mode("assisted")
    service = ApprovalService()
    with get_session() as session:
        req = service.request(
            "spend",
            why="real spend",
            cost_paise=1500,
            risk_level="L2",
            session=session,
        )
        assert req.status == "PENDING"
        assert req.decision is None
        assert service.pending(session=session) == [req]


def test_dry_run_still_auto_approves(db, set_mode):
    set_mode("dry_run")  # also the shipped default
    service = ApprovalService()
    with get_session() as session:
        req = service.request(
            "spend", why="simulated", cost_paise=100, risk_level="L2", session=session
        )
        assert req.status == "APPROVED"
        assert req.decision == "dry_run_auto_approve"


def test_autonomous_request_stays_pending(db, set_mode):
    set_mode("autonomous")
    service = ApprovalService()
    with get_session() as session:
        req = service.request(
            "spend", why="auto", cost_paise=100, risk_level="L2", session=session
        )
        assert req.status == "PENDING"
        assert req.decision is None


# ---------------------------------------------------------------------------
# Approval gates the spend; one approval funds exactly one spend
# ---------------------------------------------------------------------------


def test_approval_funds_exactly_one_spend(client, set_mode):
    set_mode("assisted")
    # spend on POST -> PENDING, no money moves yet
    resp = client.post(
        "/api/ledger/spend",
        json={"amount_paise": 500, "category": "tooling", "reason": "assisted loop"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "PENDING"
    approval_id = resp.json()["approval"]["id"]
    assert client.get("/api/ledger").json()["summary"]["spent"] == 0

    # approve -> the sanctioned write executes exactly once
    first = client.post(f"/api/approvals/{approval_id}/approve")
    assert first.status_code == 200
    assert first.json()["entry"] is not None
    assert first.json()["approval"]["consumed_at"] is not None
    assert client.get("/api/ledger").json()["summary"]["spent"] == 500

    # a second approve cannot double-spend: it errors and no SPEND appears twice
    second = client.post(f"/api/approvals/{approval_id}/approve")
    assert second.status_code == 400
    with get_session() as s:
        spends = [e for e in ledger.get_ledger(s) if e.type == "SPEND"]
        assert len(spends) == 1
        assert spends[0].reference == f"approval:{approval_id}"
        record = s.get(ApprovalRequest, approval_id)
        assert record.status == "APPROVED"
        assert record.consumed_at is not None


# ---------------------------------------------------------------------------
# record_verified_payout — the human-evidence revenue path
# ---------------------------------------------------------------------------


def test_record_verified_payout_happy_path(db):
    with get_session() as s:
        ledger.seed_capital(s, 20000)
        entry = ledger.record_verified_payout(
            s,
            30000,
            source="upwork",
            reference="payout-1",
            evidence_ref="payout-csv:txn-99",
            confirmed_by="human",
        )
        assert entry.status == "VERIFIED"
        assert entry.verification_method == "human_confirmed_payout"
        assert entry.confidence == 1.0
        meta = json.loads(entry.metadata_json)
        assert meta["evidence_ref"] == "payout-csv:txn-99"
        assert meta["confirmed_by"] == "human"

        summary = ledger.summary(s)
        assert summary["verified_revenue"] == 30000
        assert summary["available_cash"] == 50000  # seed 20000 + payout 30000
        ledger.assert_invariant(ledger.get_balance(s))


def test_record_verified_payout_requires_evidence(db):
    with get_session() as s:
        for bad in ("", "   ", "\t\n", None):
            with pytest.raises(ValueError):
                ledger.record_verified_payout(
                    s,
                    1000,
                    source="x",
                    reference="r",
                    evidence_ref=bad,
                    confirmed_by="h",
                )
        # the refused writes never touched the ledger
        assert ledger.summary(s)["entry_count"] == 0


def test_record_verified_payout_declines_nonpositive_amount(db):
    with get_session() as s:
        with pytest.raises(ValueError):
            ledger.record_verified_payout(
                s,
                0,
                source="x",
                reference="r",
                evidence_ref="txn-1",
                confirmed_by="h",
            )


# ---------------------------------------------------------------------------
# API: POST /api/ledger/confirm-payout
# ---------------------------------------------------------------------------


def test_api_confirm_payout_verified(client):
    resp = client.post(
        "/api/ledger/confirm-payout",
        json={
            "amount_paise": 5000,
            "source": "upwork",
            "reference": "payout-api-1",
            "evidence_ref": "raptor-txn:abc123",
            "confirmed_by": "human",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "VERIFIED"
    assert body["verified"] is True
    assert body["verified_revenue_paise"] == 5000
    entry = body["entry"]
    assert entry["verification_method"] == "human_confirmed_payout"
    assert entry["confidence"] == 1.0
    assert entry["metadata"]["evidence_ref"] == "raptor-txn:abc123"

    s = client.get("/api/ledger").json()["summary"]
    assert s["verified_revenue"] == 5000
    assert s["available_cash"] == 25000  # seed 20000 + 5000


def test_api_confirm_payout_missing_or_blank_evidence_400(client):
    missing = client.post(
        "/api/ledger/confirm-payout",
        json={
            "amount_paise": 5000,
            "source": "upwork",
            "reference": "payout-api-2",
            "confirmed_by": "human",
        },
    )
    assert missing.status_code == 400

    blank = client.post(
        "/api/ledger/confirm-payout",
        json={
            "amount_paise": 5000,
            "source": "upwork",
            "reference": "payout-api-2",
            "evidence_ref": "   ",
            "confirmed_by": "human",
        },
    )
    assert blank.status_code == 400

    assert client.get("/api/ledger").json()["summary"]["verified_revenue"] == 0


# ---------------------------------------------------------------------------
# CLI: orion confirm-payout
# ---------------------------------------------------------------------------


def test_cli_confirm_payout_confirm_writes(db, monkeypatch, capsys):
    with get_session() as s:
        ledger.seed_capital(s, 20000)
    monkeypatch.setattr("builtins.input", lambda _prompt: "CONFIRM")

    rc = cli_main(
        [
            "confirm-payout",
            "--amount",
            "300.00",  # rupees -> 30000 paise internally
            "--source",
            "upwork",
            "--evidence",
            "txn-42",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "₹300.00" in out

    with get_session() as s:
        entries = _revenue_entries(s)
        assert len(entries) == 1
        assert entries[0].status == "VERIFIED"
        assert entries[0].amount_paise == 30000
        assert entries[0].verification_method == "human_confirmed_payout"
        assert entries[0].confidence == 1.0
        assert ledger.summary(s)["verified_revenue"] == 30000
        ledger.assert_invariant(ledger.get_balance(s))


def test_cli_confirm_payout_no_writes(db, monkeypatch, capsys):
    with get_session() as s:
        ledger.seed_capital(s, 20000)
    monkeypatch.setattr("builtins.input", lambda _prompt: "no")

    rc = cli_main(
        [
            "confirm-payout",
            "--amount-paise",
            "30000",
            "--source",
            "upwork",
            "--evidence",
            "txn-42",
        ]
    )
    assert rc == 1  # refused: nothing recorded
    assert "aborted" in capsys.readouterr().err

    with get_session() as s:
        assert _revenue_entries(s) == []
        assert ledger.summary(s)["verified_revenue"] == 0


def test_cli_confirm_payout_refuses_blank_evidence(db, monkeypatch, capsys):
    rc = cli_main(
        [
            "confirm-payout",
            "--amount-paise",
            "100",
            "--source",
            "upwork",
            "--evidence",
            "   ",
        ]
    )
    assert rc == 1
    with get_session() as s:
        assert ledger.summary(s)["entry_count"] == 0


def test_cli_confirm_payout_requires_exactly_one_amount(db, monkeypatch, capsys):
    for argv in (
        ["confirm-payout", "--source", "upwork", "--evidence", "txn-1"],
        [
            "confirm-payout",
            "--amount-paise",
            "100",
            "--amount",
            "1.00",
            "--source",
            "upwork",
            "--evidence",
            "txn-1",
        ],
    ):
        assert cli_main(argv) == 1
    with get_session() as s:
        assert ledger.summary(s)["entry_count"] == 0


# ---------------------------------------------------------------------------
# Regression + invariant
# ---------------------------------------------------------------------------


def test_revenue_without_verification_never_verified(client):
    """Anti-hallucination stays: plain revenue without a method is not real money."""
    resp = client.post(
        "/api/ledger/revenue",
        json={"amount_paise": 1000, "source": "gig", "reference": "gig-x"},
    )
    assert resp.status_code == 200
    assert resp.json()["verified"] is False
    assert client.get("/api/ledger").json()["summary"]["verified_revenue"] == 0


def test_full_assisted_loop_invariant_holds(client, set_mode):
    set_mode("assisted")
    # spend gated by approval
    resp = client.post(
        "/api/ledger/spend", json={"amount_paise": 500, "category": "tooling"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "PENDING"
    approval_id = resp.json()["approval"]["id"]
    approved = client.post(f"/api/approvals/{approval_id}/approve")
    assert approved.status_code == 200

    # human-confirmed payout from evidence
    resp = client.post(
        "/api/ledger/confirm-payout",
        json={
            "amount_paise": 4000,
            "source": "upwork",
            "reference": "payout-7",
            "evidence_ref": "payout-csv:2026-09.csv",
            "confirmed_by": "human",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["verified"] is True

    with get_session() as s:
        ledger.assert_invariant(ledger.get_balance(s))
    s = client.get("/api/ledger").json()["summary"]
    assert s["spent"] == 500
    assert s["verified_revenue"] == 4000
    assert s["revenue_statuses"]["VERIFIED"] == 1
