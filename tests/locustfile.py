from locust import HttpUser, task, between
import uuid
import json

class OrionLoadTest(HttpUser):
    host = "http://localhost:8000"
    wait_time = between(0.01, 0.05) # Blast the API

    @task
    def test_incident_creation_and_circuit_breakers(self):
        # We try to trigger the OPA circuit breaker by hitting a protected endpoint
        # without a valid break-glass token.
        # Once it hits 5 failures, OPA will trip and return 503 instead of 403.
        
        headers = {
            "Authorization": "Bearer FAKE_TOKEN",
        }
        
        # Fire requests to trigger Keycloak / OPA circuit breaker
        with self.client.get("/v1/incidents", headers=headers, catch_response=True) as response:
            if response.status_code == 403:
                response.success() # Expected before CB trips
            elif response.status_code == 503:
                response.success() # Expected AFTER CB trips!
            else:
                response.failure(f"Unexpected status code: {response.status_code}")
