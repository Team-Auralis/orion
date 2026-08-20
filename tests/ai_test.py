import httpx
import time
import json

API_URL = "http://localhost:8001/v1"
KEYCLOAK_URL = "http://localhost:8080/realms/orion/protocol/openid-connect/token"

def get_token(username, password):
    data = {
        "client_id": "orion-api",
        "grant_type": "password",
        "username": username,
        "password": password
    }
    resp = httpx.post(KEYCLOAK_URL, data=data)
    return resp.json()["access_token"]

OPERATOR_TOKEN = get_token("operator1", "operatorpass")
HEADERS = {"Authorization": f"Bearer {OPERATOR_TOKEN}"}

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
