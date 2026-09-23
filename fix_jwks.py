import re

with open('apps/api/main.py', 'r', encoding='utf-8') as f:
    config = f.read()

# I will replace the whole verify_token try/except block
patch = '''    try:
        import jwt
        JWKS_URL = os.environ.get("KEYCLOAK_JWKS_URL", "http://localhost:8080/realms/orion/protocol/openid-connect/certs")
        jwks_client = jwt.PyJWKClient(JWKS_URL)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=os.environ.get("JWT_AUDIENCE", "account"),
            issuer=os.environ.get("JWT_ISSUER", "http://localhost:8080/realms/orion")
        )
        
        # Extract realm roles
        realm_roles = payload.get("realm_access", {}).get("roles", [])
        role = "operator" if "operator" in realm_roles else "citizen"
        
        return {
            "subject": payload.get("sub", "unknown"),
            "role": role,
            "username": payload.get("preferred_username", "unknown")
        }'''

config = re.sub(r'    try:\n        jwks = get_jwks\(\).*?        return \{\n            "subject": payload\.get\("sub", "unknown"\),\n            "role": role,\n            "username": payload\.get\("preferred_username", "unknown"\)\n        \}', patch, config, flags=re.DOTALL)

with open('apps/api/main.py', 'w', encoding='utf-8') as f:
    f.write(config)
