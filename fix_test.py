import re

with open('scripts/redteam_probe.py', 'r') as f:
    content = f.read()

content = content.replace('c = TestClient(m.app, raise_server_exceptions=False)', 'c = TestClient(m.app, raise_server_exceptions=True)')

with open('scripts/redteam_probe.py', 'w') as f:
    f.write(content)
