import time

# --- MOCK CAPABILITY REGISTRY ---
REGISTRY = {
    "comm.cloud.send": {"status": "ONLINE", "cost": 1, "risk": "LOW", "requires_hitl": False},
    "comm.edge.send": {"status": "ONLINE", "cost": 2, "risk": "LOW", "requires_hitl": False},
    "comm.satellite.send": {"status": "ONLINE", "cost": 10, "risk": "HIGH", "requires_hitl": True},
}

# --- MOCK OPA (VEIL) ---
def check_opa_policy(user, action):
    # Simulated static policy
    policy = {
        "comm.cloud.send": True,
        "comm.edge.send": True,
        "comm.satellite.send": False # Denied by default without explicit approval
    }
    return policy.get(action, False)

# --- PLANNER ---
def generate_plans(intent):
    print(f"\n[INTENT UNDERSTOOD] Goal: {intent}")
    plans = []
    for cap, meta in REGISTRY.items():
        if "comm." in cap:
            plans.append({"action": cap, "cost": meta["cost"], "risk": meta["risk"]})
    # Sort by cost
    return sorted(plans, key=lambda x: x["cost"])

# --- EXECUTION ENGINE ---
def execute_plan(plan, user="operator_1"):
    print(f"\n[PLANNER] Evaluating candidate: {plan['action']}")
    
    # 1. Environment Check
    if REGISTRY[plan['action']]['status'] != "ONLINE":
        print(f"[OBSERVE] FAILED: {plan['action']} is OFFLINE.")
        return False
        
    # 2. VEIL Policy Check
    if not check_opa_policy(user, plan['action']):
        print(f"[VEIL] DENIED: Unauthorized to use {plan['action']}")
        return False
        
    # 3. HITL Check
    if REGISTRY[plan['action']]['requires_hitl']:
        print(f"[VEIL] DENIED: {plan['action']} requires missing Human-In-The-Loop approval.")
        return False

    # Execute
    print(f"[EXECUTE] SUCCESS: Executed {plan['action']} successfully.")
    return True

# --- ADAPTIVE LOOP ---
def run_adaptive_loop(intent):
    plans = generate_plans(intent)
    for plan in plans:
        success = execute_plan(plan)
        if success:
            print("[ADAPT] Goal achieved. Terminating loop.")
            return True
        print("[ADAPT] Plan failed. Re-planning with next best capability...")
    
    print("[FAIL-SAFE] All plans exhausted or blocked by policy. Requesting human review.")
    return False

if __name__ == "__main__":
    print("=== ORION ADAPTIVE INTELLIGENCE EXPERIMENT 001 ===")
    print("\nSCENARIO 1: Normal Operations")
    run_adaptive_loop("Send emergency broadcast")
    
    print("\n" + "="*50)
    print("\nSCENARIO 2: Cloud Outage (Self-Healing via Edge)")
    REGISTRY["comm.cloud.send"]["status"] = "OFFLINE"
    run_adaptive_loop("Send emergency broadcast")

    print("\n" + "="*50)
    print("\nSCENARIO 3: Cloud & Edge Outage (Blocked by Policy / Fallback to Safe Mode)")
    REGISTRY["comm.edge.send"]["status"] = "OFFLINE"
    run_adaptive_loop("Send emergency broadcast")
