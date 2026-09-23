"""Opportunity connectors — standardized sources of :class:`SourceOffer`.

``MockConnector`` powers the offline pipeline; ``RealMarketplaceConnector``
is an explicit NOT IMPLEMENTED stub (never fakes automation, never hits the
network). ``GumroadConnector`` publishes products to Gumroad (official API
first, then draft-bundle fallback). See ``orion.connectors.base.ConnectorBase``
for the protocol.
"""

from orion.connectors.base import (
    ConnectorBase,
    SourceOffer,
    offer_content_hash,
    offer_hash,
)
from orion.connectors.mock import MockConnector
from orion.connectors.real_marketplace import RealMarketplaceConnector
from orion.connectors.gumroad import GumroadConnector

__all__ = [
    "ConnectorBase",
    "SourceOffer",
    "offer_content_hash",
    "offer_hash",
    "MockConnector",
    "RealMarketplaceConnector",
    "GumroadConnector",
]
