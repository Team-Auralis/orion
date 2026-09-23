import re

with open('scripts/security_probe.py', 'r') as f:
    content = f.read()

content = content.replace('except httpx.ConnectError:', 'except httpx.ConnectError as e:\n        print(e)')
content = content.replace('httpx.Client(', 'httpx.Client(verify=False, ')

with open('scripts/security_probe.py', 'w') as f:
    f.write(content)
