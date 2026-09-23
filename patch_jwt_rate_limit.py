import re

with open('apps/api/main.py', 'r', encoding='utf-8') as f:
    config = f.read()

patch = '''            import base64, json
            padded = auth.split(" ", 1)[1].split('.')[1] + '===='
            claims = json.loads(base64.urlsafe_b64decode(padded).decode('utf-8'))'''

config = config.replace('''            import jwt
            claims = jwt.decode(auth.split(" ", 1)[1], options={"verify_signature": False})''', patch)

with open('apps/api/main.py', 'w', encoding='utf-8') as f:
    f.write(config)
