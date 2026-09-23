import httpx
import os
import json

operator_pw = '0ZZAPJOr5eyn-DtC-RovCdr2'
token_resp = httpx.post(
    'http://localhost:8080/realms/orion/protocol/openid-connect/token',
    data={'client_id': 'orion-api', 'grant_type': 'password', 'username': 'operator1', 'password': operator_pw}
)
operator_token = token_resp.json()['access_token']

inc_payload = {
    "title": "Chaos Test Fire",
    "lat": 34.0,
    "lon": -118.0,
    "description": "Triggering network partition...",
    "source": "citizen_app"
}
resp = httpx.post("http://localhost:8001/v1/incidents", json=inc_payload, headers={"Authorization": f"Bearer {operator_token}"})
print(resp.text)
