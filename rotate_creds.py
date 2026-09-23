import secrets

pg_pass = secrets.token_hex(16)
kc_pass = secrets.token_hex(16)
gf_pass = secrets.token_hex(16)
redis_pass = secrets.token_hex(16)
nats_pass = secrets.token_hex(16)

env_content = f'''POSTGRES_USER=orion_admin_v2
POSTGRES_PASSWORD={pg_pass}
POSTGRES_DB=orion
DATABASE_URL=postgresql://orion_admin_v2:{pg_pass}@postgres:5432/orion

REDIS_PASSWORD={redis_pass}
NATS_USER=orion_worker
NATS_PASSWORD={nats_pass}

KEYCLOAK_ADMIN=admin
KEYCLOAK_ADMIN_PASSWORD={kc_pass}
KC_DB=postgres
KC_DB_URL=jdbc:postgresql://postgres:5432/orion
KC_DB_USERNAME=orion_admin_v2
KC_DB_PASSWORD={pg_pass}

GF_SECURITY_ADMIN_USER=admin
GF_SECURITY_ADMIN_PASSWORD={gf_pass}
GF_DATABASE_TYPE=postgres
GF_DATABASE_HOST=postgres:5432
GF_DATABASE_NAME=orion
GF_DATABASE_USER=orion_admin_v2
GF_DATABASE_PASSWORD={pg_pass}
'''

with open('.env', 'w') as f:
    f.write(env_content)
