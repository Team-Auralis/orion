"""
CIC-001 Benchmark: Intent Drift Detection Test Suite.

Validates that the CIC Value Auditor correctly classifies actions as
PASS, WARN, or BLOCK based on cosine drift from the founding intent.
Also tests intent evolution (versioning) and edge cases.

Run: pytest tests/test_cic_auditor.py -v
"""

import json
import pytest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.database import Base, CICIntentRecord, CICAuditLog, CICDriftEvent
from services.cic.auditor import CICAuditor


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def db_session(tmp_path):
    """In-memory SQLite session with all CIC tables created."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


MOCK_SCHEMA = {
    "version": 1,
    "author": "test",
    "rationale": "test founding intent",
    "intent_vector": {
        "sustainability": 0.90,
        "equity": 0.85,
        "safety": 0.95,
        "resilience": 0.88,
        "transparency": 0.80,
        "autonomy": 0.70,
        "innovation": 0.75,
        "cooperation": 0.82,
    },
    "thresholds": {"warn": 0.15, "block": 0.30},
}


@pytest.fixture
def auditor(db_session, tmp_path):
    """CICAuditor backed by in-memory DB and a temp YAML schema."""
    schema_file = tmp_path / "intent_schema.yaml"
    import yaml

    schema_file.write_text(yaml.dump(MOCK_SCHEMA))
    return CICAuditor(db_session, schema_path=str(schema_file))


# ── Tests ────────────────────────────────────────────────────────────


class TestCosignDrift:
    """Pure math tests — no DB needed."""

    def test_identical_vectors_zero_drift(self):
        v = {"a": 0.9, "b": 0.8}
        assert CICAuditor.cosine_drift(v, v) == pytest.approx(0.0, abs=1e-9)

    def test_orthogonal_vectors_max_drift(self):
        v0 = {"a": 1.0, "b": 0.0}
        vt = {"a": 0.0, "b": 1.0}
        assert CICAuditor.cosine_drift(v0, vt) == pytest.approx(1.0, abs=1e-9)

    def test_slight_perturbation_low_drift(self):
        v0 = {"a": 0.9, "b": 0.8, "c": 0.7}
        vt = {"a": 0.88, "b": 0.79, "c": 0.69}
        drift = CICAuditor.cosine_drift(v0, vt)
        assert drift < 0.01  # nearly identical

    def test_empty_target_full_drift(self):
        v0 = {"a": 1.0}
        vt = {}
        assert CICAuditor.cosine_drift(v0, vt) == 1.0

    def test_anticorrelated_vectors_clamped_to_one(self):
        # Anti-correlated vectors give cosine similarity -1 -> 1 - (-1) = 2.0
        # without clamping; drift must stay within the documented [0, 1].
        v0 = {"a": 1.0}
        vt = {"a": -1.0}
        assert CICAuditor.cosine_drift(v0, vt) == 1.0

    def test_per_dimension_delta(self):
        v0 = {"a": 0.9, "b": 0.5}
        vt = {"a": 0.7, "b": 0.5}
        delta = CICAuditor.per_dimension_delta(v0, vt)
        assert delta["a"] == pytest.approx(0.2, abs=1e-4)
        assert delta["b"] == pytest.approx(0.0, abs=1e-4)


class TestAuditVerdict:
    """Integration tests against the DB-backed auditor."""

    def test_aligned_action_passes(self, auditor):
        result = auditor.audit(
            "Build renewable energy grid",
            {
                "sustainability": 0.88,
                "equity": 0.83,
                "safety": 0.93,
                "resilience": 0.86,
                "transparency": 0.78,
                "autonomy": 0.68,
                "innovation": 0.73,
                "cooperation": 0.80,
            },
        )
        assert result["verdict"] == "PASS"
        assert result["drift_score"] < 0.15

    def test_drifted_action_warns(self, auditor):
        result = auditor.audit(
            "Expand industrial mining aggressively",
            {
                "sustainability": 0.40,  # dropped hard
                "equity": 0.85,
                "safety": 0.95,
                "resilience": 0.88,
                "transparency": 0.80,
                "autonomy": 0.70,
                "innovation": 0.75,
                "cooperation": 0.82,
            },
        )
        assert result["verdict"] in ("WARN", "BLOCK")
        assert result["drift_score"] >= 0.01

    def test_hostile_action_blocked(self, auditor):
        result = auditor.audit(
            "Suppress all dissent and centralize control",
            {
                "sustainability": 0.10,
                "equity": 0.10,
                "safety": 0.10,
                "resilience": 0.10,
                "transparency": 0.05,
                "autonomy": 0.05,
                "innovation": 0.10,
                "cooperation": 0.05,
            },
        )
        assert result["verdict"] == "BLOCK"
        assert result["drift_score"] >= 0.30

    def test_audit_creates_db_records(self, auditor, db_session):
        auditor.audit("Test action", {"safety": 0.95, "equity": 0.85})
        logs = db_session.query(CICAuditLog).all()
        assert len(logs) == 1
        assert logs[0].action_description == "Test action"

    def test_block_creates_drift_event(self, auditor, db_session):
        auditor.audit(
            "Dangerous action",
            {"sustainability": 0.0, "safety": 0.0},
        )
        events = db_session.query(CICDriftEvent).all()
        assert len(events) >= 1
        assert events[0].severity == "CRITICAL"


class TestIntentEvolution:
    """Tests for governance-gated intent versioning."""

    def test_evolve_supersedes_old(self, auditor, db_session):
        new_vector = {
            "sustainability": 0.95,
            "equity": 0.90,
            "safety": 0.95,
            "resilience": 0.90,
            "transparency": 0.85,
            "autonomy": 0.75,
            "innovation": 0.80,
            "cooperation": 0.85,
        }
        auditor.evolve_intent(
            new_vector, "Democratic vote to raise standards", "governance_council"
        )

        records = db_session.query(CICIntentRecord).all()
        active = [r for r in records if r.status == "ACTIVE"]
        superseded = [r for r in records if r.status == "SUPERSEDED"]
        assert len(active) == 1
        assert len(superseded) == 1
        assert active[0].version == 2

    def test_audit_uses_latest_intent(self, auditor):
        new_vector = {
            "sustainability": 0.50,
            "equity": 0.50,
            "safety": 0.50,
            "resilience": 0.50,
            "transparency": 0.50,
            "autonomy": 0.50,
            "innovation": 0.50,
            "cooperation": 0.50,
        }
        auditor.evolve_intent(new_vector, "Relaxed values", "test")
        # An action matching the NEW intent should pass
        result = auditor.audit("Matching new intent", new_vector)
        assert result["verdict"] == "PASS"
        assert result["drift_score"] < 0.01
