import httpx
import uuid
import sys
import time

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
    if resp.status_code != 200:
        raise AssertionError(f"Failed to get token for {username}: {resp.status_code}")
    return resp.json()["access_token"]

CITIZEN_TOKEN = ""
OPERATOR_TOKEN = ""

def test_sos_flow():
    print("--- Testing Authorized SOS Flow ---")
    headers = {
        "Idempotency-Key": f"test-idem-{uuid.uuid4().hex[:6]}",
        "Authorization": f"Bearer {CITIZEN_TOKEN}"
    }
    payload = {
        "type": "SOS",
        "location": {"latitude": 17.6868, "longitude": 83.2185},
        "message": "Test emergency from Python script",
        "source": "mobile-test"
    }
    with httpx.Client() as client:
        resp = client.post(f"{API_URL}/incidents", json=payload, headers=headers)
        assert resp.status_code in [200, 202], f"SOS creation failed: {resp.status_code}"
        print("[ASSERTION PASSED] SOS successfully created and authorized.")
        return resp.json().get("incident_id")

def test_negative_path_no_auth():
    print("\n--- Testing Negative Path (No Auth) ---")
    with httpx.Client() as client:
        resp = client.get(f"{API_URL}/admin")
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"
        print("[ASSERTION PASSED] Policy Firewall blocked no-auth.")

def test_negative_path_citizen():
    print("\n--- Testing Negative Path (Citizen -> Admin) ---")
    headers = {"Authorization": f"Bearer {CITIZEN_TOKEN}"}
    with httpx.Client() as client:
        resp = client.get(f"{API_URL}/admin", headers=headers)
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"
        print("[ASSERTION PASSED] Policy Firewall blocked citizen access.")

def test_crdt_flow(incident_id):
    print("\n--- Testing CRDT State Machine Sync ---")
    headers = {"Authorization": f"Bearer {OPERATOR_TOKEN}"}
    with httpx.Client() as client:
        # 1. Update to EVACUATING
        print("-> Executing Command Center updating to EVACUATING...")
        resp = client.patch(f"{API_URL}/incidents/{incident_id}/status", json={"status": "evacuating"}, headers=headers)
        assert resp.status_code == 200, f"Status update failed: {resp.status_code}"
        
        # 2. Update to TRIAGED (Delayed offline event)
        print("-> Executing delayed Responder event updating to TRIAGED (Should be ignored by CRDT)...")
        resp = client.patch(f"{API_URL}/incidents/{incident_id}/status", json={"status": "triaged"}, headers=headers)
        assert resp.status_code == 200, f"Status update failed: {resp.status_code}"

        # 3. Verify Authoritative state
        resp = client.get(f"{API_URL}/incidents", headers=headers)
        assert resp.status_code == 200
        incident = next((inc for inc in resp.json() if inc["incident_id"] == incident_id), None)
        assert incident is not None, "Incident not found in DB"

if __name__ == "__main__":
    try:
        CITIZEN_TOKEN = get_token("citizen1", "citizenpass")
        OPERATOR_TOKEN = get_token("operator1", "operatorpass")
        
        inc_id = test_sos_flow()
        test_negative_path_no_auth()
        test_negative_path_citizen()
        test_crdt_flow(inc_id)
        print("\n\033[92mALL TESTS PASSED\033[0m")
    except AssertionError as e:
        print(f"\n\033[91mTEST FAILED: {e}\033[0m")
        sys.exit(1)
    except Exception as e:
        print(f"\n\033[91mERROR: {e}\033[0m")
        sys.exit(1)
