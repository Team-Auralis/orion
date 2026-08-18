import httpx
import uuid

API_URL = "http://localhost:8000/v1"

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
                print("✅ SOS successfully created and authorized.")
            else:
                print("❌ SOS creation failed.")
    except httpx.ConnectError:
        print("❌ Could not connect to API. Is it running?")

def test_negative_path():
    print("\n--- Testing Negative Path (Citizen -> Admin) ---")
    
    try:
        with httpx.Client() as client:
            resp = client.get(f"{API_URL}/admin")
            print(f"Response Code: {resp.status_code}")
            
            if resp.status_code == 403:
                print("✅ Policy Firewall successfully blocked access (403 Forbidden).")
            else:
                print(f"❌ Policy Firewall failed to block access. Code: {resp.status_code}")
                print(f"Response Body: {resp.json()}")
    except httpx.ConnectError:
        print("❌ Could not connect to API. Is it running?")

if __name__ == "__main__":
    test_sos_flow()
    test_negative_path()
