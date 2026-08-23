import time

print("=== ORION ADAPT-003: DYNAMIC CAPABILITY DISCOVERY ===")

class OPA_VEIL:
    def __init__(self):
        self.policy = {
            "comm.cloud": True,
            "comm.edge": True,
            "comm.satellite.new": True # Policy permits it, but registry didn't have it yet
        }
    def check(self, action):
        return self.policy.get(action, False)

class DynamicRegistry:
    def __init__(self):
        self.capabilities = {
            "comm.cloud": {"status": "OFFLINE", "cost": 10},
            "comm.edge": {"status": "OFFLINE", "cost": 20}
        }
    
    def register(self, name, meta):
        print(f"\n[REGISTRY] New capability dynamically registered: {name}")
        self.capabilities[name] = meta

class Planner:
    def __init__(self, registry):
        self.registry = registry
    
    def generate_plan(self, intent):
        print(f"\n[PLANNER] Intent received: {intent}")
        plans = [{"action": k, **v} for k, v in self.registry.capabilities.items() if "comm" in k]
        return sorted(plans, key=lambda x: x["cost"])

class ExecutionEngine:
    def __init__(self, opa):
        self.opa = opa
        
    def execute(self, plan, registry):
        print(f"[EXECUTION] Attempting: {plan['action']}")
        if not self.opa.check(plan['action']):
            print(f"   [VEIL] DENY: Unauthorized.")
            return False
        if registry.capabilities.get(plan['action'], {}).get("status") != "ONLINE":
            print(f"   [ENVIRONMENT] FAIL: OFFLINE.")
            return False
        print(f"   [EXECUTE] SUCCESS: {plan['action']} safely executed.")
        return True

registry = DynamicRegistry()
opa = OPA_VEIL()
planner = Planner(registry)
engine = ExecutionEngine(opa)

print("\n--- PHASE 1: INITIAL STATE (CLOUD/EDGE OFFLINE) ---")
plans = planner.generate_plan("Send broadcast")
success = False
for plan in plans:
    if engine.execute(plan, registry):
        success = True
        break

if not success:
    print("[SYSTEM] All known capabilities failed. Entering WAIT state...")

print("\n--- PHASE 2: DYNAMIC INJECTION ---")
time.sleep(0.5)
registry.register("comm.satellite.new", {"status": "ONLINE", "cost": 50})

print("\n--- PHASE 3: RE-PLANNING WITH NEW KNOWLEDGE ---")
plans = planner.generate_plan("Send broadcast")
success = False
for plan in plans:
    if engine.execute(plan, registry):
        success = True
        break

print("\n=== CONCLUSION ===")
print("Invariant maintained: The planner successfully discovered a newly injected capability at runtime, evaluated it, verified policy permission, and executed it without requiring code changes.")
