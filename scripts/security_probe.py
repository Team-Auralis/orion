import sys
import httpx
import argparse

def print_result(check: str, passed: bool, details: str = ""):
    icon = "[+]" if passed else "[-]"
    print(f"{icon} {check}")
    if details:
        print(f"    -> {details}")
    if not passed:
        sys.exit(1)

def run_probes(base_url: str):
    print(f"=== ORION SECURITY PROBE (Target: {base_url}) ===\n")
    
    with httpx.Client(verify=False, base_url=base_url) as client:
        # 1. Authentication Boundary
        resp = client.post("/v1/dispatch/recommendations/rec-123/action", json={"action": "APPROVE"})
        print_result(
            "Authentication Boundary (Missing JWT)", 
            resp.status_code == 401 or resp.status_code == 403,
            f"Expected 401/403, got {resp.status_code}"
        )
        
        # 2. Malformed Input
        resp = client.post("/v1/incidents", json={"type": "SOS", "location": "not-an-object"})
        print_result(
            "Malformed Input Handling (Invalid Schema)",
            resp.status_code == 422,
            f"Expected 422 Unprocessable Entity, got {resp.status_code}"
        )
        
        # 3. Method Not Allowed
        resp = client.patch("/v1/incidents")
        print_result(
            "Method Not Allowed (PATCH on POST endpoint)",
            resp.status_code == 405,
            f"Expected 405, got {resp.status_code}"
        )
        
        # 4. Pilot Suspend Unauthenticated
        resp = client.post("/v1/pilot/suspend", json={"reason": "Security Probe"})
        print_result(
            "Kill Switch Protection (Unauthenticated)",
            resp.status_code == 401 or resp.status_code == 403,
            f"Expected 401/403, got {resp.status_code}"
        )
        
        # 5. Geofence Active Check (If pilot mode is on)
        resp = client.get("/v1/pilot/status")
        if resp.status_code == 200:
            status = resp.json()
            if status.get("pilot_mode"):
                print_result(
                    "Pilot Config Valid",
                    status.get("config_error") is None,
                    f"Config Error: {status.get('config_error')}"
                )
        
    print("\n[+] All non-destructive security probes passed.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="ORION Baseline Security Probe")
    parser.add_argument("--url", default="http://localhost:8001", help="Base URL of the ORION API")
    args = parser.parse_args()
    
    try:
        run_probes(args.url)
    except httpx.ConnectError as e:
        print(e)
        print(f"[-] Could not connect to target {args.url}")
        sys.exit(1)
