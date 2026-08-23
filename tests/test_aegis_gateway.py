import base64
import hashlib
import hmac
import struct

import pytest

from services.aegis.main import AegisHardwareGateway, AegisIngressError

DEVICE_ID = "A8B4C9"


def sos_payload(latitude=37.7749, longitude=-122.4194, battery=15):
    return b"\x01" + struct.pack(">f", latitude) + struct.pack(">f", longitude) + bytes([battery])


def test_decodes_lorawan_webhook_to_normalized_incident_event():
    gateway = AegisHardwareGateway()
    event = gateway.decode_lorawan_webhook({"end_device_ids": {"dev_eui": DEVICE_ID}, "uplink_message": {"frm_payload": base64.b64encode(sos_payload()).decode(), "f_cnt": 41}})
    assert event["event_type"] == "incident.created"
    assert event["actor_id"] == f"hw-{DEVICE_ID}"
    assert event["hardware_lat"] == pytest.approx(37.7749)
    assert event["hardware_lon"] == pytest.approx(-122.4194)
    assert event["hardware"] == {"transport": "LORAWAN", "device_id": DEVICE_ID, "sequence": 41, "battery_percent": 15}


def test_rejects_invalid_payload_and_coordinates():
    gateway = AegisHardwareGateway()
    with pytest.raises(AegisIngressError, match="payload length"):
        gateway.decode_lorawan_payload("01", DEVICE_ID)
    with pytest.raises(AegisIngressError, match="coordinates out of range"):
        gateway.decode_lorawan_payload(sos_payload(95, 1, 10).hex(), DEVICE_ID)


def test_radio_packet_requires_valid_device_hmac():
    payload_hex, secret = sos_payload().hex(), "radio-secret"
    signature = hmac.new(secret.encode(), f"{DEVICE_ID}:7:{payload_hex}".encode(), hashlib.sha256).hexdigest()
    gateway = AegisHardwareGateway({DEVICE_ID: secret})
    assert gateway.decode_radio_packet(DEVICE_ID.lower(), 7, payload_hex, signature)["hardware"]["transport"] == "RADIO"
    with pytest.raises(AegisIngressError, match="signature"):
        gateway.decode_radio_packet(DEVICE_ID, 7, payload_hex, "bad-signature")
