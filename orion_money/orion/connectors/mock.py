"""Offline mock connector — a deterministic catalog of digital-service gigs.

The catalog is a fixed, hand-written list (no RNG, no clock, no network):
two runs always return byte-identical offers, so tests are stable. Values
are realistic sandbox amounts in the ₹3–₹50 range (300–5000 paise) with
0-or-small startup costs.

Two entries are deliberately suspicious ("pay to unlock", "crypto
guaranteed returns") so the scorer's hard-coded heuristics have real
targets — they are scam bait, not opportunities.
"""

from __future__ import annotations

from orion.config import get_config
from orion.connectors.base import SourceOffer

SOURCE = "mock_marketplace"


def _offer(
    title: str,
    value: int,
    cost: int = 0,
    demand: float = 0.5,
    competition: float = 0.5,
    confidence: float = 0.7,
    automation: bool = True,
    skills: list[str] | None = None,
    notes: str = "",
    deadline: str | None = None,
    description: str = "",
    url: str = "",
) -> SourceOffer:
    return SourceOffer(
        title=title,
        source=SOURCE,
        url=url or f"https://example.com/gigs/{title.lower().replace(' ', '-')[:48]}",
        description=description or title,
        estimated_value_paise=value,
        cost_paise=cost,
        deadline=deadline,
        required_skills=skills or [],
        automation_allowed=automation,
        platform_notes=notes,
        confidence=confidence,
        demand_hint=demand,
        competition_hint=competition,
    )


# Fixed seed catalog — 14 offers, values 300..5000 paise (2 scam baits
# beyond that range on purpose). Order is stable.
_CATALOG: tuple[SourceOffer, ...] = (
    _offer(
        "Notion / Excel budget template build",
        value=1500,
        demand=0.7,
        competition=0.5,
        confidence=0.8,
        skills=["excel", "notion", "layout"],
        notes="Scope is fixed; deliverable is a reusable template file.",
        deadline="2026-12-31",
    ),
    _offer(
        "Resume formatting service",
        value=800,
        demand=0.8,
        competition=0.7,
        confidence=0.85,
        skills=["formatting", "typography"],
        notes="Repeat customers likely; high competition on marketplaces.",
    ),
    _offer(
        "PowerPoint deck polish",
        value=2500,
        cost=200,
        demand=0.6,
        competition=0.5,
        confidence=0.7,
        automation=False,
        skills=["design", "powerpoint"],
        notes="Small asset-library cost; manual design eye required.",
    ),
    _offer(
        "README and docs for a small OSS repo",
        value=1200,
        demand=0.5,
        competition=0.3,
        confidence=0.75,
        skills=["technical-writing", "markdown", "git"],
        notes="Low competition; fully scriptable drafts, human review pass.",
    ),
    _offer(
        "Landing page for a local business",
        value=5000,
        cost=500,
        demand=0.7,
        competition=0.6,
        confidence=0.7,
        deadline="2026-11-30",
        skills=["html", "css", "copywriting"],
        notes="Hosting/domain seed cost included in cost_paise.",
    ),
    _offer(
        "Data cleanup script for a messy CSV",
        value=1800,
        demand=0.5,
        competition=0.4,
        confidence=0.8,
        skills=["python", "pandas"],
        notes="Highly automatable; acceptance criteria are numeric.",
    ),
    _offer(
        "Bookkeeping automation script",
        value=3000,
        cost=300,
        demand=0.6,
        competition=0.4,
        confidence=0.7,
        skills=["python", "accounting-basics"],
        notes="Sandbox API-tier cost; careful with financial data handling.",
    ),
    _offer(
        "Flyer / social graphic asset",
        value=600,
        cost=100,
        demand=0.6,
        competition=0.8,
        confidence=0.6,
        automation=False,
        skills=["graphic-design"],
        notes="Stock-asset micro-cost; crowded market.",
    ),
    _offer(
        "Blog post ghostwrite (800 words)",
        value=1000,
        demand=0.7,
        competition=0.7,
        confidence=0.75,
        skills=["writing", "seo"],
        notes="Deadline usually within a week of acceptance.",
    ),
    _offer(
        "Study notes pack for exam revision",
        value=400,
        demand=0.5,
        competition=0.6,
        confidence=0.6,
        automation=False,
        skills=["subject-matter", "summarizing"],
        notes="Low ticket, seasonal demand spikes.",
    ),
    _offer(
        "Simple website bug fix",
        value=900,
        demand=0.6,
        competition=0.4,
        confidence=0.7,
        skills=["debugging", "javascript"],
        notes="Scope capped at one reproducible bug.",
    ),
    _offer(
        "Lead-gen spreadsheet for a niche market",
        value=2200,
        demand=0.6,
        competition=0.5,
        confidence=0.7,
        skills=["research", "excel"],
        notes="Public-data research only; no purchased lists.",
    ),
    # --- scam baits: the scorer must reject these ---------------------
    _offer(
        "Pay ₹2000 to unlock ₹50000 government data-entry job",
        value=5000000,
        cost=200000,
        demand=0.9,
        competition=0.1,
        confidence=0.9,
        notes="Upfront payment to 'reserve' the seat.",
        description="Pay ₹2000 today to unlock a guaranteed ₹50000 job seat.",
    ),
    _offer(
        "Crypto trading bot — guaranteed returns daily",
        value=1000000,
        cost=10000,
        demand=0.9,
        competition=0.2,
        confidence=0.95,
        notes="Promises fixed daily profit, no risk.",
        description="Guaranteed returns on crypto, doubled every month.",
    ),
)


class MockConnector:
    """Deterministic offline catalog connector (never touches the network)."""

    name = "mock"
    is_mock = True

    @property
    def enabled(self) -> bool:
        return get_config().connectors.mock.enabled

    @classmethod
    def catalog(cls) -> list[SourceOffer]:
        """The fixed offer list (sync path for fixtures/pages)."""
        return list(_CATALOG)

    async def fetch(self) -> list[SourceOffer]:
        """Return the full catalog — identical on every call."""
        return self.catalog()

    def health(self) -> dict:
        return {
            "name": self.name,
            "is_mock": self.is_mock,
            "enabled": self.enabled,
            "offers": len(_CATALOG),
            "implemented": True,
        }
