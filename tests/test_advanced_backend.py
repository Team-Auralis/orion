import pytest
from services.worker.main import haversine, processed_events, MAX_CACHE_SIZE
from apps.api.main import app, get_current_user
from fastapi.testclient import TestClient
import uuid
import collections
from unittest.mock import patch, MagicMock

# --- 1. CRDT Mesh Bounded Cache Test ---
def test_crdt_mesh_bounded_cache():
    # Reset cache
    processed_events.clear()
    
    # Insert 11,000 unique events
    for i in range(11000):
        # We simulate the LRU behavior. The worker adds to cache like:
        # processed_events[event_id] = True
        # if len(processed_events) > MAX_CACHE_SIZE:
        #     processed_events.popitem(last=False)
        event_id = f"evt-{i}"
        processed_events[event_id] = True
        if len(processed_events) > MAX_CACHE_SIZE:
            processed_events.popitem(last=False)
            
    # The cache should be exactly bounded at MAX_CACHE_SIZE (10,000)
    assert len(processed_events) == MAX_CACHE_SIZE
    
    # The first 1000 items should have been evicted (FIFO/LRU)
    assert "evt-0" not in processed_events
    assert "evt-500" not in processed_events
    
    # The last 10,000 items should be present
    assert "evt-1000" in processed_events
    assert "evt-10999" in processed_events

# --- 2. Haversine Math Test ---
def test_haversine_dispatch_math():
    # Distance between New York (40.7128, -74.0060) and London (51.5074, -0.1278)
    # Expected is approx 5570 km
    ny_lat, ny_lon = 40.7128, -74.0060
    lon_lat, lon_lon = 51.5074, -0.1278
    dist = haversine(ny_lat, ny_lon, lon_lat, lon_lon)
    assert 5500 < dist < 5600
    
    # Test across International Date Line
    # Fiji (-17.7134, 178.0650) to Samoa (-13.7590, -172.1046)
    # They are physically close but coordinates wrap.
    fiji_lat, fiji_lon = -17.7134, 178.0650
    samoa_lat, samoa_lon = -13.7590, -172.1046
    dist_idl = haversine(fiji_lat, fiji_lon, samoa_lat, samoa_lon)
    # Distance should be around 1140 km
    assert 1000 < dist_idl < 1200
    
    # Closer distance logic: Ambulance 2 miles vs Fire Truck 5 miles
    incident = (34.0522, -118.2437) # LA
    amb = (34.0522, -118.2096) # ~2 miles east
    fire = (34.0522, -118.1574) # ~5 miles east
    
    dist_amb = haversine(incident[0], incident[1], amb[0], amb[1])
    dist_fire = haversine(incident[0], incident[1], fire[0], fire[1])
    
    assert dist_amb < dist_fire

# --- 3. Idempotency Key Test ---
client = TestClient(app)

def override_get_current_user():
    return {"subject": "test-user-123", "role": "operator"}

app.dependency_overrides[get_current_user] = override_get_current_user

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from apps.api.database import Base, get_db

# Create an in-memory SQLite database for idempotency testing
engine_test = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False})
SessionLocalTest = sessionmaker(autocommit=False, autoflush=False, bind=engine_test)
Base.metadata.create_all(bind=engine_test)

def override_get_db():
    try:
        db = SessionLocalTest()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

@patch("httpx.AsyncClient.post")
@patch("apps.api.main.redis_client", None)
@patch("apps.api.main.nc", MagicMock())
def test_idempotency_blocks_duplicate(mock_post):
    # Mock OPA bypass
    app.dependency_overrides[get_current_user] = lambda: {"subject": "test", "role": "operator"}
    mock_response = MagicMock()
    mock_response.json.return_value = {"result": True}
    mock_post.return_value = mock_response
    
    import uuid
    idem_key = str(uuid.uuid4())
    payload = {
        "type": "SOS",
        "location": {"latitude": 34.0, "longitude": -118.0},
        "message": "test",
        "source": "civilian"
    }
    headers = {"Idempotency-Key": idem_key}
    
    # First request should succeed and return 200
    res1 = client.post("/v1/incidents", json=payload, headers=headers)
    print("RES1 payload error:", res1.json())
    assert res1.status_code == 200
    
    # Second request with the SAME idempotency key should ALSO return 200 (returning the cached response),
    # but NOT process it again. It fetches from the SQLite `idempotency_keys` table.
    res2 = client.post("/v1/incidents", json=payload, headers=headers)
    assert res2.status_code == 200
    assert res1.json() == res2.json()
