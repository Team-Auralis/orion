import re

with open('scripts/security_probe.py', 'r') as f:
    content = f.read()

content = content.replace('import requests', 'import requests\nimport urllib3\nurllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)')
content = content.replace('requests.get(', 'requests.get(verify=False, ')
content = content.replace('requests.post(', 'requests.post(verify=False, ')
content = content.replace('requests.put(', 'requests.put(verify=False, ')
content = content.replace('requests.delete(', 'requests.delete(verify=False, ')

with open('scripts/security_probe.py', 'w') as f:
    f.write(content)
