import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from services.cyber import (
    SecurityEvent, DetectionEngine, Finding,
    SoarEngine, SoarError, ActionSpec,
)

NOW = datetime(2026, 8, 23, 14, 0, 0, tzinfo=timezone.utc)


def ev(**kw):
    ts = kw.pop("ts", NOW)
    return SecurityEvent.create(ts=ts, **kw)


@pytest.fixture()
def engine():
    return DetectionEngine(nats_publisher_allowlist={
        "incident.created": {"api"},
        "incident.status_changed": {"api"},
    })


# ---------------- detections ----------------

def test_benign_traffic_produces_no_findings(engine):
    e = ev(source="kc", category="auth", action="login", outcome="success",
           subject="op1", role="operator")
    assert engine.process(e) == []


def test_bruteforce_fires_on_fifth_failure(engine):
    findings = []
    for i in range(5):
        f = engine.process(ev(source="10.0.0.9", category="auth", action="login",
                              outcome="failed", subject="victim",
                              attrs={"attempt": i}))
        findings.extend(f)
    assert len(findings) == 1
    assert findings[0].rule_id == "AUTH-BRUTEFORCE"
    assert findings[0].severity == "high"
    assert findings[0].evidence_event_ids


def test_impossible_travel_fires(engine):
    a = ev(source="web", category="auth", action="login", outcome="success",
           subject="wanderer", attrs={"geo": {"lat": 34.05, "lon": -118.24}})
    b = ev(source="web", category="auth", action="login", outcome="success",
           subject="wanderer",
           attrs={"geo": {"lat": 48.85, "lon": 2.35}},
           ts=NOW + timedelta(hours=1))
    assert engine.process(a) == []
    out = engine.process(b)
    assert out and out[0].rule_id == "IMPOSSIBLE-TRAVEL"


def test_breakglass_spike_and_offhours(engine):
    night = NOW.replace(hour=23)
    fs = []
    for i in range(3):
        fs += engine.process(ev(source="api", category="breakglass",
                                action="activate", outcome="success",
                                subject="op1", role="operator", ts=night))
    ids = [f.rule_id for f in fs]
    assert "BG-SPIKE" in ids
    assert "BG-OFFHOURS" in ids
    spike = [f for f in fs if f.rule_id == "BG-SPIKE"][0]
    assert spike.severity == "critical"


def test_expired_breakglass_use_is_critical(engine):
    out = engine.process(ev(source="api", category="breakglass", action="use",
                            outcome="expired", subject="attacker"))
    assert out[0].rule_id == "BG-TOKEN-ABUSE"
    assert out[0].confidence >= 0.9


def test_killswitch_tamper_by_non_operator(engine):
    out = engine.process(ev(source="redis", category="pilot.killswitch",
                            action="resume", outcome="success",
                            subject="mystery", role="citizen"))
    assert out[0].rule_id == "KS-TAMPER"


def test_killswitch_resume_without_active_suspension(engine):
    out = engine.process(ev(source="api", category="pilot.killswitch",
                            action="resume", outcome="success",
                            subject="op1", role="operator",
                            attrs={"had_active_suspension": False}))
    assert out[0].rule_id == "KS-TAMPER"
    assert out[0].confidence >= 0.95


def test_legitimate_killswitch_cycle_is_quiet(engine):
    assert engine.process(ev(source="api", category="pilot.killswitch",
                             action="suspend", outcome="success",
                             subject="op1", role="operator")) == []
    assert engine.process(ev(source="api", category="pilot.killswitch",
                             action="resume", outcome="success",
                             subject="op1", role="operator",
                             attrs={"had_active_suspension": True})) == []


def test_policy_deny_burst(engine):
    fs = []
    for i in range(11):
        fs += engine.process(ev(source="api", category="authz", action="read",
                                outcome="denied", subject="prober"))
    assert any(f.rule_id == "POLICY-DENY-BURST" for f in fs)


def test_unauthorized_nats_publisher(engine):
    out = engine.process(ev(source="unknown-svc", category="nats.publish",
                            action="publish", outcome="success",
                            subject="svc-x", actor_kind="service",
                            resource="incident.created"))
    assert out[0].rule_id == "NATS-UNAUTHORIZED-PUBLISHER"


def test_unknown_nats_subject_is_low_confidence(engine):
    out = engine.process(ev(source="api", category="nats.publish", action="publish",
                            outcome="success", subject="api", actor_kind="service",
                            resource="brand.new.subject"))
    assert out[0].rule_id == "NATS-UNKNOWN-SUBJECT"
    assert out[0].confidence <= 0.5


def test_oversize_payload(engine):
    out = engine.process(ev(source="nats", category="ingest", action="message",
                            outcome="received", subject="civ",
                            attrs={"size_bytes": 5_000_000}))
    assert out[0].rule_id == "PAYLOAD-OVERSIZE"


def test_asset_teleport(engine):
    a = ev(source="aegis", category="asset.move", action="position", outcome="ok",
           subject="dev-7", resource="AMB-01", attrs={"geo": {"lat": 34.05, "lon": -118.24}})
    b = ev(source="aegis", category="asset.move", action="position", outcome="ok",
           subject="dev-7", resource="AMB-01",
           attrs={"geo": {"lat": 40.71, "lon": -74.00}},
           ts=NOW + timedelta(seconds=30))
    assert engine.process(a) == []
    out = engine.process(b)
    assert out[0].rule_id == "ASSET-TELEPORT"


def test_normalize_raw_dict_roundtrip():
    raw = {"source": "kc", "category": "auth", "action": "login",
           "outcome": "failed", "subject": "u1", "role": "citizen",
           "ts": "2026-08-23T00:00:00+00:00", "attrs": {"x": 1}}
    e = SecurityEvent.normalize(raw)
    assert e.actor.subject == "u1" and e.attrs["x"] == 1
    again = SecurityEvent.normalize(e.to_dict())
    assert again.event_id == e.event_id


# ---------------- SOAR ----------------

@pytest.fixture()
def soar(tmp_path):
    s = SoarEngine(audit_path=str(tmp_path / "audit.jsonl"))
    executed = {}
    s.register(ActionSpec(
        name="isolate_endpoint", impact="high",
        expected_effect="endpoint quarantined from fabric",
        executor=lambda t: executed.setdefault("exe", []).append(t) or {"isolated": t},
        rollback=lambda t: executed.setdefault("rb", []).append(t) or {"restored": t},
    ))
    s.register(ActionSpec(
        name="increase_monitoring", impact="low",
        expected_effect="verbosity raised on target",
        executor=lambda t: {"watching": t},
    ))
    return s, executed


def allow(a, t, c):
    return True


def deny(a, t, c):
    return False


def appr(approver, decision="APPROVE", at=None):
    return {"approver_id": approver, "decision": decision,
            "decided_at": (at or (NOW - timedelta(minutes=2))).isoformat()}


def test_default_policy_denies_everything(soar):
    s, _ = soar
    rec = s.execute("increase_monitoring", "node-1", "analyst", "why",
                    authorizer=lambda *a, **k: False)
    assert rec.status == "REJECTED" and rec.policy_decision is False


def test_low_impact_executes_when_allowed(soar):
    s, _ = soar
    rec = s.execute("increase_monitoring", "node-1", "analyst", "hunt",
                    authorizer=allow)
    assert rec.status == "EXECUTED" and rec.result == {"watching": "node-1"}


def test_high_impact_requires_approval(soar):
    s, ex = soar
    rec = s.execute("isolate_endpoint", "edge-3", "sentience-ai",
                    "ai thinks node is bad", authorizer=allow,
                    ai_recommended=True)
    assert rec.status == "PENDING_APPROVAL"
    assert "isolate_endpoint" not in ex.get("exe", [])


def test_ai_cannot_self_approve(soar):
    s, ex = soar
    rec = s.execute("isolate_endpoint", "edge-3", "analyst", "j", authorizer=allow,
                    approvals=appr("SENTIENCE-AI"), now=NOW)
    assert rec.status == "REJECTED"
    assert "non-human" in rec.error
    assert "isolate_endpoint" not in ex.get("exe", [])


def test_self_approval_forbidden(soar):
    s, ex = soar
    rec = s.execute("isolate_endpoint", "edge-3", "op9", "j", authorizer=allow,
                    approvals=appr("op9"), now=NOW)
    assert rec.status == "REJECTED"
    assert "self-approval" in rec.error
    assert "isolate_endpoint" not in ex.get("exe", [])


def test_stale_and_future_approvals_rejected(soar):
    s, _ = soar
    stale = s.execute("isolate_endpoint", "e", "op1", "j", authorizer=allow,
                      approvals=appr("chief", at=NOW - timedelta(hours=2)),
                      now=NOW)
    assert stale.status == "REJECTED"
    assert stale.error.startswith("approval expired")
    future = s.execute("isolate_endpoint", "e", "op1", "j", authorizer=allow,
                       approvals=appr("chief", at=NOW + timedelta(hours=5)),
                       now=NOW)
    assert future.status == "REJECTED"
    assert future.error == "approval timestamp in the future"


def test_approved_high_impact_executes_and_audits(soar):
    s, ex = soar
    rec = s.execute("isolate_endpoint", "edge-3", "soc-bot", "containment",
                    authorizer=allow, approvals=appr("duty-chief"), now=NOW)
    assert rec.status == "EXECUTED"
    assert ex["exe"] == ["edge-3"]
    lines = open(s.audit_path, encoding="utf-8").read().strip().splitlines()
    entry = json.loads(lines[-1])
    for field in ("action", "target", "requested_by", "justification", "impact",
                  "status", "policy_decision", "expected_effect"):
        assert field in entry
    assert entry["policy_decision"] is True


def test_reject_decision_does_not_execute(soar):
    s, ex = soar
    rec = s.execute("isolate_endpoint", "e", "op1", "j", authorizer=allow,
                    approvals=appr("chief", decision="REJECT"), now=NOW)
    assert rec.status == "REJECTED"
    assert "does not authorize" in rec.error
    assert not ex.get("exe")


def test_rollback_flow(soar):
    s, ex = soar
    rec = s.execute("isolate_endpoint", "edge-4", "op1", "containment",
                    authorizer=allow, approvals=appr("chief"), now=NOW)
    rb = s.rollback(rec, requested_by="chief2", authorizer=allow, now=NOW)
    assert rb.status == "EXECUTED" and rb.result == {"restored": "edge-4"}
    assert ex["rb"] == ["edge-4"]


def test_rollback_requires_policy(soar):
    s, ex = soar
    rec = s.execute("isolate_endpoint", "edge-5", "op1", "c",
                    authorizer=allow, approvals=appr("chief"), now=NOW)
    rb = s.rollback(rec, requested_by="rogue", authorizer=deny, now=NOW)
    assert rb.status == "REJECTED"
    assert not ex.get("rb")


def test_unknown_action_rejected(soar):
    s, _ = soar
    with pytest.raises(SoarError, match="unknown action"):
        s.execute("nuke_from_orbit", "earth", "op1", "j", authorizer=allow)
