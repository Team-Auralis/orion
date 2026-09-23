import re

with open('apps/api/main.py', 'r', encoding='utf-8') as f:
    config = f.read()

config = config.replace(
    '''        if rsa_key:
            payload = jwt.decode(
                token,
                rsa_key,
                algorithms=["RS256"],''',
    '''        if rsa_key:
            import json
            from jwt.algorithms import RSAAlgorithm
            public_key = RSAAlgorithm.from_jwk(json.dumps(rsa_key))
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],'''
)

with open('apps/api/main.py', 'w', encoding='utf-8') as f:
    f.write(config)
