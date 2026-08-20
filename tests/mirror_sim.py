import httpx
import time
import random
import uuid

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

def inject_mirror_data():
    print("\n--- Injecting MIRROR Tactical Grid Data ---")
    
    incidents = [
        {"msg": "Flood waters rising rapidly on the east side.", "type": "SOS"},
        {"msg": "Fire reported in the industrial sector.", "type": "FIRE"},
        {"msg": "Car crash on the main highway, multiple injuries.", "type": "MEDICAL"},
        {"msg": "Building collapse, people trapped inside.", "type": "SOS"},
        {"msg": "Suspicious package found near the power grid.", "type": "SECURITY"},
        {"msg": "Minor power outage in residential block.", "type": "INFRASTRUCTURE"}
    ]
    
    for inc in incidents:
        # Bounding box: lat 33 to 35, lon -119 to -117
        lat = 34.0 + random.uniform(-0.8, 0.8)
        lon = -118.0 + random.uniform(-0.8, 0.8)
        
        payload = {
            "type": inc["type"],
            "location": {"latitude": lat, "longitude": lon},
            "message": inc['msg'],
            "source": "mirror_sim"
        }
        resp = httpx.post(f"{API_URL}/incidents", json=payload, headers=HEADERS)
        incident_id = resp.json().get("incident_id")
        print(f"Injected: {incident_id} at ({lat:.4f}, {lon:.4f})")
        
        # Simulate organic delay
        time.sleep(0.5)
        
if __name__ == "__main__":
    inject_mirror_data()
