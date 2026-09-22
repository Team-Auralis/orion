import uuid
import json
import math
import yaml
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.orm import Session
from apps.api.database import CICIntentRecord, CICAuditLog, CICDriftEvent


class CICAuditor:
    """
    CIC: Civilizational Intent Conservation – Value Auditor.

    Sits between NEXUS/FORGE proposal and VEIL authorization.
    Every proposed action is scored against the active intent vector.
    If drift exceeds the threshold, the action is warned or blocked.
    """

    def __init__(self, db_session: Session, schema_path: str = None):
        self.db = db_session
        self.schema_path = schema_path or str(
            Path(__file__).resolve().parents[2] / "intent_schema.yaml"
        )
        self._ensure_intent_loaded()

    # ── Bootstrap ────────────────────────────────────────────────

    def _ensure_intent_loaded(self):
        """Load the YAML schema into the DB if no active record exists."""
        active = (
            self.db.query(CICIntentRecord)
            .filter_by(status="ACTIVE")
            .order_by(CICIntentRecord.version.desc())
            .first()
        )
        if active:
            return

        schema = self._read_schema()
        record = CICIntentRecord(
            id=str(uuid.uuid4()),
            version=schema["version"],
            intent_vector=json.dumps(schema["intent_vector"]),
            rationale=schema.get("rationale", "Initial load from YAML"),
            author=schema.get("author", "system"),
            status="ACTIVE",
        )
        self.db.add(record)
        self.db.commit()

    def _read_schema(self) -> dict:
        with open(self.schema_path) as f:
            return yaml.safe_load(f)

    # ── Core: get active intent ──────────────────────────────────

    def get_active_intent(self) -> dict:
        """Return the current active intent vector as a dict."""
        record = (
            self.db.query(CICIntentRecord)
            .filter_by(status="ACTIVE")
            .order_by(CICIntentRecord.version.desc())
            .first()
        )
        return json.loads(record.intent_vector)

    def get_thresholds(self) -> dict:
        """Return warn/block thresholds from the YAML schema."""
        schema = self._read_schema()
        return schema.get("thresholds", {"warn": 0.15, "block": 0.30})

    # ── Core: compute drift ──────────────────────────────────────

    @staticmethod
    def cosine_drift(v0: dict, vt: dict) -> float:
        """
        Compute drift as 1 - cosine_similarity(v0, vt).
        Returns 0.0 (perfect alignment) to 1.0 (total drift).
        Keys missing in vt are treated as 0.0.
        """
        keys = set(v0) | set(vt)
        dot = sum(v0.get(k, 0.0) * vt.get(k, 0.0) for k in keys)
        mag0 = math.sqrt(sum(v0.get(k, 0.0) ** 2 for k in keys))
        magt = math.sqrt(sum(vt.get(k, 0.0) ** 2 for k in keys))
        if mag0 == 0 or magt == 0:
            return 1.0
        sim = dot / (mag0 * magt)
        return max(0.0, min(1.0, 1.0 - sim))

    @staticmethod
    def composite_drift(v0: dict, vt: dict) -> float:
        """
        Composite drift metric: max(mean_absolute_drift, max_single_dimension_drift).

        Cosine similarity only captures directional change, missing uniform
        magnitude collapse (e.g. all values halved).  Mean absolute difference
        misses single-dimension collapse diluted across many dimensions.
        Taking the max of both catches every failure mode.

        ponytail: upgrade path → per-dimension weighting by intent importance.
        """
        keys = set(v0) | set(vt)
        if not keys:
            return 0.0
        diffs = [abs(v0.get(k, 0.0) - vt.get(k, 0.0)) for k in keys]
        mean_drift = sum(diffs) / len(diffs)
        max_drift = max(diffs)
        return max(mean_drift, max_drift)

    @staticmethod
    def per_dimension_delta(v0: dict, vt: dict) -> dict:
        """Absolute per-dimension difference for the audit details."""
        keys = set(v0) | set(vt)
        return {k: round(abs(v0.get(k, 0.0) - vt.get(k, 0.0)), 4) for k in keys}

    # ── Public API: audit an action ──────────────────────────────

    def audit(self, action_description: str, action_values: dict) -> dict:
        """
        Audit a proposed action against the founding intent.

        Parameters
        ----------
        action_description : str
            Human-readable label for the action being audited.
        action_values : dict
            The action's implied value weights, same keys as intent_vector.
            Example: {"safety": 0.9, "sustainability": 0.3, "equity": 0.8, ...}

        Returns
        -------
        dict with keys: verdict, drift_score, threshold, details, audit_id
        """
        intent = self.get_active_intent()
        thresholds = self.get_thresholds()

        drift = self.composite_drift(intent, action_values)
        details = self.per_dimension_delta(intent, action_values)

        # Determine verdict
        if drift >= thresholds["block"]:
            verdict = "BLOCK"
        elif drift >= thresholds["warn"]:
            verdict = "WARN"
        else:
            verdict = "PASS"

        # Get active intent version
        active_record = (
            self.db.query(CICIntentRecord)
            .filter_by(status="ACTIVE")
            .order_by(CICIntentRecord.version.desc())
            .first()
        )

        # Persist audit log
        audit_id = str(uuid.uuid4())
        log = CICAuditLog(
            id=audit_id,
            action_description=action_description,
            intent_version=active_record.version,
            drift_score=round(drift, 6),
            threshold=thresholds["block"],
            verdict=verdict,
            details=json.dumps(details),
        )
        self.db.add(log)

        # Raise drift event if warranted
        if verdict in ("WARN", "BLOCK"):
            event = CICDriftEvent(
                id=str(uuid.uuid4()),
                audit_log_id=audit_id,
                severity="CRITICAL" if verdict == "BLOCK" else "WARN",
                corrective_action=(
                    "Action blocked. Submit governance proposal to evolve intent."
                    if verdict == "BLOCK"
                    else "Drift detected. Review action alignment."
                ),
            )
            self.db.add(event)

        self.db.commit()

        return {
            "verdict": verdict,
            "drift_score": round(drift, 6),
            "threshold_warn": thresholds["warn"],
            "threshold_block": thresholds["block"],
            "details": details,
            "audit_id": audit_id,
        }

    # ── Intent Evolution (governance-gated) ──────────────────────

    def evolve_intent(self, new_vector: dict, rationale: str, author: str) -> str:
        """
        Supersede the current intent and activate a new version.
        In production this would require HITL approval via SOAR.
        """
        # Supersede current
        current = (
            self.db.query(CICIntentRecord)
            .filter_by(status="ACTIVE")
            .order_by(CICIntentRecord.version.desc())
            .first()
        )
        new_version = (current.version + 1) if current else 1
        if current:
            current.status = "SUPERSEDED"

        record_id = str(uuid.uuid4())
        record = CICIntentRecord(
            id=record_id,
            version=new_version,
            intent_vector=json.dumps(new_vector),
            rationale=rationale,
            author=author,
            status="ACTIVE",
        )
        self.db.add(record)
        self.db.commit()
        return record_id
