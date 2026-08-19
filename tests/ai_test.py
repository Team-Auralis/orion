import httpx
import time

API_URL = "http://localhost:8001/v1"
HEADERS = {"Authorization": "Bearer MOCK_TOKEN_OPERATOR"}

def test_ai_sentinel():
    print("\n--- Testing Phase 0.3: SENTIENCE AI Routing ---")
    
    incidents = [
        {"msg": "Help, my house is flooding on 5th street, water is rising fast!", "expected": "HIGH/FLOODING"},
        {"msg": "Fire! The building is filled with smoke, people are trapped!", "expected": "CRITICAL/FIRE/RESCUE_REQUIRED"},
        {"msg": "Need assistance with a minor traffic collision.", "expected": "LOW/GENERAL"}
    ]
    
    for inc in incidents:
        print(f"\n-> Submitting: '{inc['msg']}'")
        payload = {
            "type": "SOS",
            "location": {"latitude": 34.0, "longitude": -118.0},
            "message": inc['msg'],
            "source": "citizen_app"
        }
        resp = httpx.post(f"{API_URL}/incidents", json=payload, headers=HEADERS)
        incident_id = resp.json().get("incident_id")
        print(f"Created: {incident_id}")
        
    print("\nWaiting for AI Sentinel to process...")
    time.sleep(3.0)
    
    print("\n-> Checking Dashboard API...")
    resp = httpx.get(f"{API_URL}/incidents", headers=HEADERS)
    data = resp.json()
    
    for inc in data[:3]:
        print(f"ID: {inc['incident_id']} | Status: {inc['status']} | Severity: {inc['ai_severity']} | Tags: {inc['ai_tags']}")

if __name__ == "__main__":
    test_ai_sentinel()
