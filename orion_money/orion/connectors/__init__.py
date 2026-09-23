"""Opportunity connectors — standardized sources of :class:`SourceOffer`.

``MockConnector`` powers the offline pipeline; ``RealMarketplaceConnector``
is an explicit NOT IMPLEMENTED stub (never fakes automation, never hits the
network). See ``orion.connectors.base.ConnectorBase`` for the protocol.
"""

from orion.connectors.base import (
    ConnectorBase,
    SourceOffer,
    offer_content_hash,
    offer_hash,
)
from orion.connectors.mock import MockConnector
from orion.connectors.real_marketplace import RealMarketplaceConnector

__all__ = [
    "ConnectorBase",
    "SourceOffer",
    "offer_content_hash",
    "offer_hash",
    "MockConnector",
    "RealMarketplaceConnector",
]
