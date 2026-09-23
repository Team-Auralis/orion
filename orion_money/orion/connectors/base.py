"""Connector protocol and the standardized offer record.

Every opportunity source (mock catalog, real marketplace, future
connectors) yields :class:`SourceOffer` — one normalized shape the
discovery/scoring pipeline can process without caring where it came from.
All money is INTEGER PAISE. Connectors are async (``fetch``); ``health`` is
a cheap sync status dict.

Offers are untrusted external data: fields are validated (non-negative
money, 0..1 hints) but descriptions/titles are treated as plain text and
never executed or merged into prompts unlabelled.
"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field, field_validator


class SourceOffer(BaseModel):
    """Standardized opportunity record from any connector."""

    title: str
    source: str
    url: str = ""
    description: str = ""
    estimated_value_paise: int = Field(default=0, ge=0)  # ₹ revenue, paise
    cost_paise: int = Field(default=0, ge=0)  # startup cost, paise
    deadline: str | None = None  # optional free-form / ISO date
    required_skills: list[str] = Field(default_factory=list)
    automation_allowed: bool = False
    platform_notes: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    demand_hint: float = Field(default=0.5, ge=0.0, le=1.0)
    competition_hint: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("estimated_value_paise", "cost_paise")
    @classmethod
    def _non_negative_money(cls, v: int) -> int:
        if v < 0:
            raise ValueError("money fields must be >= 0 paise")
        return v


@runtime_checkable
class ConnectorBase(Protocol):
    """What every opportunity connector looks like."""

    name: str
    is_mock: bool

    async def fetch(self) -> list[SourceOffer]:
        """Return the connector's current offer list (may be empty)."""
        ...

    def health(self) -> dict:
        """Cheap status dict (name, enabled/implemented, counts)."""
        ...


_WS = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WS.sub(" ", (text or "").strip().lower())


def offer_content_hash(title: str, source: str, description: str) -> str:
    """Canonical dedupe key: sha256 over normalized title+source+description.

    Normalization = strip + lowercase + collapse whitespace, so trivial
    formatting differences between scans map to the same row.
    """
    canonical = "\n".join(
        (_normalize(title), _normalize(source), _normalize(description))
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def offer_hash(offer: SourceOffer) -> str:
    """:func:`offer_content_hash` for a :class:`SourceOffer`."""
    return offer_content_hash(offer.title, offer.source, offer.description)
