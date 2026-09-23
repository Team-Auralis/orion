"""Opportunity discovery: connector scan -> deduped Opportunity rows.

Lifecycle statuses (:class:`OpportunityStatus`):

    DISCOVERED -> SCORED -> PENDING -> APPROVED -> REJECTED -> EXECUTED -> CLOSED

``scan`` persists new offers as ``DISCOVERED``; scoring (orion.scoring)
advances them to ``SCORED`` — or straight to ``REJECTED`` when suspicious,
so suspicious offers never reach ``PENDING``. Dedupe is a canonical
content hash (normalized title+source+description): a re-scan of an
existing offer only bumps ``last_seen`` on the existing row.
"""

from __future__ import annotations

import asyncio
import enum
import json
from typing import Optional, Sequence

from orion.connectors import (
    ConnectorBase,
    MockConnector,
    RealMarketplaceConnector,
    SourceOffer,
    offer_hash,
)
from orion.db import get_session
from orion.log import get_logger
from orion.models import Opportunity, utc_now_iso

log = get_logger("discovery")


class OpportunityStatus(str, enum.Enum):
    DISCOVERED = "DISCOVERED"  # persisted by scan
    SCORED = "SCORED"  # scored, clean, not yet submitted
    PENDING = "PENDING"  # awaiting a human/approval decision
    APPROVED = "APPROVED"  # decision: go
    REJECTED = "REJECTED"  # decision: no (or suspicious at scoring)
    EXECUTED = "EXECUTED"  # work delivered
    CLOSED = "CLOSED"  # terminal: done/abandoned


def _offer_to_row(offer: SourceOffer, connector_name: str) -> Opportunity:
    return Opportunity(
        name=offer.title.strip()[:255],
        kind=connector_name,
        payload_json=offer.model_dump_json(),
        status=OpportunityStatus.DISCOVERED.value,
        content_hash=offer_hash(offer),
        source=offer.source,
        source_connector=connector_name,
        url=offer.url,
        description=offer.description,
        estimated_value_paise=offer.estimated_value_paise,
        cost_paise=offer.cost_paise,
        deadline=offer.deadline,
        required_skills_json=json.dumps(offer.required_skills),
        automation_allowed=offer.automation_allowed,
        platform_notes=offer.platform_notes,
        confidence=offer.confidence,
        demand_hint=offer.demand_hint,
        competition_hint=offer.competition_hint,
        last_seen=utc_now_iso(),
    )


class DiscoveryService:
    """Runs enabled connectors and maintains the opportunities table."""

    def __init__(self, connectors: Optional[Sequence[ConnectorBase]] = None):
        self.connectors: list[ConnectorBase] = (
            list(connectors)
            if connectors is not None
            else [MockConnector(), RealMarketplaceConnector()]
        )

    def scan(self, session) -> list[Opportunity]:
        """Fetch every enabled connector, dedupe, persist, return NEW rows.

        Duplicate offers (same content hash) update ``last_seen`` on the
        existing row and are not returned. A connector that is enabled but
        NOT IMPLEMENTED raises — never faked. Runs the connectors' async
        ``fetch`` on a private event loop (callers must not already be
        inside one — use :meth:`scan_async` there).
        """
        return asyncio.run(self.scan_async(session))

    async def scan_async(self, session) -> list[Opportunity]:
        """:meth:`scan` without the event-loop bridge (for async callers)."""
        new_rows: list[Opportunity] = []
        for connector in self.connectors:
            if not getattr(connector, "enabled", True):
                log.info(
                    "connector skipped (disabled)",
                    extra={"connector": connector.name},
                )
                continue
            offers = await connector.fetch()
            for offer in offers:
                row = self._upsert_offer(offer, connector.name, session)
                if row is not None:
                    new_rows.append(row)
            log.info(
                "connector scanned",
                extra={"connector": connector.name, "offers": len(offers)},
            )
        session.flush()
        return new_rows

    def _upsert_offer(
        self, offer: SourceOffer, connector_name: str, session
    ) -> Optional[Opportunity]:
        """Insert a DISCOVERED row, or bump ``last_seen`` on the duplicate.

        Returns the new row, or ``None`` when the offer already existed.
        """
        h = offer_hash(offer)
        existing = (
            session.query(Opportunity).filter(Opportunity.content_hash == h).first()
        )
        if existing is not None:
            existing.last_seen = utc_now_iso()
            session.flush()
            return None
        row = _offer_to_row(offer, connector_name)
        session.add(row)
        session.flush()
        return row

    def list_opportunities(
        self,
        session=None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[Opportunity]:
        """Opportunities newest-first, optionally filtered by status."""
        if session is None:
            with get_session() as s:
                return self.list_opportunities(s, status=status, limit=limit)
        q = session.query(Opportunity)
        if status is not None:
            q = q.filter(Opportunity.status == str(status))
        return q.order_by(Opportunity.id.desc()).limit(limit).all()

    def get(self, id: int, session=None) -> Opportunity:
        """Fetch one opportunity by id; raises ValueError when missing."""
        if session is None:
            with get_session() as s:
                return self.get(id, session=s)
        row = session.get(Opportunity, id)
        if row is None:
            raise ValueError(f"opportunity {id} not found")
        return row

    def submit_for_decision(self, id: int, session=None) -> Opportunity:
        """SCORED -> PENDING (awaiting decision).

        Refuses anything that is not SCORED — in particular suspicious/
        REJECTED offers can never enter the approval flow.
        """
        if session is None:
            with get_session() as s:
                return self.submit_for_decision(id, session=s)
        row = self.get(id, session=session)
        if row.status == OpportunityStatus.REJECTED.value:
            raise ValueError(
                f"opportunity {id} rejected — never enters the decision flow"
                + (f" ({row.rejected_reason})" if row.rejected_reason else "")
            )
        if row.status != OpportunityStatus.SCORED.value:
            raise ValueError(
                f"opportunity {id} must be SCORED to submit (status={row.status})"
            )
        row.status = OpportunityStatus.PENDING.value
        session.flush()
        log.info("opportunity submitted for decision", extra={"id": id})
        return row
