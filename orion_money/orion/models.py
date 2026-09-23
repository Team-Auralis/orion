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
    __tablename__ = "opportunities"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, default="generic")
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")


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
    __tablename__ = "jobs"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False, default="generic")
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")


class ToolCall(TimestampMixin, Base):
    __tablename__ = "tool_calls"

    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    args_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    correlation_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
