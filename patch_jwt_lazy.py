import re

with open('apps/api/main.py', 'r', encoding='utf-8') as f:
    config = f.read()

patch = '''    try:
        import json
        import base64
        
        # Ponytail: Let OPA do the crypto verification. We just parse the payload here.
        padded = token.split('.')[1] + '===='
        payload = json.loads(base64.urlsafe_b64decode(padded).decode('utf-8'))
        
        realm_roles = payload.get("realm_access", {}).get("roles", [])
        role = "operator" if "operator" in realm_roles else "citizen"
        
        return {
            "subject": payload.get("sub", "unknown"),
            "role": role,
            "username": payload.get("preferred_username", "unknown")
        }'''

config = re.sub(r'    try:\n        import jwt\n        # Bypassing local signature.*?        \}', patch, config, flags=re.DOTALL)

with open('apps/api/main.py', 'w', encoding='utf-8') as f:
    f.write(config)
