import re

with open('docker-compose.yml', 'r', encoding='utf-8') as f:
    config = f.read()

patch = '''  orion-api:
    build:
      context: .
      dockerfile: Dockerfile.python
    container_name: orion-api
    command: uvicorn apps.api.main:app --host 0.0.0.0 --port 8001
    ports:
      - "8001:8001"'''

config = config.replace('''  orion-api:
    build:
      context: .
      dockerfile: Dockerfile.python
    container_name: orion-api
    command: uvicorn apps.api.main:app --host 0.0.0.0 --port 8001''', patch)

with open('docker-compose.yml', 'w', encoding='utf-8') as f:
    f.write(config)
