"""Tests for orion.connectors — mock catalog, real stub, SourceOffer validation.
Fresh SQLite/config per test.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from orion.config import get_config
from orion.db import _reset_engine, init_db
from orion.connectors import MockConnector, RealMarketplaceConnector, SourceOffer


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("ORION_DATA_DIR", str(tmp_path))
    _reset_engine()
    get_config(force_reload=True)
    init_db()
    yield
    _reset_engine()


# ---------------------------------------------------------------------------
# MockConnector
# ---------------------------------------------------------------------------


def test_mock_returns_at_least_12_offers(db):
    offers = asyncio.run(MockConnector().fetch())
    assert len(offers) >= 12
    assert all(isinstance(o, SourceOffer) for o in offers)
    # money sanity: legit offers stay in the 300..5000 paise band (2 scam
    # baits sit far above it on purpose)
    values = sorted(o.estimated_value_paise for o in offers)
    assert values[0] >= 300
    assert MockConnector().is_mock is True


def test_mock_is_deterministic(db):
    a = asyncio.run(MockConnector().fetch())
    b = asyncio.run(MockConnector().fetch())
    assert [o.model_dump() for o in a] == [o.model_dump() for o in b]
    # stable across connector instances too
    c = asyncio.run(MockConnector().fetch())
    assert [o.title for o in a] == [o.title for o in c]


def test_mock_health(db):
    health = MockConnector().health()
    assert health["name"] == "mock"
    assert health["is_mock"] is True
    assert health["enabled"] is True
    assert health["offers"] >= 12


def test_mock_catalog_has_scam_baits(db):
    """Two deliberately suspicious offers must exist for the scorer tests."""
    from orion.scoring import detect_suspicious

    flagged = [o for o in MockConnector().catalog() if detect_suspicious(o)]
    assert 1 <= len(flagged) <= 4  # at least the 2 planted baits


# ---------------------------------------------------------------------------
# RealMarketplaceConnector (NOT IMPLEMENTED stub)
# ---------------------------------------------------------------------------


def test_real_disabled_returns_empty(db):
    conn = RealMarketplaceConnector()
    assert conn.enabled is False
    assert asyncio.run(conn.fetch()) == []
    health = conn.health()
    assert health["implemented"] is False
    assert health["enabled"] is False


def test_real_enabled_raises_not_implemented(db):
    cfg = get_config()
    cfg.connectors.real_marketplace.enabled = True
    conn = RealMarketplaceConnector()
    with pytest.raises(NotImplementedError) as exc:
        asyncio.run(conn.fetch())
    msg = str(exc.value)
    assert "real marketplace connector is NOT IMPLEMENTED" in msg
    assert "setting enabled: true" in msg
    cfg.connectors.real_marketplace.enabled = False


# ---------------------------------------------------------------------------
# SourceOffer validation
# ---------------------------------------------------------------------------


def test_sourceoffer_rejects_negative_money():
    with pytest.raises(ValidationError):
        SourceOffer(
            title="x", source="s", estimated_value_paise=-1, cost_paise=0
        )
    with pytest.raises(ValidationError):
        SourceOffer(
            title="x", source="s", estimated_value_paise=100, cost_paise=-5
        )


def test_sourceoffer_rejects_out_of_range_hints():
    with pytest.raises(ValidationError):
        SourceOffer(
            title="x", source="s", estimated_value_paise=100,
            demand_hint=1.5,
        )
    with pytest.raises(ValidationError):
        SourceOffer(
            title="x", source="s", estimated_value_paise=100,
            confidence=-0.1,
        )


def test_sourceoffer_minimal_valid():
    offer = SourceOffer(title="t", source="s", estimated_value_paise=0)
    assert offer.cost_paise == 0
    assert offer.automation_allowed is False
    assert 0.0 <= offer.confidence <= 1.0
