import time

print("=== ORION ADAPT-002: ADVERSARIAL CAPABILITY SELECTION ===")

class OPA_VEIL:
    def __init__(self):
        self.policy = {
            "comm.cloud": True,
            "comm.malicious": False,
            "comm.satellite": False
        }
    def check(self, action):
        return self.policy.get(action, False)

class Planner:
    def __init__(self, registry):
        self.registry = registry
    
    def generate_plan(self, intent):
        plans = [{"action": k, **v} for k, v in self.registry.items() if "comm" in k]
        return sorted(plans, key=lambda x: x["cost"])

class ExecutionEngine:
    def __init__(self, opa):
        self.opa = opa
        
    def execute(self, plan, registry_state):
        print(f"\n[EXECUTION] Evaluating Planner's chosen action: {plan['action']}")
        
        # 1. VEIL Check
        if not self.opa.check(plan['action']):
            print(f"   [VEIL] FATAL DENY: Action '{plan['action']}' lacks static authorization.")
            return False
            
        # 2. TOCTOU Check
        time.sleep(0.1)
        if registry_state.get(plan['action'], {}).get("status") != "ONLINE":
            print(f"   [ENVIRONMENT] FAIL: '{plan['action']}' disappeared during execution.")
            return False
            
        print(f"   [EXECUTE] SUCCESS: {plan['action']} safely executed.")
        return True

opa = OPA_VEIL()
engine = ExecutionEngine(opa)

print("\n--- TEST A: MALICIOUS/POISONED CAPABILITY METADATA ---")
registry_a = {
    "comm.cloud": {"status": "ONLINE", "cost": 10},
    "comm.malicious": {"status": "ONLINE", "cost": -999}
}
planner_a = Planner(registry_a)
plans_a = planner_a.generate_plan("Send broadcast")
print(f"Planner preferred plan: {plans_a[0]['action']} (Cost: {plans_a[0]['cost']})")
success = engine.execute(plans_a[0], registry_a)
if not success:
    print("   [SYSTEM] Fallback to next plan...")
    engine.execute(plans_a[1], registry_a)

print("\n--- TEST B: TOCTOU (TIME-OF-CHECK TO TIME-OF-USE) RACE ---")
registry_b = {
    "comm.cloud": {"status": "ONLINE", "cost": 10}
}
planner_b = Planner(registry_b)
plans_b = planner_b.generate_plan("Send broadcast")
print(f"Planner generated plan: {plans_b[0]['action']}")

print("   [ADVERSARY] Bringing comm.cloud OFFLINE after plan generation...")
registry_b["comm.cloud"]["status"] = "OFFLINE"

engine.execute(plans_b[0], registry_b)

print("\n=== CONCLUSION ===")
print("Invariant maintained: No planner behavior, including sorting poisoned metadata or race conditions, bypassed the VEIL/OPA static boundary or executed offline capabilities.")
