import time
import json
import re

print("==================================================")
print("     A U R A  |  ORION Conversational Interface   ")
print("==================================================\n")

# --- MOCK CAPABILITY REGISTRY ---
REGISTRY = {
    "comm.cloud": {"status": "OFFLINE", "cost": 1, "requires_hitl": False},
    "comm.edge": {"status": "OFFLINE", "cost": 2, "requires_hitl": False},
    "comm.satellite": {"status": "ONLINE", "cost": 10, "requires_hitl": True},
}

# --- MOCK OPA (VEIL) ---
def check_opa_policy(user, action, hitl_approved=False):
    policy = {
        "comm.cloud": True,
        "comm.edge": True,
        "comm.satellite": hitl_approved # Denied unless HITL approved
    }
    return policy.get(action, False)

# --- AURA INTENT PARSER (Mock LLM) ---
def parse_intent(text):
    print("? [AURA STATE: PARSING INTENT...]")
    time.sleep(0.5)
    intent = {"goal": "UNKNOWN", "priority": "NORMAL", "raw": text}
    
    if "comm" in text.lower() or "broadcast" in text.lower():
        intent["goal"] = "Maintain Communication"
    if "critical" in text.lower() or "emergency" in text.lower():
        intent["priority"] = "CRITICAL"
        
    return intent

# --- ADAPTIVE PLANNER ---
def generate_plans(intent):
    print("?? [AURA STATE: ANALYZING CAPABILITIES...]")
    time.sleep(0.5)
    plans = [{"action": k, **v} for k, v in REGISTRY.items() if "comm" in k]
    return sorted(plans, key=lambda x: x["cost"])

def execute_with_aura(intent):
    plans = generate_plans(intent)
    
    for plan in plans:
        print(f"\n?? [AURA STATE: ATTEMPTING '{plan['action']}']")
        time.sleep(0.5)
        
        # 1. Environment Check
        if plan['status'] != "ONLINE":
            print(f"? [ENVIRONMENT] Capability '{plan['action']}' is OFFLINE. Replanning...")
            continue
            
        # 2. VEIL Check & HITL
        hitl_approved = False
        if plan['requires_hitl']:
            print(f"?? [VEIL] ACTION RESTRICTED: '{plan['action']}' requires human authorization.")
            auth = input(f"   AURA: Do you authorize the use of {plan['action']}? (Y/N): ").strip().upper()
            if auth == 'Y':
                hitl_approved = True
                print("   [AURA] Authorization captured and signed.")
            else:
                print("   [AURA] Authorization denied by operator. Replanning...")
                continue
                
        if not check_opa_policy("operator_1", plan['action'], hitl_approved):
             print(f"? [VEIL] FATAL DENY: Unauthorized to use {plan['action']}.")
             continue
             
        print(f"? [AURA STATE: EXECUTING -> SAFE]")
        print(f"   Target '{plan['action']}' executed successfully.")
        return True
        
    print("\n?? [AURA STATE: FAIL-SAFE]")
    print("   AURA: I have exhausted all safe, available capabilities. Manual intervention required.")
    return False

# --- MAIN CHAT LOOP ---
def main():
    print("AURA: Online. I am monitoring ORION infrastructure. How can I assist you?")
    while True:
         try:
             user_input = input("\nOperator> ")
             if user_input.lower() in ['exit', 'quit']:
                 break
             if not user_input.strip():
                 continue
                 
             intent = parse_intent(user_input)
             print(f"   [Parsed Intent JSON] -> {json.dumps(intent)}")
             
             execute_with_aura(intent)
             
         except KeyboardInterrupt:
             break

if __name__ == "__main__":
    # Hardcode a quick execution for the AI test runner so it doesn't block waiting for input
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        print("Operator> We have a critical emergency, maintain comms.")
        intent = parse_intent("We have a critical emergency, maintain comms.")
        print(f"   [Parsed Intent JSON] -> {json.dumps(intent)}")
        
        # Mocking the HITL input for the test
        original_input = __builtins__.input
        __builtins__.input = lambda _: "Y"
        execute_with_aura(intent)
        __builtins__.input = original_input
    else:
        main()
