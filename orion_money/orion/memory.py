"""SQL-backed memory subsystem: facts, beliefs, hypotheses, evidence.

Model
-----
Every memory row lives in ``memory_items`` (see :mod:`orion.models.MemoryItem`)
and is discriminated by ``kind``:

* FACT — what actually happened. Only enters as a fact when ``verified`` is
  set OR it carries an evidence linkage; ``add_fact`` refuses both missing
  (anti-hallucination). A fact linked to evidence is automatically ``verified``.
* BELIEF — what ORION currently thinks. Weighted (``confidence``), may be
  wrong, and never silently becomes a fact (no promotion path exists).
* HYPOTHESIS — a testable statement with a lifecycle status
  ``proposed -> confirmed | refuted`` (see :func:`update_hypothesis`).
* EVIDENCE — an observation linked to a ledger entry or experiment id
  (``reference``) that supports or contradicts a claim (``direction``).

Anti-hallucination rule (enforced here): hypothesis -> evidence -> fact, never
hypothesis -> fact directly. :func:`promote_hypothesis_to_fact` refuses to run
unless a *supporting* evidence row exists for the hypothesis.
"""

from __future__ import annotations

import enum
import json
from typing import Any, Optional

from sqlalchemy import select

from orion.db import get_session  # noqa: F401  (re-exported convenience)
from orion.log import get_logger
from orion.models import MemoryItem

log = get_logger("memory")

# Statuses a hypothesis must transition through.
VALID_HYPOTHESIS_STATUSES = {"proposed", "confirmed", "refuted"}


class MemoryKind(str, enum.Enum):
    FACT = "fact"
    BELIEF = "belief"
    HYPOTHESIS = "hypothesis"
    EVIDENCE = "evidence"


class EvidenceDirection(str, enum.Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"


class HypothesisStatus(str, enum.Enum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    REFUTED = "refuted"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _to_json(value: Any) -> Optional[str]:
    """Serialize a dict/list to a JSON string; pass strings through as-is."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_json(text: Optional[str]) -> dict[str, Any]:
    if not text:
        return {}
    try:
        loaded = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return {"raw": text}
    return loaded if isinstance(loaded, dict) else {"raw": loaded}


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def add_fact(
    session,
    text: str,
    *,
    verified: bool = False,
    evidence_reference: Optional[str] = None,
    source: Optional[str] = None,
    confidence: Optional[float] = None,
) -> MemoryItem:
    """Record a fact.

    Anti-hallucination: a fact must be explicitly ``verified`` or carry an
    ``evidence_reference``; both missing is refused. An evidence-linked fact
    is treated as verified (the evidence IS the verification).
    """
    _require(bool(text.strip()), "fact text must not be empty")
    _require(
        verified or bool(evidence_reference),
        "a fact requires verified=True or an evidence_reference "
        "(facts can never enter unverified)",
    )
    row = MemoryItem(
        kind=MemoryKind.FACT.value,
        content=text.strip(),
        verified=verified or bool(evidence_reference),
        reference=evidence_reference,
        source=source,
        confidence=confidence,
    )
    session.add(row)
    session.flush()
    log.info("memory add_fact", extra={"id": row.id, "verified": row.verified})
    return row


def add_belief(
    session, text: str, weight: float, source: Optional[str] = None
) -> MemoryItem:
    """Record a belief with a weight in [0, 1]. Beliefs never become facts."""
    _require(bool(text.strip()), "belief text must not be empty")
    _require(
        isinstance(weight, (int, float))
        and not isinstance(weight, bool)
        and 0.0 <= weight <= 1.0,
        f"belief weight must be in [0, 1], got {weight!r}",
    )
    row = MemoryItem(
        kind=MemoryKind.BELIEF.value,
        content=text.strip(),
        confidence=float(weight),
        source=source,
    )
    session.add(row)
    session.flush()
    log.info("memory add_belief", extra={"id": row.id, "weight": row.confidence})
    return row


def add_hypothesis(
    session,
    text: str,
    params_json: Any = None,
    status: str = HypothesisStatus.PROPOSED.value,
    source: Optional[str] = None,
) -> MemoryItem:
    """Record a testable hypothesis (status ``proposed`` by default)."""
    _require(bool(text.strip()), "hypothesis text must not be empty")
    _require(
        status in VALID_HYPOTHESIS_STATUSES, f"invalid hypothesis status {status!r}"
    )
    row = MemoryItem(
        kind=MemoryKind.HYPOTHESIS.value,
        content=text.strip(),
        payload_json=_to_json(params_json),
        status=status,
        source=source,
    )
    session.add(row)
    session.flush()
    log.info("memory add_hypothesis", extra={"id": row.id, "status": row.status})
    return row


def add_evidence(
    session,
    text: str,
    claim_kind: str,
    direction: str,
    reference: str,
    source: Optional[str] = None,
) -> MemoryItem:
    """Record an observation supporting/contradicting a claim.

    ``reference`` links the observation to a ledger entry id or experiment id
    (e.g. ``"ledger:42"`` or ``"experiment:sweep-7"``); ``claim_kind`` names
    the claim it bears on (kept in ``payload_json``).
    """
    _require(bool(text.strip()), "evidence text must not be empty")
    _require(
        direction in {d.value for d in EvidenceDirection},
        f"evidence direction must be supports|contradicts, got {direction!r}",
    )
    _require(bool(claim_kind.strip()), "claim_kind must not be empty")
    _require(bool(reference), "evidence requires a reference (ledger/experiment id)")
    row = MemoryItem(
        kind=MemoryKind.EVIDENCE.value,
        content=text.strip(),
        payload_json=_to_json({"claim_kind": claim_kind}),
        direction=direction,
        reference=reference,
        source=source,
    )
    session.add(row)
    session.flush()
    log.info(
        "memory add_evidence",
        extra={"id": row.id, "direction": row.direction, "reference": row.reference},
    )
    return row


# ---------------------------------------------------------------------------
# Queries / lifecycle
# ---------------------------------------------------------------------------


def query(
    session,
    category: Optional[str] = None,
    text_contains: Optional[str] = None,
    limit: int = 50,
) -> list[MemoryItem]:
    """Memory rows, newest first, filtered by ``category`` / substring."""
    stmt = select(MemoryItem)
    if category is not None:
        _require(
            category in {k.value for k in MemoryKind},
            f"unknown memory category {category!r}",
        )
        stmt = stmt.where(MemoryItem.kind == category)
    if text_contains:
        stmt = stmt.where(MemoryItem.content.ilike(f"%{text_contains}%"))
    stmt = stmt.order_by(MemoryItem.id.desc()).limit(limit)
    return list(session.execute(stmt).scalars())


def update_hypothesis(
    session, id: int, status: str, observed_result: Any
) -> MemoryItem:
    """Transition a hypothesis and attach the observation that motivated it."""
    row = session.get(MemoryItem, id)
    _require(row is not None, f"no memory row with id {id}")
    _require(row.kind == MemoryKind.HYPOTHESIS.value, f"row {id} is not a hypothesis")
    _require(
        status in VALID_HYPOTHESIS_STATUSES, f"invalid hypothesis status {status!r}"
    )
    payload = _load_json(row.payload_json)
    payload["observed_result"] = observed_result
    row.payload_json = _to_json(payload)
    row.status = status
    session.flush()
    log.info("memory update_hypothesis", extra={"id": id, "status": status})
    return row


def promote_hypothesis_to_fact(session, id: int, evidence_id: int) -> MemoryItem:
    """Promote a hypothesis to a fact — ONLY backed by supporting evidence.

    Anti-hallucination: refuses unless the given evidence row exists, is an
    EVIDENCE row and ``direction == "supports"``. The hypothesis is marked
    ``confirmed``; a new verified FACT row is created linked to the evidence.
    """
    hypothesis = session.get(MemoryItem, id)
    _require(
        hypothesis is not None and hypothesis.kind == MemoryKind.HYPOTHESIS.value,
        f"row {id} is not a hypothesis (can only promote hypotheses)",
    )
    evidence = session.get(MemoryItem, evidence_id)
    _require(
        evidence is not None and evidence.kind == MemoryKind.EVIDENCE.value,
        f"row {evidence_id} is not an evidence row — no supporting evidence to promote on",
    )
    _require(
        evidence.direction == EvidenceDirection.SUPPORTS.value,
        f"evidence {evidence_id} contradicts the claim; it cannot promote a hypothesis",
    )

    payload = _load_json(hypothesis.payload_json)
    payload["hypothesis_id"] = id
    fact = MemoryItem(
        kind=MemoryKind.FACT.value,
        content=hypothesis.content,
        verified=True,
        reference=f"evidence:{evidence_id}",
        payload_json=_to_json(payload),
        confidence=evidence.confidence,
        source=f"promoted:{id}",
    )
    session.add(fact)
    hypothesis.status = HypothesisStatus.CONFIRMED.value
    session.flush()
    log.info(
        "memory promote_hypothesis_to_fact",
        extra={"hypothesis_id": id, "evidence_id": evidence_id, "fact_id": fact.id},
    )
    return fact


def get_summary(session) -> dict[str, Any]:
    """Aggregate counts of every memory kind (and kind-specific state)."""
    rows = list(session.execute(select(MemoryItem)).scalars())
    counts: dict[str, int] = {k.value: 0 for k in MemoryKind}
    for row in rows:
        counts[row.kind] = counts.get(row.kind, 0) + 1

    beliefs = [r for r in rows if r.kind == MemoryKind.BELIEF.value]
    belief_avg = (
        sum(r.confidence or 0.0 for r in beliefs) / len(beliefs) if beliefs else None
    )
    hyp_status: dict[str, int] = {}
    ev_direction: dict[str, int] = {}
    for row in rows:
        if row.kind == MemoryKind.HYPOTHESIS.value:
            key = row.status or HypothesisStatus.PROPOSED.value
            hyp_status[key] = hyp_status.get(key, 0) + 1
        elif row.kind == MemoryKind.EVIDENCE.value:
            key = row.direction or ""
            ev_direction[key] = ev_direction.get(key, 0) + 1

    return {
        "total": len(rows),
        "counts": counts,
        "verified_facts": sum(
            1 for r in rows if r.kind == MemoryKind.FACT.value and r.verified
        ),
        "belief_avg_weight": belief_avg,
        "hypotheses_by_status": hyp_status,
        "evidence_by_direction": ev_direction,
    }
