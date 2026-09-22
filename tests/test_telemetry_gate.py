import pytest
from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


def test_telemetry_compress_without_readings_has_no_gate():
    resp = client.post(
        "/v1/telemetry/compress", json={"device_id": "d1", "states": [0, 1, 2, 3, 0]}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["original_elements"] == 5
    assert "gate" not in body


def test_telemetry_gate_rejects_impossible_reading():
    resp = client.post(
        "/v1/telemetry/compress",
        json={
            "device_id": "d1",
            "states": [1, 1, 1],
            "readings": [
                {
                    "sensor_id": "s1",
                    "metric": "mass",
                    "value": -10.0,
                    "unit": "kg",
                    "timestamp": "1",
                }
            ],
        },
    )
    body = resp.json()
    assert body["gate"]["is_consistent"] is False
    assert body["gate"]["impossibilities"] == ["Negative mass: -10.0"]
    assert body["original_elements"] == 3


def test_telemetry_gate_passes_consistent_readings():
    resp = client.post(
        "/v1/telemetry/compress",
        json={
            "device_id": "d1",
            "states": [2, 0, 3],
            "readings": [
                {
                    "sensor_id": "s1",
                    "metric": "temperature",
                    "value": 25.0,
                    "unit": "C",
                    "timestamp": "1",
                }
            ],
        },
    )
    body = resp.json()
    assert body["gate"]["is_consistent"] is True
    assert body["gate"]["contradictions"] == []
    assert body["gate"]["impossibilities"] == []
    assert body["gate"]["confidence"] == 1.0


def test_telemetry_compress_rejects_oversized_states():
    # O(n) packing loops on an unauthenticated endpoint: cap list length so a
    # giant states array cannot be a memory/CPU DoS.
    resp = client.post(
        "/v1/telemetry/compress",
        json={
            "device_id": "d1",
            "states": [0] * 100_001,
        },
    )
    assert resp.status_code == 422


def test_telemetry_compress_rejects_oversized_readings():
    resp = client.post(
        "/v1/telemetry/compress",
        json={
            "device_id": "d1",
            "states": [0, 1],
            "readings": [
                {
                    "sensor_id": "s1",
                    "metric": "m",
                    "value": 1.0,
                    "unit": "u",
                    "timestamp": "1",
                }
            ]
            * 10_001,
        },
    )
    assert resp.status_code == 422
