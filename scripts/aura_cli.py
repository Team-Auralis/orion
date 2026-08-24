import time
import json
import random
import re

print("==================================================")
print("     A U R A  |  ORION Conversational Interface   ")
print("==================================================\n")

# --- MOCK REGISTRY ---
REGISTRY = {
    "comm.cloud": {"status": "OFFLINE", "cost": 1, "requires_hitl": False},
    "comm.edge": {"status": "OFFLINE", "cost": 2, "requires_hitl": False},
    "comm.satellite": {"status": "ONLINE", "cost": 10, "requires_hitl": True},
    "surveillance.drone": {"status": "ONLINE", "cost": 5, "requires_hitl": True},
}

def check_opa_policy(user, action, hitl_approved=False):
    policy = {
        "comm.cloud": True,
        "comm.edge": True,
        "comm.satellite": hitl_approved,
        "surveillance.drone": hitl_approved
    }
    return policy.get(action, False)

# --- CONVERSATIONAL MEMORY & NLP ENGINE ---
class AuraNLP:
    def __init__(self):
        self.memory = {"last_topic": None, "last_intent": None}
        
        self.greetings = [
            "Hey! AURA here. All systems are being monitored. What's on your mind?",
            "Hello! I'm online and ready. Need me to check the infrastructure or deploy something?",
            "Hi there. Things are a bit chaotic in the mesh today (Cloud is down), but I'm ready to help. What do you need?",
            "Hey Operator, AURA standing by. How can I assist you today?"
        ]
        
        self.acknowledgements = [
            "Got it. Let me look into that.",
            "Understood. Parsing your request now...",
            "Sure thing. Give me a second to figure out the best approach.",
            "I hear you. Let me check the capability registry."
        ]
        
    def generate_human_response(self, text):
        text_lower = text.lower()
        
        # 1. Greetings
        if re.search(r'\b(hello|hi|hey|sup|morning|afternoon)\b', text_lower):
            return {"type": "chat", "response": random.choice(self.greetings)}
            
        # 2. Identity / Capabilities
        if "who are you" in text_lower or "what can you do" in text_lower:
            return {"type": "chat", "response": "I'm AURA! I'm essentially the conversational brain for Project ORION. You can chat with me naturally, and if you need something done - like deploying drones or fixing communications - I'll translate that into code and execute it safely through VEIL."}
            
        # 3. Status
        if any(word in text_lower for word in ["status", "health", "how are things", "what's up with the system"]):
            self.memory["last_topic"] = "infrastructure"
            return {"type": "chat", "response": "Honestly, the primary mesh is struggling a bit. Both the Cloud and Edge communication nodes are currently OFFLINE. However, our Satellite links and Drone fleets are fully operational. Need me to route something through them?"}
            
        # 4. Gratitude / Chit-Chat
        if re.search(r'\b(thanks|thank you|awesome|good job|nice)\b', text_lower):
            return {"type": "chat", "response": random.choice(["You're very welcome!", "Happy to help!", "Anytime. That's what I'm here for.", "No problem at all."])}
            
        if "how are you" in text_lower:
            return {"type": "chat", "response": "I'm doing great, thanks for asking! Just hanging out in the matrix, keeping an eye on the ORION cluster. How are you holding up?"}
            
        # 5. Intent Extraction (Context-Aware)
        intent = {"type": "intent", "goal": "UNKNOWN", "priority": "NORMAL", "raw": text, "target_capability": "unknown"}
        
        # Handle contextual "fix it"
        if "fix it" in text_lower or "do it" in text_lower:
            if self.memory["last_topic"] == "infrastructure":
                 intent["goal"] = "Maintain Communication"
                 intent["target_capability"] = "comm"
                 
        if any(word in text_lower for word in ["comm", "broadcast", "message", "network", "connect", "internet", "route"]):
            intent["goal"] = "Maintain Communication"
            intent["target_capability"] = "comm"
            self.memory["last_topic"] = "comm"
            
        elif any(word in text_lower for word in ["drone", "scout", "survey", "look", "camera", "fly"]):
            intent["goal"] = "Deploy Surveillance"
            intent["target_capability"] = "surveillance"
            self.memory["last_topic"] = "surveillance"
            
        if any(word in text_lower for word in ["critical", "emergency", "urgent", "now", "fast", "hurry"]):
            intent["priority"] = "CRITICAL"
            
        if intent["goal"] != "UNKNOWN":
            print(f"? AURA: {random.choice(self.acknowledgements)}")
            time.sleep(0.6)
            return intent
            
        # Fallback
        return {"type": "chat", "response": "I'm not entirely sure what you mean by that. We can just chat, or you can ask me to do something specific like 'deploy a surveillance drone' or 'check the system status'."}

nlp = AuraNLP()

def generate_plans(intent):
    print("?? [AURA INTERNAL: Analyzing capability graph...]")
    time.sleep(0.8)
    target = intent.get("target_capability", "unknown")
    plans = [{"action": k, **v} for k, v in REGISTRY.items() if target in k]
    return sorted(plans, key=lambda x: x["cost"])

def execute_with_aura(intent):
    plans = generate_plans(intent)
    
    if not plans:
        print(f"? AURA: Hmm, I couldn't find any tools in my registry to handle that specific request.")
        return False
        
    for plan in plans:
        time.sleep(0.5)
        
        if plan['status'] != "ONLINE":
            print(f"?? AURA: I tried to use '{plan['action']}', but it looks like it's offline. Let me try a fallback...")
            continue
            
        hitl_approved = False
        if plan['requires_hitl']:
            print(f"\n?? AURA: Hold up. The only available path is '{plan['action']}', which requires strict human authorization under VEIL policies.")
            auth = input(f"   Do you authorize me to proceed with {plan['action']}? (Y/N): ").strip().upper()
            if auth == 'Y':
                hitl_approved = True
                print("   [Cryptographic Signature Captured]")
                print("? AURA: Great, authorization confirmed. Executing now...")
            else:
                print("? AURA: No worries, I've aborted that action. Let me see if there's another way...")
                continue
                
        if not check_opa_policy("operator_1", plan['action'], hitl_approved):
             print(f"? AURA: VEIL rejected my execution attempt for {plan['action']}. We don't have the privileges for that.")
             continue
             
        time.sleep(0.5)
        print(f"? AURA: All done! Target '{plan['action']}' was executed successfully and the operation is SAFE.")
        return True
        
    print("\n?? AURA: I'm really sorry, but I've exhausted all safe and available options. I can't complete this request autonomously.")
    return False

def main():
    print("AURA: Online. Type 'quit' to exit.")
    while True:
         try:
             user_input = input("\nYou: ")
             if user_input.lower() in ['exit', 'quit']:
                 print("AURA: Catch you later! Shutting down.")
                 break
             if not user_input.strip():
                 continue
                 
             parsed = nlp.generate_human_response(user_input)
             
             if parsed["type"] == "chat":
                 print(f"AURA: {parsed['response']}")
             else:
                 execute_with_aura(parsed)
             
         except KeyboardInterrupt:
             print("\nAURA: Shutting down.")
             break

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        test_inputs = [
            "Hey there!",
            "How are you doing today?",
            "What's up with the system status?",
            "Oh wow, fix the comms immediately please",
            "Thanks AURA!"
        ]
        
        original_input = __builtins__.input
        __builtins__.input = lambda _: "Y"
        
        for msg in test_inputs:
            print(f"\nYou: {msg}")
            parsed = nlp.generate_human_response(msg)
            if parsed["type"] == "chat":
                print(f"AURA: {parsed['response']}")
            else:
                execute_with_aura(parsed)
                
        __builtins__.input = original_input
    else:
        main()
