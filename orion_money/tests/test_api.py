"""Tests for the FastAPI layer — status/health, ledger money endpoints,
approvals, kill switch, SSE activity stream, scans, strategies, jobs.

Each test runs against a private SQLite DB in a pytest tmp dir (same
fixture pattern as test_ledger.py); the app's startup lifespan seeds the
capital once per DB. The model router is forced DEGRADED (no network).
"""

from __future__ import annotations

import time

import pytest
from starlette.testclient import TestClient

from orion import events
from orion.config import get_config
from orion.db import _reset_engine, get_session, init_db
from orion.ledger import fmt_paise, get_ledger


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
    """Force a non-dry-run autonomy mode (config reloaded; DB survives)."""

    def _set(mode: str):
        monkeypatch.setenv("ORION_AUTONOMY_MODE", mode)
        _reset_engine()
        get_config(force_reload=True)
        init_db()

    return _set


def _available(client) -> int:
    return client.get("/api/ledger").json()["summary"]["available_cash"]


# ---------------------------------------------------------------------------
# Status / health / formatting
# ---------------------------------------------------------------------------


def test_status_returns_mode_and_autonomy_map(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "dry_run"
    assert body["kill_switch_active"] is False
    assert body["model_status"] == "DEGRADED"
    assert body["db_ok"] is True
    assert body["autonomy"]["research"] == "ENABLED"
    assert body["autonomy"]["local_files"] == "ENABLED"
    assert body["autonomy"]["messaging"] == "APPROVAL"
    assert body["autonomy"]["purchases"] == "APPROVAL"
    assert body["autonomy"]["financial"] == "APPROVAL"
    assert body["autonomy"]["high_impact"] == "BLOCKED"


def test_health_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["checks"]["db"] == "pass"
    assert body["checks"]["model"] == "degraded"  # tolerated


def test_fmt_paise():
    assert fmt_paise(120000) == "₹1,200.00"
    assert fmt_paise(123456) == "₹1,234.56"
    assert fmt_paise(1) == "₹0.01"
    assert fmt_paise(0) == "₹0.00"
    assert fmt_paise(-500) == "-₹5.00"


# ---------------------------------------------------------------------------
# Revenue
# ---------------------------------------------------------------------------


def test_revenue_verified_with_evidence(client):
    resp = client.post(
        "/api/ledger/revenue",
        json={
            "amount_paise": 1000,
            "source": "gig",
            "reference": "gig-api-1",
            "verification_method": "payout-confirmed",
            "confidence": 0.95,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "VERIFIED"
    assert body["entry"]["amount_paise"] == 1000
    assert body["entry"]["amount_formatted"] == "₹10.00"
    assert body["verified_revenue_paise"] == 1000

    ledger_body = client.get("/api/ledger").json()
    s = ledger_body["summary"]
    assert s["verified_revenue"] == 1000
    assert s["available_cash"] == 21000  # seed 20000 + 1000
    assert s["verified_revenue_formatted"] == "₹10.00"
    assert s["capital_formatted"] == "₹200.00"
    assert any(e["type"] == "REVENUE" for e in ledger_body["entries"])


def test_revenue_without_verification_never_recognized(client):
    resp = client.post(
        "/api/ledger/revenue",
        json={"amount_paise": 1000, "source": "gig", "reference": "gig-api-2"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("PENDING", "ESTIMATED")
    assert body["verified"] is False
    # anti-hallucination: unverified revenue never touches real money
    s = client.get("/api/ledger").json()["summary"]
    assert s["verified_revenue"] == 0
    assert s["available_cash"] == 20000


def test_ledger_entries_have_formatted_money_pairs(client):
    s = client.get("/api/ledger").json()["summary"]
    for key in (
        "capital",
        "available_cash",
        "reserved_cash",
        "spent",
        "revenue",
        "fees",
        "refunds",
        "net_profit",
    ):
        assert isinstance(s[key], int)
        assert s[f"{key}_formatted"].startswith("₹")


# ---------------------------------------------------------------------------
# Spend: dry-run never spends; real money moves only via approval
# ---------------------------------------------------------------------------


def test_spend_dry_run_auto_approves_without_moving_money(client):
    resp = client.post(
        "/api/ledger/spend",
        json={"amount_paise": 500, "category": "tooling", "reason": "dry-run sim"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "SIMULATED"
    assert body["simulated"] is True
    approval = body["approval"]
    assert approval is not None
    assert approval["status"] == "APPROVED"
    assert approval["decision"] == "dry_run_auto_approve"
    assert body["entry"] is None
    # dry-run must NEVER spend
    s = client.get("/api/ledger").json()["summary"]
    assert s["available_cash"] == 20000
    assert s["spent"] == 0


def test_spend_approval_flow_in_manual_mode_moves_money_only_on_approve(
    db, client, set_mode
):
    set_mode("manual")
    assert _available(client) == 20000  # startup seed survived the reset

    # spend requires approval in manual mode -> PENDING, no money moved yet
    resp = client.post(
        "/api/ledger/spend",
        json={"amount_paise": 500, "category": "tooling", "reason": "api test"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "PENDING"
    approval_id = body["approval"]["id"]
    assert _available(client) == 20000

    # approve -> the sanctioned write executes
    resp = client.post(f"/api/approvals/{approval_id}/approve")
    assert resp.status_code == 200
    assert resp.json()["approval"]["status"] == "APPROVED"

    assert _available(client) == 19500
    s = client.get("/api/ledger").json()["summary"]
    assert s["available_cash"] == 19500
    assert s["spent"] == 500
    assert s["reserved_cash"] == 0

    # reject flow: another pending spend is rejected and never moves money
    resp = client.post(
        "/api/ledger/spend", json={"amount_paise": 300, "category": "tooling"}
    )
    approval_id2 = resp.json()["approval"]["id"]
    resp = client.post(f"/api/approvals/{approval_id2}/reject", json={"reason": "no"})
    assert resp.status_code == 200
    assert resp.json()["approval"]["status"] == "REJECTED"
    assert _available(client) == 19500

    # the ledger write happened exactly once (the approved SPEND)
    with get_session() as s:
        spends = [e for e in get_ledger(s) if e.type == "SPEND"]
    assert len([e for e in spends if e.reference == f"approval:{approval_id}"]) == 1


def test_spend_blocked_by_policy_is_403(client):
    # kill switch engaged -> SafetyEngine hard-blocks with reasons
    client.post("/api/kill", json={"reason": "stop everything"})
    resp = client.post(
        "/api/ledger/spend", json={"amount_paise": 100, "category": "tooling"}
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"] == "blocked_by_policy"
    assert any("kill switch" in r.lower() for r in body["reasons"])


def test_kill_switch_blocks_and_lifts(client):
    resp = client.post("/api/kill", json={"reason": "test stop"})
    assert resp.status_code == 200
    assert resp.json()["active"] is True
    assert client.get("/api/status").json()["kill_switch_active"] is True

    client.post("/api/kill/lift", json={"reason": "all clear"})
    assert client.get("/api/status").json()["kill_switch_active"] is False


# ---------------------------------------------------------------------------
# Approvals listing
# ---------------------------------------------------------------------------


def test_approvals_list_pending(client, set_mode):
    set_mode("manual")
    client.post("/api/ledger/spend", json={"amount_paise": 200, "category": "tooling"})
    row = client.get("/api/approvals", params={"status": "pending"}).json()
    assert row["count"] >= 1
    assert all(a["status"] == "PENDING" for a in row["approvals"])
    assert row["approvals"][0]["cost_formatted"] == "₹2.00"


# ---------------------------------------------------------------------------
# SSE activity stream
# ---------------------------------------------------------------------------


def test_activity_sse_streams_events(db):
    """Real HTTP smoke test: uvicorn in a thread (TestClient cannot handle
    non-terminating streams with this httpx pairing)."""
    import threading

    import uvicorn
    from orion.api import app

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 10
        while not server.started:
            assert time.time() < deadline, "uvicorn failed to start"
            time.sleep(0.02)
        port = server.servers[0].sockets[0].getsockname()[1]
        base = f"http://127.0.0.1:{port}"

        import httpx

        # Published before the stream opens -> arrives via history replay.
        events.publish("test_event", agent="test-agent", metadata={"n": 42})
        received: list[str] = []
        with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0)) as hx:
            with hx.stream("GET", f"{base}/api/activity") as resp:
                assert resp.status_code == 200
                assert "text/event-stream" in resp.headers.get("content-type", "")
                for line in resp.iter_lines():
                    received.append(line)
                    if "test_event" in line:
                        # live event after replay proves the subscriber loop
                        events.publish(
                            "live_event", agent="test-agent", metadata={"live": True}
                        )
                    elif "live_event" in line:
                        break
                    elif len(received) > 5000:  # cap: fail instead of hanging
                        break
            assert any("test_event" in str(r) for r in received)
            assert any("live_event" in str(r) for r in received)
            # non-stream fallback serves the same history
            recent = hx.get(f"{base}/api/activity/recent").json()
            assert any(r["event"] == "test_event" for r in recent["events"])
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_activity_recent_returns_history(client):
    events.publish("some_event", agent="system", entity_id=7)
    body = client.get("/api/activity/recent").json()
    assert body["count"] >= 1
    assert any(
        r["event"] == "some_event" and r["entity_id"] == 7 for r in body["events"]
    )


# ---------------------------------------------------------------------------
# Opportunities / strategies / experiments / jobs / memory
# ---------------------------------------------------------------------------


def test_opportunities_scan_creates_and_scores_rows(client):
    resp = client.post("/api/opportunities/scan")
    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] >= 1
    assert body["scored"] >= 1
    assert body["total"] >= 1

    rows = client.get("/api/opportunities", params={"limit": 50}).json()[
        "opportunities"
    ]
    assert len(rows) >= 1
    assert any(r["status"] == "SCORED" for r in rows)
    assert all("score_0_100" in r for r in rows)
    assert all("factors" in r for r in rows)
    scored = [r for r in rows if r["status"] == "SCORED"]
    assert scored and scored[0]["score_0_100"] is not None

    # scan is idempotent-ish: re-running bumps last_seen, creates 0 new rows
    again = client.post("/api/opportunities/scan").json()
    assert again["created"] == 0
    assert again["scored"] == 0


def test_strategies_propose_and_list(client):
    resp = client.post(
        "/api/strategies",
        json={
            "name": "api micro-gig strategy",
            "description": "simulated delivery sweeps",
            "required_capital_paise": 1000,
            "required_skills": ["python", "writing"],
            "automation_level": "semi",
            "risk_level": "L2",
            "min_opportunity_score": 40.0,
            "max_spend_paise": 500,
            "allowed_risk_levels": ["L0", "L1", "L2"],
        },
    )
    assert resp.status_code == 200
    strategy = resp.json()
    assert strategy["status"] == "PROPOSED"
    assert strategy["id"] >= 1
    assert strategy["max_spend_formatted"] == "₹5.00"

    strategies = client.get("/api/strategies").json()["strategies"]
    assert any(s["id"] == strategy["id"] for s in strategies)
    assert strategies[0]["performance_summary"]["run_count"] == 0


def test_experiments_start_and_list(client):
    resp = client.post(
        "/api/experiments",
        json={
            "hypothesis": "smaller params grow profit",
            "strategy_id": None,
            "params_paise": 100,
            "expected_result": "profit up",
        },
    )
    assert resp.status_code == 200
    experiment = resp.json()
    assert experiment["status"] == "RUNNING"
    assert experiment["params_formatted"] == "₹1.00"

    experiments = client.get("/api/experiments").json()["experiments"]
    assert any(e["id"] == experiment["id"] for e in experiments)


def test_jobs_enqueue_and_list(client):
    resp = client.post(
        "/api/jobs",
        json={"job_type": "example", "payload": {"x": 1}, "priority": 2},
    )
    assert resp.status_code == 200
    job = resp.json()
    assert job["status"] == "QUEUED"
    assert job["job_type"] == "example"
    assert job["payload"] == {"x": 1}

    rows = client.get("/api/jobs", params={"status": "QUEUED"}).json()["jobs"]
    assert any(j["id"] == job["id"] for j in rows)


def test_memory_query(client):
    resp = client.get("/api/memory", params={"category": "fact"})
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def test_validation_error_is_400(client):
    resp = client.post(
        "/api/ledger/spend", json={"amount_paise": -5, "category": "tooling"}
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "validation_error"


def test_unknown_route_is_json_404(client):
    resp = client.get("/api/does-not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"] == "http_error"
