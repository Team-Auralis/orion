"""Tests for orion.discovery — scan/dedupe, status lifecycle, decision gate.
Fresh SQLite/config per test.
"""

from __future__ import annotations

import time

import pytest

from orion.config import get_config
from orion.connectors import MockConnector
from orion.db import _reset_engine, get_session, init_db
from orion.discovery import DiscoveryService, OpportunityStatus
from orion.models import Opportunity
from orion.scoring import OpportunityScorer, detect_suspicious


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("ORION_DATA_DIR", str(tmp_path))
    _reset_engine()
    get_config(force_reload=True)
    init_db()
    yield
    _reset_engine()


def _catalog():
    return MockConnector().catalog()


# ---------------------------------------------------------------------------
# scan creates opportunities
# ---------------------------------------------------------------------------


def test_scan_creates_opportunity_rows(db):
    service = DiscoveryService()
    catalog = _catalog()
    with get_session() as session:
        new = service.scan(session)
        assert len(new) == len(catalog)
        rows = session.query(Opportunity).all()
        assert len(rows) == len(catalog)
        for row, offer in zip(rows, catalog):
            assert row.status == OpportunityStatus.DISCOVERED.value
            assert row.content_hash  # dedupe key present
            assert row.name == offer.title
            assert row.source == offer.source
            assert row.estimated_value_paise == offer.estimated_value_paise
            assert row.suspicious is False  # scanner does not judge


def test_scan_filters_disabled_connectors(db):
    """real_marketplace is disabled by default -> only mock offers."""
    service = DiscoveryService()
    with get_session() as session:
        new = service.scan(session)
        assert len(new) == len(_catalog())
        assert {r.source_connector for r in new} == {"mock"}


# ---------------------------------------------------------------------------
# duplicate scans collapse
# ---------------------------------------------------------------------------


def test_duplicate_scan_updates_last_seen_only(db):
    service = DiscoveryService()
    with get_session() as session:
        first = service.scan(session)
        assert len(first) == len(_catalog())
        first_count = session.query(Opportunity).count()
        before = {r.id: r.last_seen for r in session.query(Opportunity)}

        time.sleep(0.002)  # ensure last_seen timestamps can differ
        second = service.scan(session)
        assert second == []  # no NEW opportunities
        assert session.query(Opportunity).count() == first_count  # row stable

        for row in session.query(Opportunity):
            assert row.last_seen >= before[row.id]  # refreshed, not re-inserted
            assert row.status == OpportunityStatus.DISCOVERED.value


def test_content_hash_collapses_normalized_duplicates(db):
    """Identical title/source/description with different whitespace/case."""
    from orion.connectors.base import offer_content_hash

    a = offer_content_hash("  Notion   Template   ", "Mock", "desc")
    b = offer_content_hash("notion template", "mock", "desc")
    assert a == b


# ---------------------------------------------------------------------------
# DISCOVERED -> SCORED (and suspicious -> REJECTED)
# ---------------------------------------------------------------------------


def test_score_advances_status(db):
    service = DiscoveryService()
    scorer = OpportunityScorer()
    clean = [o for o in _catalog() if not detect_suspicious(o)][0]
    with get_session() as session:
        service.scan(session)
        row = scorer.score_opportunity_from_offer(clean, session)
        assert row.status == OpportunityStatus.SCORED.value
        assert row.score_0_100 is not None
        assert 0.0 <= row.score_0_100 <= 100.0
        assert row.factors_json is not None
        assert row.suspicious is False


def test_suspicious_offer_scored_rejected(db):
    service = DiscoveryService()
    scorer = OpportunityScorer()
    scam = [o for o in _catalog() if detect_suspicious(o)][0]
    with get_session() as session:
        service.scan(session)
        row = scorer.score_opportunity_from_offer(scam, session)
        assert row.status == OpportunityStatus.REJECTED.value
        assert row.suspicious is True
        assert row.suspicious_reason
        assert row.rejected_reason == row.suspicious_reason
        assert row.score_0_100 <= 10.0


def test_score_unknown_offer_raises(db):
    from orion.scoring import OpportunityScorer

    with get_session() as session:
        with pytest.raises(ValueError):
            OpportunityScorer().score_opportunity_from_offer(
                MockConnector().catalog()[0], session
            )  # no row scanned yet


# ---------------------------------------------------------------------------
# decision gate: suspicious never reaches PENDING
# ---------------------------------------------------------------------------


def test_clean_scored_offer_reaches_pending(db):
    service = DiscoveryService()
    scorer = OpportunityScorer()
    with get_session() as session:
        service.scan(session)
        clean = [o for o in _catalog() if not detect_suspicious(o)][0]
        row = scorer.score_opportunity_from_offer(clean, session)
        row = service.submit_for_decision(row.id, session=session)
        assert row.status == OpportunityStatus.PENDING.value


def test_suspicious_offer_never_reaches_pending(db):
    service = DiscoveryService()
    scorer = OpportunityScorer()
    scam = [o for o in _catalog() if detect_suspicious(o)][0]
    with get_session() as session:
        service.scan(session)
        row = scorer.score_opportunity_from_offer(scam, session)
        assert row.status == OpportunityStatus.REJECTED.value
        with pytest.raises(ValueError, match="never enters"):
            service.submit_for_decision(row.id, session=session)
        assert row.status == OpportunityStatus.REJECTED.value  # unchanged


def test_unscored_offer_cannot_reach_pending(db):
    service = DiscoveryService()
    with get_session() as session:
        service.scan(session)
        rows = session.query(Opportunity).all()
        with pytest.raises(ValueError, match="must be SCORED"):
            service.submit_for_decision(rows[0].id, session=session)
        assert rows[0].status == OpportunityStatus.DISCOVERED.value


# ---------------------------------------------------------------------------
# list / get
# ---------------------------------------------------------------------------


def test_list_and_get(db):
    service = DiscoveryService()
    scorer = OpportunityScorer()
    with get_session() as session:
        service.scan(session)
        offered = [o for o in _catalog() if not detect_suspicious(o)]
        for o in offered:
            scorer.score_opportunity_from_offer(o, session)
        for scam in [o for o in _catalog() if detect_suspicious(o)]:
            scorer.score_opportunity_from_offer(scam, session)

        all_rows = service.list_opportunities(session=session)
        assert len(all_rows) == len(_catalog())
        scored = service.list_opportunities(
            session=session, status=OpportunityStatus.SCORED.value
        )
        assert len(scored) == len(offered)
        rejected = service.list_opportunities(
            session=session, status=OpportunityStatus.REJECTED.value
        )
        assert len(rejected) == len(_catalog()) - len(offered)

        first_id = all_rows[0].id
        assert service.get(first_id, session=session).id == first_id

    # after the outer session commits, the auto-session path sees the row
    assert service.get(first_id).id == first_id


def test_get_missing_raises(db):
    with get_session() as session:
        with pytest.raises(ValueError, match="not found"):
            DiscoveryService().get(99999, session=session)


def test_list_limit(db):
    service = DiscoveryService()
    with get_session() as session:
        service.scan(session)
        rows = service.list_opportunities(session=session, limit=5)
        assert len(rows) == 5
