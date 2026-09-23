import re

with open('apps/api/main.py', 'r', encoding='utf-8') as f:
    config = f.read()

patch = '''        if not rsa_key:
            raise HTTPException(status_code=403, detail="Invalid Key")
            
        import json
        from jwt.algorithms import RSAAlgorithm
        public_key = RSAAlgorithm.from_jwk(json.dumps(rsa_key))
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],'''

config = config.replace('''        if not rsa_key:
            raise HTTPException(status_code=403, detail="Invalid Key")
            
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],''', patch)

with open('apps/api/main.py', 'w', encoding='utf-8') as f:
    f.write(config)
