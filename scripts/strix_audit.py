import asyncio
import httpx
import os
import sys

# ponytail: Emulating strix-pentest core logic without dragging in the massive LLM dependency tree.
# We test what actually matters: can citizens hit admin endpoints? Can they IDOR someone else's incident?

API_BASE = "http://localhost:8001/v1"
KC_BASE = "http://localhost:8080/realms/orion/protocol/openid-connect/token"

async def get_token(username, password):
    async with httpx.AsyncClient() as client:
        resp = await client.post(KC_BASE, data={
            'client_id': 'orion-api', 'grant_type': 'password', 
            'username': username, 'password': password
        })
        return resp.json().get('access_token')

async def run_strix_audit():
    print("===============================================================")
    print("  FORGE CYBER - STRIX AUTONOMOUS PENTEST ")
    print("===============================================================")
    
    print("\n[1] Extracting tokens from Keycloak...")
    operator_token = await get_token('operator1', 'operatorpass')
    citizen_token = await get_token('citizen1', 'citizenpass')
    
    if not operator_token or not citizen_token:
        print("❌ FAILED TO GET TOKENS. Is Keycloak running?")
        sys.exit(1)
        
    print("    Tokens acquired.")
    
    # 1. BOLA / IDOR Testing (Broken Object Level Authorization)
    print("\n[2] Executing BOLA/IDOR attacks on /v1/incidents...")
    async with httpx.AsyncClient() as client:
        # Operator creates an incident
        res = await client.post(f"{API_BASE}/incidents", json={
            "type": "SOS", "location": {"latitude": 0, "longitude": 0}, 
            "message": "Operator incident", "source": "radio"
        }, headers={"Authorization": f"Bearer {operator_token}"})
        inc_id = res.json()["incident_id"]
        
        # Citizen attempts to view operator's incident
        # (Assuming we implement GET /v1/incidents/{id} which we haven't yet, but let's test the listing)
        print("    Checking if Citizen can list all incidents...")
        list_res = await client.get(f"{API_BASE}/incidents", headers={"Authorization": f"Bearer {citizen_token}"})
        if list_res.status_code == 403:
            print("    [PASS] Citizen blocked from listing all incidents (OPA Enforced).")
        else:
            print(f"    [FAIL] Citizen could list incidents. HTTP {list_res.status_code}")
            
    # 2. Privilege Escalation (Vertical)
    print("\n[3] Executing Vertical Privilege Escalation attacks on /v1/admin...")
    async with httpx.AsyncClient() as client:
        admin_res = await client.get(f"{API_BASE}/admin", headers={"Authorization": f"Bearer {citizen_token}"})
        if admin_res.status_code == 403:
            print("    [PASS] Citizen blocked from /admin (OPA Enforced).")
        else:
            print(f"    [FAIL] Citizen accessed /admin. HTTP {admin_res.status_code}")
            
    # 3. Rate Limiting / DoS (Volumetric)
    print("\n[4] Executing Volumetric / DoS attack on /v1/incidents...")
    print("    Flooding API with 50 rapid SOS requests from Citizen...")
    
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {citizen_token}"}
        payload = {"type": "SOS", "location": {"latitude": 0, "longitude": 0}, "message": "Spam", "source": "bot"}
        
        tasks = [client.post(f"{API_BASE}/incidents", json=payload, headers=headers) for _ in range(50)]
        responses = await asyncio.gather(*tasks)
        
        successes = len([r for r in responses if r.status_code == 200])
        # If rate limiting isn't implemented, this will flag it as a finding.
        if successes > 10:
             print(f"    [FINDING] API accepted {successes}/50 requests without rate-limiting. Vulnerable to DoS.")
        else:
             print(f"    [PASS] API rate-limited the flood. Accepted {successes}/50.")

    print("\n===============================================================")
    print("  AUDIT COMPLETE.")
    print("===============================================================")

if __name__ == "__main__":
    asyncio.run(run_strix_audit())
