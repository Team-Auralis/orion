"""SQLAlchemy ORM models.

All money columns are INTEGER PAISE; ``created_at``/``updated_at`` are UTC
ISO-8601 strings. Ledger entries are append-only (see :mod:`orion.ledger`);
the other tables carry the data shapes later tasks will expand — this task
only seeds the skeleton (id + type/name + JSON payload + status).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from orion.db import Base


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string with timezone offset."""
    return datetime.now(timezone.utc).isoformat()


class TimestampMixin:
    """Shared ``id``/``created_at``/``updated_at`` columns."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[str] = mapped_column(
        String(32), default=utc_now_iso, nullable=False
    )
    updated_at: Mapped[str] = mapped_column(
        String(32), default=utc_now_iso, onupdate=utc_now_iso, nullable=False
    )


# ---------------------------------------------------------------------------
# Ledger (append-only money log)
# ---------------------------------------------------------------------------


class LedgerEntry(TimestampMixin, Base):
    __tablename__ = "ledger_entries"

    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    source: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    destination: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Event-type dependent: revenue uses revenue statuses; others use
    # lifecycle states (CONFIRMED/ACTIVE/COMPLETED/OPEN/APPLIED/...).
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    verification_method: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )


# ---------------------------------------------------------------------------
# System / safety
# ---------------------------------------------------------------------------


class SchemaVersion(TimestampMixin, Base):
    __tablename__ = "schema_version"

    version: Mapped[int] = mapped_column(Integer, nullable=False)
    applied_at: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")


class SystemSetting(Base):
    __tablename__ = "system_settings"
    __table_args__ = (UniqueConstraint("key", name="uq_system_settings_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[str] = mapped_column(
        String(32), default=utc_now_iso, onupdate=utc_now_iso, nullable=False
    )


class KillSwitch(TimestampMixin, Base):
    """Singleton row (id=1). When ``active`` the agent must halt money moves."""

    __tablename__ = "kill_switch"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Stubs for later tasks (minimal: id + name/type + JSON payload + status)
# ---------------------------------------------------------------------------


class ApprovalRequest(TimestampMixin, Base):
    """Approval queue record. Lifecycle: PENDING -> APPROVED | REJECTED,
    and PENDING past ``expires_at`` becomes EXPIRED (see orion.safety).
    All money columns are INTEGER PAISE.
    """

    __tablename__ = "approval_requests"

    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    why: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cost_paise: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    potential_revenue_paise: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    risk_level: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    destination: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    correlation_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    expires_at: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    created_by: Mapped[str] = mapped_column(
        String(64), nullable=False, default="system"
    )
    decided_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    decision: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    decision_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_at: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)


class Opportunity(TimestampMixin, Base):
    """Discovered revenue opportunity.

    Lifecycle (see orion.discovery.OpportunityStatus):
    DISCOVERED -> SCORED -> PENDING -> APPROVED -> REJECTED -> EXECUTED ->
    CLOSED. Suspicious offers go DISCOVERED -> SCORED -> REJECTED and are
    kept out of the approval flow. All money columns are INTEGER PAISE.
    ``content_hash`` dedupes re-scans: same normalized title+source+
    description updates ``last_seen`` on the existing row, never inserts.
    """

    __tablename__ = "opportunities"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, default="generic")
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="DISCOVERED", index=True
    )
    # Normalized offer identity (sha256 of title+source+description).
    content_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", index=True
    )
    source: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source_connector: Mapped[str] = mapped_column(
        String(64), nullable=False, default=""
    )
    url: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    estimated_value_paise: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    cost_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deadline: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    required_skills_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    automation_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    platform_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    demand_hint: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    competition_hint: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Scoring (orion.scoring — pure numeric, never an LLM).
    score_0_100: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    factors_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    suspicious: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    suspicious_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rejected_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_seen: Mapped[str] = mapped_column(
        String(32), default=utc_now_iso, nullable=False
    )


class Strategy(TimestampMixin, Base):
    __tablename__ = "strategies"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")


class Experiment(TimestampMixin, Base):
    __tablename__ = "experiments"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="planned")


class MemoryItem(TimestampMixin, Base):
    """Discriminated memory rows: kind ∈ fact|belief|hypothesis|evidence.

    kind-specific columns (see orion.memory for semantics):
    * ``verified``  — FACTS only: True when the fact is confirmed, either by
      explicit verification or by linkage to a supporting evidence row.
    * ``status``    — HYPOTHESES only: proposed | confirmed | refuted.
    * ``direction`` — EVIDENCE only: supports | contradicts.
    * ``reference`` — EVIDENCE: ledger entry id / experiment id it observes;
      FACTS: the evidence row id (``evidence:<id>``) that verified it.
    """

    __tablename__ = "memory_items"

    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    direction: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class Job(TimestampMixin, Base):
    """Persistent queue row. Lifecycle: QUEUED -> RUNNING -> SUCCESS |
    FAILED | CANCELLED, plus WAITING_APPROVAL (awaiting a human decision).
    ``attempts`` counts executions; a job is never rerun past
    ``jobs.max_attempts`` (see orion.jobs).
    """

    __tablename__ = "jobs"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False, default="generic")
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="QUEUED", index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    finished_at: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)


class StrategyRun(TimestampMixin, Base):
    """One recorded execution of a Strategy — the evidence base for ranking
    (orion.strategy). All money columns are INTEGER PAISE.
    ``profit_per_hour_paise`` is derived (profit / time_hours) when the
    caller does not supply it.
    """

    __tablename__ = "strategy_runs"

    strategy_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    capital_used_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    time_hours: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    opportunities_checked: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    responses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    losses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revenue_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fees_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    profit_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    profit_per_hour_paise: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    failure_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")


class ExperimentResult(TimestampMixin, Base):
    """Outcome of one Experiment (orion.experiments). ``delta_paise`` only
    counts when ``supporting_evidence_id`` points at a real ledger/evidence
    row — otherwise it is zeroed with a ``warning`` (anti-hallucination).
    """

    __tablename__ = "experiment_results"

    experiment_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    observed_outcome: Mapped[str] = mapped_column(Text, nullable=False, default="")
    delta_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    supporting_evidence_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    warning: Mapped[str] = mapped_column(Text, nullable=False, default="")


class ToolCall(TimestampMixin, Base):
    __tablename__ = "tool_calls"

    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    args_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    correlation_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
