import re

with open('infra/keycloak/realm-export.json', 'r', encoding='utf-8') as f:
    config = f.read()

config = config.replace('"publicClient": false,', '"publicClient": true,')
config = config.replace('"directAccessGrantsEnabled": false,', '"directAccessGrantsEnabled": true,')

with open('infra/keycloak/realm-export.json', 'w', encoding='utf-8') as f:
    f.write(config)
