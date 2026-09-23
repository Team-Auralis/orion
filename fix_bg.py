import re

with open('apps/api/main.py', 'r') as f:
    content = f.read()

content = content.replace('token=override_token,', 'token=hashlib.sha256(override_token.encode()).hexdigest(),')
content = content.replace('BreakGlassSession.token == override_token,', 'BreakGlassSession.token == hashlib.sha256(override_token.encode()).hexdigest(),')
if 'import hashlib' not in content:
    content = 'import hashlib\n' + content

with open('apps/api/main.py', 'w') as f:
    f.write(content)
