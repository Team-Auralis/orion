"""Real marketplace connector — explicit NOT IMPLEMENTED stub.

Project rule: never fake automation we don't have. When ``enabled`` in
config this raises ``NotImplementedError`` with the approval instructions;
when disabled it returns an empty list. It NEVER hits the network in
either state.
"""

from __future__ import annotations

from orion.config import get_config

_NOT_IMPLEMENTED_MSG = (
    "real marketplace connector is NOT IMPLEMENTED — approve a real "
    "connector by writing one and setting enabled: true"
)


class RealMarketplaceConnector:
    """Placeholder for a live marketplace API integration."""

    name = "real_marketplace"
    is_mock = False

    @property
    def enabled(self) -> bool:
        return get_config().connectors.real_marketplace.enabled

    async def fetch(self):
        """Disabled -> ``[]``. Enabled -> loud NotImplementedError (no network)."""
        if not self.enabled:
            return []
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def health(self) -> dict:
        return {
            "name": self.name,
            "is_mock": self.is_mock,
            "enabled": self.enabled,
            "offers": 0,
            "implemented": False,
        }
