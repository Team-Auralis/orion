"""ORION ledger — append-only money log and balance computation.

Model
-----
The ledger is an append-only event log. Entries are never UPDATEd or DELETEd;
state changes (e.g. a revenue becoming disputed) are expressed as *new* events
that also flip the affected entry's ``status`` column as an audit trail.

Every event carries ``amount_paise`` — integer paise, no floats anywhere.

Invariant (checked on every write; see :func:`assert_invariant`):

    capital == available_cash + reserved_cash + spent
             - verified_revenue + refunds - fees

Where (all paise, cumulative over the event log):

    * ``capital``           — money injected from outside (DEPOSIT/ADJUSTMENT basis).
    * ``available_cash``    — cash usable right now.
    * ``reserved_cash``     — cash committed to pending spends.
    * ``spent``             — gross money spent on purchases.
    * ``verified_revenue``  — revenue recognized as VERIFIED (confirmed inflow).
    * ``refunds``           — money returned on purchases; a refund *reverses* part of
                              ``spent`` (net-spend accounting) and is also reported here.
    * ``fees``              — costs of earning, deducted from the verified revenue they
                              relate to (e.g. platform/transaction fees); they are not
                              cash outflows from the wallet.

Event effects:

    DEPOSIT          capital += a; available += a
    RESERVE          available -= a (>= 0); reserved += a
    SPEND            reserved first then available; spent += a
    RELEASE_RESERVE  reserved -= a; available += a
    REVENUE (VER)    available += a; verified_revenue += a
    REVENUE (pend)   pending_revenue += a            (informational, not in invariant)
    FEE              verified_revenue -= a (>= 0); fees += a
    REFUND           spent -= a (>= 0); refunds += a
    DISPUTE          available -= a (>= 0); verified_revenue -= a (>= 0);
                     marks the referenced revenue entry DISPUTED
    ADJUSTMENT       capital += a; available += a    (manual books correction, a may be
                     negative; available must stay >= 0)

Revenue statuses: ESTIMATED (no verification method), PENDING (method but
confidence < 0.9), VERIFIED (method AND confidence >= 0.9), REFUNDED, DISPUTED.
PENDING/ESTIMATED revenue is tracked but does not touch ``available_cash`` —
only VERIFIED revenue is real money.
"""

from __future__ import annotations

import enum
import json
from typing import Any, Optional

from sqlalchemy import select

from orion.config import get_config
from orion.db import get_session  # noqa: F401  (re-exported convenience)
from orion.log import get_logger
from orion.models import LedgerEntry, SystemSetting, utc_now_iso

log = get_logger("ledger")

VERIFIED_CONFIDENCE_THRESHOLD = 0.9


def fmt_paise(paise: int) -> str:
    """The one place paise become ₹ — `fmt_paise(123456)` -> '₹1,234.56'."""
    amount = int(paise)
    sign = "-" if amount < 0 else ""
    absolute = abs(amount)
    return f"{sign}₹{absolute // 100:,}.{absolute % 100:02d}"


CAPITAL_KEY = "capital"
SEED_SETTING_KEY = "capital_seeded"

BALANCE_FIELDS = (
    "capital",
    "available_cash",
    "reserved_cash",
    "spent",
    "verified_revenue",
    "pending_revenue",
    "fees",
    "refunds",
)


class EventType(str, enum.Enum):
    DEPOSIT = "DEPOSIT"
    RESERVE = "RESERVE"
    SPEND = "SPEND"
    RELEASE_RESERVE = "RELEASE_RESERVE"
    REVENUE = "REVENUE"
    FEE = "FEE"
    REFUND = "REFUND"
    DISPUTE = "DISPUTE"
    ADJUSTMENT = "ADJUSTMENT"


class RevenueStatus(str, enum.Enum):
    ESTIMATED = "ESTIMATED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REFUNDED = "REFUNDED"
    DISPUTED = "DISPUTED"


# Lifecycle status per non-revenue event type.
_STATUS_BY_TYPE = {
    EventType.DEPOSIT: "CONFIRMED",
    EventType.RESERVE: "ACTIVE",
    EventType.SPEND: "COMPLETED",
    EventType.RELEASE_RESERVE: "COMPLETED",
    EventType.FEE: "CHARGED",
    EventType.REFUND: "COMPLETED",
    EventType.DISPUTE: "OPEN",
    EventType.ADJUSTMENT: "APPLIED",
}


# ---------------------------------------------------------------------------
# Event folding
# ---------------------------------------------------------------------------


def _blank_balance() -> dict[str, int]:
    return {field: 0 for field in BALANCE_FIELDS}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _require_positive(amount_paise: int) -> None:
    _require(
        isinstance(amount_paise, int)
        and not isinstance(amount_paise, bool)
        and amount_paise > 0,
        f"amount_paise must be a positive integer, got {amount_paise!r}",
    )


def _apply_event(balance: dict[str, int], entry: LedgerEntry) -> None:
    """Fold one ledger event into the running balance (validate as we go)."""
    a = entry.amount_paise
    # ADJUSTMENT carries a signed amount; every other event must be positive.
    if entry.type != EventType.ADJUSTMENT:
        _require_positive(a)
    else:
        _require(
            isinstance(a, int) and not isinstance(a, bool),
            f"amount_paise must be an integer, got {a!r}",
        )
    t = entry.type

    if t == EventType.DEPOSIT:
        balance["capital"] += a
        balance["available_cash"] += a

    elif t == EventType.RESERVE:
        _require(
            balance["available_cash"] >= a, "cannot reserve more than available cash"
        )
        balance["available_cash"] -= a
        balance["reserved_cash"] += a

    elif t == EventType.SPEND:
        _require(
            balance["available_cash"] + balance["reserved_cash"] >= a,
            "insufficient funds",
        )
        take = min(a, balance["reserved_cash"])
        balance["reserved_cash"] -= take
        balance["available_cash"] -= a - take
        balance["spent"] += a

    elif t == EventType.RELEASE_RESERVE:
        _require(
            balance["reserved_cash"] >= a, "cannot release more than reserved cash"
        )
        balance["reserved_cash"] -= a
        balance["available_cash"] += a

    elif t == EventType.REVENUE:
        # Status is a *label* for audit purposes. Only ESTIMATED/PENDING
        # stays unrealized; VERIFIED counts as money in, and DISPUTED/REFUNDED
        # still count as booked revenue here because the matching
        # DISPUTE/REFUND *event* performs the actual retraction.
        if entry.status in (
            RevenueStatus.VERIFIED,
            RevenueStatus.DISPUTED,
            RevenueStatus.REFUNDED,
        ):
            balance["available_cash"] += a
            balance["verified_revenue"] += a
        else:  # ESTIMATED / PENDING
            balance["pending_revenue"] += a

    elif t == EventType.FEE:
        _require(
            balance["verified_revenue"] >= a, "fee exceeds verified revenue to charge"
        )
        balance["verified_revenue"] -= a
        balance["fees"] += a

    elif t == EventType.REFUND:
        _require(balance["spent"] >= a, "refund exceeds total spent")
        balance["spent"] -= a
        balance["refunds"] += a

    elif t == EventType.DISPUTE:
        _require(balance["verified_revenue"] >= a, "dispute exceeds verified revenue")
        _require(balance["available_cash"] >= a, "dispute exceeds available cash")
        balance["verified_revenue"] -= a
        balance["available_cash"] -= a

    elif t == EventType.ADJUSTMENT:
        _require(a != 0, "adjustment amount must be non-zero")
        balance["capital"] += a
        balance["available_cash"] += a
        _require(balance["available_cash"] >= 0, "adjustment would make cash negative")

    else:  # pragma: no cover - unknown discriminator should never be persisted
        raise ValueError(f"unknown event type {t!r}")

    _require(balance["available_cash"] >= 0, "available cash went negative")
    assert_invariant(balance)


def _replay(session) -> dict[str, int]:
    """Replay the whole ledger in id order into a fresh balance."""
    balance = _blank_balance()
    entries = session.execute(
        select(LedgerEntry).order_by(LedgerEntry.id.asc())
    ).scalars()
    for entry in entries:
        _apply_event(balance, entry)
    return balance


# ---------------------------------------------------------------------------
# Invariant
# ---------------------------------------------------------------------------


def assert_invariant(balance: dict[str, int]) -> None:
    """Assert the ledger conservation law holds for ``balance``.

    See the module docstring for the exact definition of each term.
    """
    lhs = balance["capital"]
    rhs = (
        balance["available_cash"]
        + balance["reserved_cash"]
        + balance["spent"]
        - balance["verified_revenue"]
        + balance["refunds"]
        - balance["fees"]
    )
    assert lhs == rhs, (
        f"ledger invariant violated: capital={lhs} != "
        f"available+reserved+spent-verified_revenue+refunds-fees={rhs} "
        f"full balance={balance}"
    )


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def get_balance(session) -> dict[str, int]:
    """Current balance counters (replayed from the event log)."""
    return _replay(session)


def get_ledger(session, limit: Optional[int] = None) -> list[LedgerEntry]:
    """Ledger entries, newest first, optionally capped by ``limit``."""
    query = select(LedgerEntry).order_by(LedgerEntry.id.desc())
    if limit is not None:
        query = query.limit(limit)
    return list(session.execute(query).scalars())


def summary(session) -> dict[str, Any]:
    """Human/API-facing financial picture of the whole ledger."""
    balance = _replay(session)
    revenue_rows = list(
        session.execute(
            select(LedgerEntry).where(LedgerEntry.type == EventType.REVENUE)
        ).scalars()
    )
    revenue_statuses: dict[str, int] = {}
    for row in revenue_rows:
        revenue_statuses[row.status] = revenue_statuses.get(row.status, 0) + 1

    return {
        "currency": get_config().orion.currency,
        "capital": balance["capital"],
        "available_cash": balance["available_cash"],
        "reserved_cash": balance["reserved_cash"],
        "spent": balance["spent"],
        "revenue": balance["verified_revenue"],  # recognized (VERIFIED) revenue
        "verified_revenue": balance["verified_revenue"],
        "pending_revenue": balance["pending_revenue"],
        "total_revenue": balance["verified_revenue"] + balance["pending_revenue"],
        "fees": balance["fees"],
        "refunds": balance["refunds"],
        "net_profit": (
            balance["verified_revenue"]
            - balance["spent"]
            - balance["fees"]
            + balance["refunds"]
        ),
        "revenue_statuses": revenue_statuses,
        "entry_count": len(session.execute(select(LedgerEntry.id)).scalars().all()),
        "target_paise": get_config().orion.target,
    }


# ---------------------------------------------------------------------------
# Writes (append-only)
# ---------------------------------------------------------------------------


def _write(
    session,
    *,
    type_: EventType,
    amount_paise: int,
    source: str,
    destination: str = "",
    reference: Optional[str] = None,
    status: Optional[str] = None,
    verification_method: Optional[str] = None,
    confidence: Optional[float] = None,
    metadata_json: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> LedgerEntry:
    """Insert one entry, flush, then re-verify the invariant against the log."""
    if type_ == EventType.ADJUSTMENT:
        _require(
            isinstance(amount_paise, int)
            and not isinstance(amount_paise, bool)
            and amount_paise != 0,
            f"adjustment amount must be a non-zero integer, got {amount_paise!r}",
        )
    else:
        _require_positive(amount_paise)
    entry = LedgerEntry(
        type=type_.value,
        amount_paise=amount_paise,
        source=source,
        destination=destination,
        reference=reference,
        status=status or _STATUS_BY_TYPE[type_],
        verification_method=verification_method,
        confidence=confidence,
        metadata_json=metadata_json,
        correlation_id=correlation_id,
    )
    session.add(entry)
    session.flush()  # make the entry visible to the invariant replay
    _replay(session)
    log.info(
        "ledger write",
        extra={
            "type": type_.value,
            "amount_paise": amount_paise,
            "source": source,
            "status": entry.status,
        },
    )
    return entry


def seed_capital(session, amount_paise: int) -> LedgerEntry:
    """Inject starting capital exactly once (idempotent per database)."""
    setting = (
        session.execute(
            select(SystemSetting).where(SystemSetting.key == SEED_SETTING_KEY)
        )
        .scalars()
        .first()
    )
    if setting is not None:
        log.debug("capital already seeded", extra={"amount_paise": setting.value})
        seed_entry = (
            session.execute(
                select(LedgerEntry).where(LedgerEntry.reference == "seed_capital")
            )
            .scalars()
            .first()
        )
        return seed_entry

    entry = _write(
        session,
        type_=EventType.DEPOSIT,
        amount_paise=amount_paise,
        source="system",
        destination="orion",
        reference="seed_capital",
    )
    session.add(SystemSetting(key=SEED_SETTING_KEY, value=str(amount_paise)))
    session.flush()  # visible to a later seed_capital within the same session
    return entry


def deposit(
    session,
    amount_paise: int,
    source: str,
    reference: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> LedgerEntry:
    """Record outside money injected into the wallet."""
    return _write(
        session,
        type_=EventType.DEPOSIT,
        amount_paise=amount_paise,
        source=source,
        destination="orion",
        reference=reference or "deposit",
        correlation_id=correlation_id,
    )


def reserve(
    session,
    amount_paise: int,
    destination: str,
    reference: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> LedgerEntry:
    """Set cash aside for a planned spend (available -> reserved)."""
    return _write(
        session,
        type_=EventType.RESERVE,
        amount_paise=amount_paise,
        source="orion",
        destination=destination,
        reference=reference or "reserve",
        correlation_id=correlation_id,
    )


def spend(
    session,
    amount_paise: int,
    destination: str,
    reference: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> LedgerEntry:
    """Pay money out. Draws from reserved cash first, then available.

    Enforces the configured single-spend / daily-spend / total-loss guardrails.
    """
    guardrails = get_config().risk_guardrails
    if amount_paise > guardrails.max_single_spend:
        raise ValueError(
            f"spend {amount_paise} exceeds max_single_spend "
            f"{guardrails.max_single_spend}"
        )

    balance = _replay(session)
    today = utc_now_iso()[:10]
    today_spent = 0
    for entry in session.execute(
        select(LedgerEntry).where(LedgerEntry.type == EventType.SPEND)
    ).scalars():
        if entry.created_at[:10] == today:
            today_spent += entry.amount_paise
    if today_spent + amount_paise > guardrails.max_daily_spend:
        raise ValueError(
            f"spend would break max_daily_spend {guardrails.max_daily_spend}"
        )
    if (
        balance["spent"] - balance["refunds"]
    ) + amount_paise > guardrails.max_total_loss:
        raise ValueError(
            f"spend would break max_total_loss {guardrails.max_total_loss}"
        )

    return _write(
        session,
        type_=EventType.SPEND,
        amount_paise=amount_paise,
        source="orion",
        destination=destination,
        reference=reference or "spend",
        correlation_id=correlation_id,
    )


def release_reserve(
    session,
    amount_paise: int,
    reference: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> LedgerEntry:
    """Cancel part/all of a reservation (reserved -> available)."""
    return _write(
        session,
        type_=EventType.RELEASE_RESERVE,
        amount_paise=amount_paise,
        source="orion",
        destination="orion",
        reference=reference or "release_reserve",
        correlation_id=correlation_id,
    )


def record_revenue(
    session,
    amount_paise: int,
    source: str,
    reference: str,
    verification_method: Optional[str] = None,
    confidence: float = 0.0,
    correlation_id: Optional[str] = None,
) -> LedgerEntry:
    """Record earned revenue.

    VERIFIED only when ``verification_method`` is provided AND
    ``confidence >= 0.9``. Otherwise the entry stays ESTIMATED (no method) or
    PENDING (method, low confidence) and does not touch available cash.
    """
    verified = (
        bool(verification_method)
        and confidence is not None
        and confidence >= VERIFIED_CONFIDENCE_THRESHOLD
    )
    status = (
        RevenueStatus.VERIFIED
        if verified
        else (RevenueStatus.PENDING if verification_method else RevenueStatus.ESTIMATED)
    )
    return _write(
        session,
        type_=EventType.REVENUE,
        amount_paise=amount_paise,
        source=source,
        destination="orion",
        reference=reference,
        status=status.value,
        verification_method=verification_method,
        confidence=float(confidence),
        correlation_id=correlation_id,
    )


def record_fee(
    session,
    amount_paise: int,
    source: str,
    reference: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> LedgerEntry:
    """Charge a cost of earning against verified revenue (see module docstring)."""
    return _write(
        session,
        type_=EventType.FEE,
        amount_paise=amount_paise,
        source=source,
        destination="orion",
        reference=reference or "fee",
        correlation_id=correlation_id,
    )


def record_refund(
    session,
    amount_paise: int,
    source: str,
    reference: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> LedgerEntry:
    """Record money returned on a purchase: reverses part of ``spent``."""
    return _write(
        session,
        type_=EventType.REFUND,
        amount_paise=amount_paise,
        source=source,
        destination="orion",
        reference=reference or "refund",
        correlation_id=correlation_id,
    )


def record_dispute(
    session,
    amount_paise: int,
    revenue_reference: str,
    reason: str = "",
) -> LedgerEntry:
    """Mark a VERIFIED revenue disputed: retract it from cash and recognition.

    ``revenue_reference`` must match a previously recorded VERIFIED REVENUE
    entry (matched additionally by amount). That entry's status is flipped to
    DISPUTED as the audit trail; the new DISPUTE event carries the retraction.
    """
    target = (
        session.execute(
            select(LedgerEntry).where(
                LedgerEntry.type == EventType.REVENUE,
                LedgerEntry.reference == revenue_reference,
                LedgerEntry.status == RevenueStatus.VERIFIED,
            )
        )
        .scalars()
        .first()
    )
    _require(
        target is not None, f"no VERIFIED revenue with reference {revenue_reference!r}"
    )
    _require(
        target.amount_paise == amount_paise,
        "dispute amount must match the revenue entry",
    )

    entry = _write(
        session,
        type_=EventType.DISPUTE,
        amount_paise=amount_paise,
        source="orion",
        destination=target.source,
        reference=revenue_reference,
        metadata_json=json.dumps({"reason": reason, "disputed_entry_id": target.id}),
    )
    target.status = RevenueStatus.DISPUTED
    return entry


def record_adjustment(
    session,
    amount_paise: int,
    source: str,
    reference: Optional[str] = None,
    note: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> LedgerEntry:
    """Manual books correction. May be negative; adjusts capital and cash."""
    meta = json.dumps({"note": note}) if note else None
    return _write(
        session,
        type_=EventType.ADJUSTMENT,
        amount_paise=amount_paise,
        source=source,
        destination="orion",
        reference=reference or f"adjustment:{'+' if amount_paise > 0 else '-'}",
        metadata_json=meta,
        correlation_id=correlation_id,
    )


def kill_switch_state(session) -> dict[str, Any]:
    """Return the singleton KillSwitch row (creating it if absent)."""
    from orion.models import KillSwitch

    ks = session.get(KillSwitch, 1)
    if ks is None:
        ks = KillSwitch(id=1, active=False, reason=None)
        session.add(ks)
        session.flush()
    return {"active": ks.active, "reason": ks.reason}
