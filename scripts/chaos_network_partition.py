import time
import httpx
import uuid
from datetime import datetime, timezone

def run_chaos_experiment():
    print("===============================================================")
    print("  PHOENIX CRDT / HAVEN EDGE - NETWORK CHAOS EXPERIMENT")
    print("===============================================================")
    
    # 1. Auth setup
    print("\n[1] Authenticating Operator & Edge Citizen...")
    token_resp = httpx.post(
        "http://localhost:8080/realms/orion/protocol/openid-connect/token",
        data={'client_id': 'orion-api', 'grant_type': 'password', 'username': 'operator1', 'password': 'operatorpass'}
    )
    operator_token = token_resp.json()['access_token']
    
    # 2. Setup Incident ID
    print("\n[2] Creating target incident...")
    inc_payload = {
        "type": "SOS",
        "location": {"latitude": 34.1, "longitude": -118.1},
        "message": "Chaos Test Incident",
        "source": "mobile"
    }
    resp = httpx.post("http://localhost:8001/v1/incidents", json=inc_payload, headers={"Authorization": f"Bearer {operator_token}"})
    incident_id = resp.json()["incident_id"]
    print(f"    Target Incident ID: {incident_id}")
    time.sleep(1)
    
    # 3. Simulate Edge Disconnection
    print("\n[3] INJECTING CHAOS: Severing Network to Edge Node...")
    print("    (Simulating loss of NATS connectivity from the mobile gateway)")
    time.sleep(2)
    
    # 4. Generate Stale Offline Event
    print("\n[4] Edge Node Operator acts OFFLINE (Local timestamp generated)")
    stale_timestamp = datetime.now(timezone.utc).isoformat()
    print(f"    Offline Status Update: 'TRIAGED' at {stale_timestamp}")
    time.sleep(2)
    
    # 5. Cloud Command Center acts ONLINE
    print("\n[5] Cloud Command Center acts ONLINE (Later timestamp generated)")
    fresh_timestamp = datetime.now(timezone.utc).isoformat()
    print(f"    Online Status Update: 'EVACUATING' at {fresh_timestamp}")
    
    print("\n[6] Cloud synchronizes to Database...")
    resp = httpx.patch(
        f"http://localhost:8001/v1/incidents/{incident_id}/status",
        json={"status": "evacuating", "timestamp": fresh_timestamp},
        headers={"Authorization": f"Bearer {operator_token}"}
    )
    print(f"    Cloud Update Response: HTTP {resp.status_code}")
    time.sleep(1) # wait for worker to merge
    
    # 6. Network Restored
    print("\n[7] CHAOS RESOLVED: Network Restored. Edge Node synchronizes payload...")
    resp = httpx.patch(
        f"http://localhost:8001/v1/incidents/{incident_id}/status",
        json={"status": "triaged", "timestamp": stale_timestamp},
        headers={"Authorization": f"Bearer {operator_token}"}
    )
    print(f"    Edge Sync Response: HTTP {resp.status_code}")
    time.sleep(1) # wait for worker to merge
    
    # 7. Final State Verification
    print("\n[8] VERIFYING CRDT STATE RESOLUTION...")
    resp = httpx.get("http://localhost:8001/v1/incidents", headers={"Authorization": f"Bearer {operator_token}"})
    incidents = resp.json()
    incident = next((i for i in incidents if i["incident_id"] == incident_id), None)
    
    if incident:
        print(f"    Final Database Status: {incident['status']}")
        if incident['status'] == "EVACUATING":
            print("\n[PASS] EXPERIMENT SUCCESS: CRDT successfully discarded the stale edge event and preserved the mathematically newer state.")
        else:
            print("\n[FAIL] EXPERIMENT FAILED: CRDT incorrectly allowed a stale edge event to overwrite newer state.")
    else:
        print("\n[FAIL] EXPERIMENT FAILED: Incident not found in Database.")

if __name__ == "__main__":
    run_chaos_experiment()
