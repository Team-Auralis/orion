import re

def update_reqs(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    content = content.replace('fastapi[all]==0.103.1', 'fastapi[all]>=0.109.2\nstarlette>=0.40.0')
    content = content.replace('python-jose[cryptography]==3.3.0', 'PyJWT>=2.8.0\ncryptography>=42.0.0')

    with open(filepath, 'w') as f:
        f.write(content)

update_reqs('apps/api/requirements.txt')
update_reqs('apps/worker/requirements.txt')
