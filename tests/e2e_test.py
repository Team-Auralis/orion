import httpx
import uuid

API_URL = "http://localhost:8001/v1"

def test_sos_flow():
    print("--- Testing Authorized SOS Flow ---")
    
    # We use a mocked user in the API for now, but this is the structure
    headers = {
        "Idempotency-Key": f"test-idem-{uuid.uuid4().hex[:6]}"
    }
    
    payload = {
        "type": "SOS",
        "location": {
            "latitude": 17.6868,
            "longitude": 83.2185
        },
        "message": "Test emergency from Python script",
        "source": "mobile-test"
    }
    
    try:
        with httpx.Client() as client:
            resp = client.post(f"{API_URL}/incidents", json=payload, headers=headers)
            print(f"Response Code: {resp.status_code}")
            print(f"Response Body: {resp.json()}")
            
            if resp.status_code == 200:
                if resp.json().get("status") == "ACCEPTED_DEGRADED_MODE":
                    print("[SUCCESS] SOS accepted in DEGRADED MODE (Database Offline).")
                else:
                    print("[SUCCESS] SOS successfully created and authorized.")
            else:
                print("[FAILED] SOS creation failed.")
    except httpx.ConnectError:
        print("[FAILED] Could not connect to API. Is it running?")

def test_negative_path():
    print("\n--- Testing Negative Path (Citizen -> Admin) ---")
    
    try:
        with httpx.Client() as client:
            resp = client.get(f"{API_URL}/admin")
            print(f"Response Code: {resp.status_code}")
            
            if resp.status_code == 403:
                print("[SUCCESS] Policy Firewall successfully blocked access (403 Forbidden).")
            else:
                print(f"[FAILED] Policy Firewall failed to block access. Code: {resp.status_code}")
                print(f"Response Body: {resp.json()}")
    except httpx.ConnectError:
        print("[FAILED] Could not connect to API. Is it running?")

if __name__ == "__main__":
    test_sos_flow()
    test_negative_path()
