"""FORGE CYBER SOAR: policy-gated, human-approved, audited response actions.

Governance invariants:
- every action declares impact; high-impact requires a distinct human approval
  within TTL (mirrors ORION HITL dispatch semantics)
- AI recommendations are advisory input only and can never substitute approval
- default-deny policy decision via injectable authorizer
- immutable audit record per execution attempt
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable


class SoarError(Exception):
    pass


@dataclass
class Approval:
    approver_id: str
    decision: str
    decided_at: datetime

    @staticmethod
    def parse(raw: dict | None) -> "Approval | None":
        if not raw:
            return None
        d = raw.get("decided_at")
        if isinstance(d, str):
            d = datetime.fromisoformat(d.replace("Z", "+00:00"))
        if isinstance(d, datetime) and d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return Approval(approver_id=str(raw.get("approver_id", "")),
                        decision=str(raw.get("decision", "")).upper(),
                        decided_at=d or datetime.now(timezone.utc))


@dataclass
class ActionSpec:
    name: str
    impact: str
    expected_effect: str
    executor: Callable[[str], dict]
    rollback: Callable[[str], dict] | None = None


@dataclass
class SoarRecord:
    action: str
    target: str
    requested_by: str
    justification: str
    impact: str
    status: str
    policy_decision: object
    approval: dict | None
    ai_recommended: bool
    expected_effect: str
    rollback_available: bool
    executed_at: str | None = None
    result: dict = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class SoarEngine:
    APPROVAL_TTL = timedelta(minutes=15)

    def __init__(self, audit_path: str | None = None):
        self._specs: dict[str, ActionSpec] = {}
        self._lock = threading.Lock()
        self.audit_path = audit_path or os.path.join("logs", "soar_audit.jsonl")

    def register(self, spec: ActionSpec):
        if spec.impact not in ("low", "medium", "high"):
            raise SoarError(f"invalid impact {spec.impact}")
        self._specs[spec.name] = spec

    def _audit(self, rec: SoarRecord):
        line = json.dumps(rec.to_dict(), default=str)
        with self._lock:
            os.makedirs(os.path.dirname(self.audit_path), exist_ok=True)
            with open(self.audit_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def execute(self, action_name: str, target: str, requested_by: str,
                justification: str, authorizer: Callable[[str, str, dict], bool],
                approvals: dict | None = None, now: datetime | None = None,
                ai_recommended: bool = False) -> SoarRecord:
        now = now or datetime.now(timezone.utc)
        spec = self._specs.get(action_name)
        if spec is None:
            rec = SoarRecord(action_name, target, requested_by, justification,
                             "unknown", "REJECTED", False, None, ai_recommended,
                             "", False, error="unknown action")
            self._audit(rec)
            raise SoarError(f"unknown action '{action_name}'")

        policy_decision = bool(authorizer(action_name, target,
                                          {"requested_by": requested_by}))
        approval = Approval.parse(approvals)

        if not policy_decision:
            rec = SoarRecord(action_name, target, requested_by, justification,
                             spec.impact, "REJECTED", False, None, ai_recommended,
                             spec.expected_effect, spec.rollback is not None,
                             error="denied by policy")
            self._audit(rec)
            return rec

        if spec.impact == "high":
            verdict = self._check_approval(spec, approval, requested_by, now)
            if verdict != "OK":
                rec = SoarRecord(
                    action_name, target, requested_by, justification,
                    spec.impact, "PENDING_APPROVAL" if verdict == "MISSING"
                    else "REJECTED",
                    True,
                    approval.__dict__ if approval else None,
                    ai_recommended, spec.expected_effect,
                    spec.rollback is not None, error=verdict)
                self._audit(rec)
                return rec

        result = spec.executor(target)
        rec = SoarRecord(action_name, target, requested_by, justification,
                         spec.impact, "EXECUTED", True,
                         approval.__dict__ if approval else None,
                         ai_recommended, spec.expected_effect,
                         spec.rollback is not None,
                         executed_at=now.isoformat(), result=result)
        self._audit(rec)
        return rec

    NON_HUMAN_APPROVER_PREFIXES = ("ai-", "sentience", "svc-", "system")

    def _check_approval(self, spec: ActionSpec, approval: Approval | None,
                        requested_by: str, now: datetime) -> str:
        if approval is None:
            return "MISSING"
        if approval.decision != "APPROVE":
            return f"approval decision {approval.decision} does not authorize execution"
        low = approval.approver_id.strip().lower()
        if any(low.startswith(p) for p in self.NON_HUMAN_APPROVER_PREFIXES):
            return "non-human approver forbidden for high-impact actions"
        if approval.approver_id == requested_by:
            return "self-approval forbidden for high-impact actions"
        age = now - approval.decided_at
        if age > self.APPROVAL_TTL:
            return f"approval expired ({age.total_seconds():.0f}s old)"
        if age.total_seconds() < -300:
            return "approval timestamp in the future"
        return "OK"

    def rollback(self, original: SoarRecord, requested_by: str,
                 authorizer: Callable[[str, str, dict], bool],
                 now: datetime | None = None) -> SoarRecord:
        now = now or datetime.now(timezone.utc)
        spec = self._specs.get(original.action)
        if spec is None or spec.rollback is None:
            raise SoarError(f"no rollback registered for '{original.action}'")
        if original.status != "EXECUTED":
            raise SoarError("can only roll back executed actions")
        allowed = bool(authorizer(f"{original.action}:rollback", original.target,
                                  {"requested_by": requested_by}))
        if not allowed:
            rec = SoarRecord(original.action + ":rollback", original.target,
                             requested_by, "undo " + original.justification,
                             spec.impact, "REJECTED", False, None, False,
                             spec.expected_effect, False, error="denied by policy")
            self._audit(rec)
            return rec
        result = spec.rollback(original.target)
        rec = SoarRecord(original.action + ":rollback", original.target,
                         requested_by, "undo " + original.justification,
                         spec.impact, "EXECUTED", True, None, False,
                         spec.expected_effect, False,
                         executed_at=now.isoformat(), result=result)
        self._audit(rec)
        return rec


def default_authorizer(action: str, target: str, ctx: dict) -> bool:
    return False
