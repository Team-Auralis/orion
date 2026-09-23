import re

with open('apps/api/main.py', 'r') as f:
    content = f.read()

content = content.replace('''        payload = jwt.decode(
            token,
            # JWKS_CACHE is usually a dict, but PyJWT decode needs the key string or PyJWK
            # In an E2E mocked test, this is bypassed anyway
            options={"verify_signature": False},
            algorithms=["RS256"],
            audience=os.environ.get("JWT_AUDIENCE", "account"),
            issuer=os.environ.get("JWT_ISSUER", "http://localhost:8080/realms/orion")
        )''',
'''        jwks_client = jwt.PyJWKClient(JWKS_URL)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=os.environ.get("JWT_AUDIENCE", "account"),
            issuer=os.environ.get("JWT_ISSUER", "http://localhost:8080/realms/orion")
        )''')

with open('apps/api/main.py', 'w') as f:
    f.write(content)
