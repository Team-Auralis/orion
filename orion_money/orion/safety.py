"""Risk-level policy, approval queue, and dry-run mode.

Single source of truth for the risk matrix is ``config/policies.yaml``:
``actions`` maps an action class (e.g. ``spend``, ``publish``) to a risk
level, and ``levels`` maps that risk level to its default decision
(``AUTO`` / ``APPROVAL`` / ``BLOCKED``). :func:`matrix` combines the two into
``{action: SafetyRule(level, default_decision)}``. Unknown action classes
fall back to a conservative ``L2 / APPROVAL`` default.

Dry-run mode (``config autonomy.default_mode == "dry_run"``, also settable via
the ``ORION_AUTONOMY_MODE`` env var, which :mod:`orion.config` folds into the
same field): external/financial actions still create an approval record, but
every approval is auto-approved with reason ``dry_run_auto_approve``. Callers
MUST treat ``dry_run_auto_approve`` as a simulation: no real side effects may
happen downstream. The safety engine only reports decisions — it never
executes the action.
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from orion.config import get_config
from orion.db import get_session
from orion.log import get_logger
from orion.models import ApprovalRequest, utc_now_iso
from orion.policy import BudgetPolicy
from orion.security import KillSwitchService

log = get_logger("safety")

# Action classes that move money and therefore must pass BudgetPolicy first.
FINANCIAL_ACTIONS = frozenset({"spend", "purchase"})


class RiskLevel(str, enum.Enum):
    L0 = "READ_ONLY"
    L1 = "LOCAL_WRITE"
    L2 = "EXTERNAL_COMMUNICATION"
    L3 = "FINANCIAL"
    L4 = "HIGH_IMPACT"


class Decision(str, enum.Enum):
    AUTO = "AUTO"
    APPROVAL = "APPROVAL"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class SafetyRule:
    level: RiskLevel
    decision: Decision


@dataclass(frozen=True)
class SafetyDecision:
    level: RiskLevel
    decision: Decision
    requires_approval: bool
    reasons: list[str] = field(default_factory=list)


# Conservative fallback for action classes not present in policies.yaml.
_DEFAULT_RULE = SafetyRule(RiskLevel.L2, Decision.APPROVAL)


def matrix() -> dict[str, SafetyRule]:
    """Build ``{action class: SafetyRule}`` from config/policies.yaml.

    The YAML is the single source of truth; this is a derived view.
    """
    policies = get_config().policies
    rules: dict[str, SafetyRule] = {}
    for action, level_name in policies.actions.items():
        try:
            level = RiskLevel[level_name]  # name lookup: "L0".."L4"
        except KeyError:
            level = RiskLevel.L2
        try:
            decision = Decision[policies.levels.get(level.name, "APPROVAL")]
        except KeyError:
            decision = Decision.APPROVAL
        rules[action] = SafetyRule(level=level, decision=decision)
    return rules


class SafetyEngine:
    """Evaluates proposed actions; the gate before anything executes."""

    def __init__(
        self,
        policy: Optional[BudgetPolicy] = None,
        kill_switch: Optional[KillSwitchService] = None,
    ):
        self.policy = policy or BudgetPolicy()
        self.kill_switch = kill_switch or KillSwitchService()

    def evaluate(self, action: dict, session=None) -> SafetyDecision:
        """Decide an action class + arguments.

        Order: kill switch first, then the risk matrix, then the budget
        engine for financial actions. Budget denial is a hard BLOCKED — an
        approval can never override a policy decision.
        """
        if session is None:
            with get_session() as s:
                return self.evaluate(action, session=s)

        reasons: list[str] = []

        # 1. Kill switch: blocks absolutely everything.
        if self.kill_switch.is_killed(session=session):
            return SafetyDecision(
                level=RiskLevel.L4,
                decision=Decision.BLOCKED,
                requires_approval=False,
                reasons=["kill switch active"],
            )

        # 2. Risk matrix.
        name = str(
            action.get("action") or action.get("tool") or action.get("name") or ""
        ).lower()
        rule = matrix().get(name, _DEFAULT_RULE)
        decision = rule.decision
        reasons.append(
            f"action class {name!r} -> {rule.level.name} "
            f"default {rule.decision.value}{' (unknown class, conservative default)' if name not in matrix() else ''}"
        )

        # 3. Budget engine for financial actions.
        if name in FINANCIAL_ACTIONS:
            amount = action.get("amount_paise", action.get("cost_paise"))
            if amount is None:
                decision = Decision.BLOCKED
                reasons.append(
                    f"financial action {name!r} missing amount_paise/cost_paise"
                )
            else:
                verdict = self.policy.can_spend(
                    amount,
                    action.get("category", ""),
                    when=action.get("when"),
                    session=session,
                )
                if not verdict.allow:
                    decision = Decision.BLOCKED
                    reasons.extend(verdict.reasons)
                else:
                    reasons.append(f"budget ok for {name}: {amount} paise")

        return SafetyDecision(
            level=rule.level,
            decision=decision,
            requires_approval=decision == Decision.APPROVAL,
            reasons=reasons,
        )


class ApprovalService:
    """SQL-backed approval queue over the ``approval_requests`` table.

    Lifecycle: PENDING -> APPROVED | REJECTED; PENDING past TTL -> EXPIRED.
    In dry-run mode every request auto-approves with decision
    ``dry_run_auto_approve``. Callers MUST NOT perform real side effects for
    dry-run approvals — the safety engine only reports; execution is the
    caller's job.

    Real modes (manual/assisted/autonomous) never auto-approve: requests
    stay PENDING until a human decides. An approved ``spend`` funds exactly
    one ledger write — the executor stamps ``consumed_at`` (see
    orion.api._execute_approved_spend) and a second approve() refuses because
    the record is no longer PENDING.
    """

    def _dry_run_active(self) -> bool:
        # ORION_AUTONOMY_MODE is folded into the same config field already.
        return get_config().autonomy.default_mode == "dry_run"

    def request(
        self,
        action: str,
        why: str = "",
        cost_paise: Optional[int] = None,
        potential_revenue_paise: Optional[int] = None,
        risk_level: Optional[str] = None,
        proposed_payload: Optional[dict[str, Any]] = None,
        destination: str = "",
        correlation_id: Optional[str] = None,
        ttl_hours: Optional[int] = None,
        session=None,
    ) -> ApprovalRequest:
        """Create a PENDING approval record (auto-approved in dry run)."""
        if session is None:
            with get_session() as s:
                return self.request(
                    action,
                    why=why,
                    cost_paise=cost_paise,
                    potential_revenue_paise=potential_revenue_paise,
                    risk_level=risk_level,
                    proposed_payload=proposed_payload,
                    destination=destination,
                    correlation_id=correlation_id,
                    ttl_hours=ttl_hours,
                    session=s,
                )

        ttl = (
            ttl_hours
            if ttl_hours is not None
            else get_config().policies.approval_ttl_hours
        )
        created = datetime.now(timezone.utc)
        expires = created + timedelta(hours=ttl)

        record = ApprovalRequest(
            kind=action,
            why=why,
            payload_json=(
                json.dumps(proposed_payload) if proposed_payload is not None else None
            ),
            cost_paise=cost_paise,
            potential_revenue_paise=potential_revenue_paise,
            risk_level=risk_level,
            destination=destination,
            correlation_id=correlation_id,
            expires_at=expires.isoformat(),
            status="PENDING",
            created_by="system",
        )
        session.add(record)
        session.flush()

        # --- Dry-run auto-approve -------------------------------
        # Simulation only: no real side effects may follow this approval.
        if self._dry_run_active():
            record.status = "APPROVED"
            record.decision = "dry_run_auto_approve"
            record.decision_reason = "dry_run_auto_approve"
            record.decided_by = "system"
            record.decided_at = utc_now_iso()
            log.warning(
                "dry-run auto-approve (NO side effects may execute)",
                extra={"id": record.id, "action": action, "cost_paise": cost_paise},
            )
        else:
            log.info(
                "approval requested",
                extra={"id": record.id, "action": action, "risk_level": risk_level},
            )
        session.flush()
        return record

    def approve(
        self, id: int, reason: str = "approved", session=None
    ) -> ApprovalRequest:
        """Approve a PENDING request (refuses if expired or already decided)."""
        if session is None:
            with get_session() as s:
                return self.approve(id, reason=reason, session=s)
        record = self._get_decidable(id, session)
        record.status = "APPROVED"
        record.decision = "APPROVED"
        record.decision_reason = reason
        record.decided_by = "system"
        record.decided_at = utc_now_iso()
        session.flush()
        log.info("approval approved", extra={"id": id, "reason": reason})
        return record

    def reject(self, id: int, reason: str, session=None) -> ApprovalRequest:
        """Reject a PENDING request. ``reason`` is required."""
        if session is None:
            with get_session() as s:
                return self.reject(id, reason=reason, session=s)
        if not reason or not reason.strip():
            raise ValueError("reject requires a non-empty reason")
        record = self._get_decidable(id, session)
        record.status = "REJECTED"
        record.decision = "REJECTED"
        record.decision_reason = reason
        record.decided_by = "system"
        record.decided_at = utc_now_iso()
        session.flush()
        log.info("approval rejected", extra={"id": id, "reason": reason})
        return record

    def expire_stale(self, session=None) -> int:
        """Mark every PENDING request past its TTL as EXPIRED. Returns count."""
        if session is None:
            with get_session() as s:
                return self.expire_stale(session=s)
        now = datetime.now(timezone.utc)
        count = 0
        for record in session.query(ApprovalRequest).filter(
            ApprovalRequest.status == "PENDING"
        ):
            if _is_expired(record, now):
                record.status = "EXPIRED"
                count += 1
        session.flush()
        if count:
            log.info("approvals expired", extra={"count": count})
        return count

    def pending(self, session=None) -> list[ApprovalRequest]:
        """Open (PENDING) requests, newest first."""
        if session is None:
            with get_session() as s:
                return self.pending(session=s)
        return list(
            session.query(ApprovalRequest)
            .filter(ApprovalRequest.status == "PENDING")
            .order_by(ApprovalRequest.id.desc())
        )

    def history(self, limit: int = 50, session=None) -> list[ApprovalRequest]:
        """All requests across statuses, newest first."""
        if session is None:
            with get_session() as s:
                return self.history(limit=limit, session=s)
        return list(
            session.query(ApprovalRequest)
            .order_by(ApprovalRequest.id.desc())
            .limit(limit)
        )

    # ------------------------------------------------------------------

    def _get_decidable(self, id: int, session) -> ApprovalRequest:
        record = session.get(ApprovalRequest, id)
        if record is None:
            raise ValueError(f"approval {id} not found")
        if record.status != "PENDING":
            raise ValueError(f"approval {id} already decided (status={record.status})")
        if _is_expired(record):
            record.status = "EXPIRED"
            session.flush()
            raise ValueError(f"approval {id} expired")
        return record


def _is_expired(record: ApprovalRequest, now: Optional[datetime] = None) -> bool:
    """True when an ``expires_at`` timestamp is in the past (None = no expiry)."""
    if not record.expires_at:
        return False
    now = now or datetime.now(timezone.utc)
    try:
        expires = datetime.fromisoformat(record.expires_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return now >= expires
