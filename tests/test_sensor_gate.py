import pytest
from services.omnis.sensor_gate import SensorConsistencyGate
from services.omnis.transfer_guard import TransferGuard


def test_sensor_gate():
    gate = SensorConsistencyGate()
    assert gate.check_readings(
        [
            {
                "sensor_id": "1",
                "metric": "mass",
                "value": 10.0,
                "unit": "kg",
                "timestamp": "1",
            }
        ]
    ).is_consistent
    assert not gate.check_readings(
        [
            {
                "sensor_id": "1",
                "metric": "mass",
                "value": -10.0,
                "unit": "kg",
                "timestamp": "1",
            }
        ]
    ).is_consistent
    assert not gate.check_readings(
        [
            {
                "sensor_id": "1",
                "metric": "temperature",
                "value": -300.0,
                "unit": "C",
                "timestamp": "1",
            }
        ]
    ).is_consistent
    assert not gate.check_readings(
        [
            {
                "sensor_id": "1",
                "metric": "speed",
                "value": 100.0,
                "unit": "m/s",
                "timestamp": "1",
            },
            {
                "sensor_id": "2",
                "metric": "speed",
                "value": 50.0,
                "unit": "m/s",
                "timestamp": "1",
            },
        ]
    ).is_consistent


def test_transfer_guard():
    g = TransferGuard()
    r1 = g.evaluate(0.9, "1", True)
    assert not r1.allow_direct_transfer and r1.require_forge_verification
    r2 = g.evaluate(0.9, "1", False)
    assert r2.allow_direct_transfer and not r2.require_forge_verification
    r3 = g.evaluate(0.2, "1", True)
    assert (
        not r3.allow_direct_transfer
        and r3.require_forge_verification
        and r3.domain_flag == "NOVEL"
    )
    r4 = g.evaluate(0.5, "1", True)
    assert not r4.allow_direct_transfer and r4.require_forge_verification
    r5 = g.evaluate(0.5, "1", False)
    assert r5.allow_direct_transfer and not r5.require_forge_verification


def test_sensor_gate_malformed_readings_are_impossibilities_not_errors():
    gate = SensorConsistencyGate()
    report = gate.check_readings(
        [
            {"metric": "mass", "value": 10.0},
            {"unit": "kg"},  # missing metric/value
            "not a dict",
            None,
        ]
    )
    # Malformed entries must be reported as impossibilities, never raise
    # (gate runs on the unauthenticated /v1/telemetry/compress endpoint).
    assert not report.is_consistent
    assert len(report.impossibilities) == 3
    assert report.confidence == 0.0
