import pytest
from fastapi.testclient import TestClient
from apps.api.main import app, get_current_user, get_db
from apps.api.database import Base, Asset, DispatchRecommendation, BreakGlassSession
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import datetime, timezone, timedelta

# Create in-memory SQLite for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

def override_get_current_user():
    return {"subject": "test-operator", "role": "operator"}

@pytest.fixture(autouse=True)
def isolated_overrides():
    saved = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    
    # Insert Break Glass Session to bypass OPA network calls!
    bg = BreakGlassSession(
        token="test-bg-token",
        user_id="test-operator",
        reason="Test bypass",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1)
    )
    db.merge(bg)
    
    asset = Asset(asset_id="TEST-AMB-01", type="AMBULANCE", latitude=0.0, longitude=0.0, status="IDLE")
    db.merge(asset)
    
    rec1 = DispatchRecommendation(
        id="rec-active",
        incident_id="INC-123",
        recommended_asset_id="TEST-AMB-01",
        status="PENDING",
        created_at=datetime.now(timezone.utc)
    )
    db.merge(rec1)
    
    rec2 = DispatchRecommendation(
        id="rec-expired",
        incident_id="INC-456",
        recommended_asset_id="TEST-AMB-01",
        status="PENDING",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=15)
    )
    db.merge(rec2)
    db.commit()
    db.close()
    
    yield
    
    Base.metadata.drop_all(bind=engine)

headers = {"X-Break-Glass-Token": "test-bg-token"}

from unittest.mock import patch

@patch("apps.api.main.redis_client", None)
def test_hitl_blocks_direct_dispatch():
    response = client.put("/v1/assets/TEST-AMB-01/status", json={"status": "DISPATCHED"}, headers=headers)
    assert response.status_code == 400
    assert "Invalid state" in response.json()["detail"]

@patch("apps.api.main.redis_client", None)
def test_hitl_blocks_expired_approval():
    response = client.post("/v1/dispatch/recommendations/rec-expired/action", json={"action": "APPROVE"}, headers=headers)
    assert response.status_code == 400
    assert "expired" in response.json()["detail"]

@patch("apps.api.main.redis_client", None)
def test_hitl_successful_approval_records_identity():
    response = client.post("/v1/dispatch/recommendations/rec-active/action", json={"action": "APPROVE"}, headers=headers)
    assert response.status_code == 200
    
    db = TestingSessionLocal()
    rec = db.query(DispatchRecommendation).filter_by(id="rec-active").first()
    assert rec.status == "APPROVED"
    assert rec.resolved_by == "test-operator"
    
    asset = db.query(Asset).filter_by(asset_id="TEST-AMB-01").first()
    assert asset.status == "DISPATCHED"
    db.close()
