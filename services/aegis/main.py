"""AEGIS hardware ingress gateway."""
import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import math
import os
import re
import struct
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

import nats

NATS_URL = os.environ.get("NATS_URL", "nats://localhost:4222")
DEVICE_ID_RE = re.compile(r"^[A-Fa-f0-9]{6,32}$")


class AegisIngressError(ValueError):
    """A packet is malformed, unauthenticated, or unsafe to route."""


class AegisHardwareGateway:
    """Normalize LoRaWAN and authenticated radio SOS packets for ORION.

    LoRaWAN network servers authenticate uplinks before forwarding their
    webhook. Direct radio requires an HMAC-SHA256 signature over
    ``device_id:sequence:payload_hex``. Device keys come from
    ``AEGIS_DEVICE_SECRETS_JSON`` as ``{device_id: secret}``.
    """
    def __init__(self, device_secrets: Optional[Mapping[str, str]] = None):
        self.nc = nats.NATS()
        self.device_secrets = {
            self._validate_device_id(device_id): secret
            for device_id, secret in (device_secrets or self._load_device_secrets()).items()
        }

    @staticmethod
    def _load_device_secrets() -> Mapping[str, str]:
        try:
            secrets = json.loads(os.environ.get("AEGIS_DEVICE_SECRETS_JSON", "{}"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("AEGIS_DEVICE_SECRETS_JSON must contain a JSON object") from exc
        if not isinstance(secrets, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in secrets.items()):
            raise RuntimeError("AEGIS_DEVICE_SECRETS_JSON must map device IDs to secrets")
        return secrets

    async def connect(self) -> None:
        await self.nc.connect(NATS_URL)
        print("AEGIS Gateway connected to Event Mesh.")

    @staticmethod
    def _validate_device_id(device_id: str) -> str:
        normalized = device_id.strip().upper()
        if not DEVICE_ID_RE.fullmatch(normalized):
            raise AegisIngressError("invalid device identifier")
        return normalized

    @staticmethod
    def _decode_sos_payload(payload: bytes) -> tuple[float, float, int]:
        # v1: SOS type, big-endian float32 lat/lon, battery percentage.
        if len(payload) != 10:
            raise AegisIngressError("invalid payload length; expected 10 bytes")
        if payload[0] != 0x01:
            raise AegisIngressError("unsupported AEGIS message type")
        latitude, longitude = struct.unpack(">ff", payload[1:9])
        battery = payload[9]
        if not all(math.isfinite(value) for value in (latitude, longitude)):
            raise AegisIngressError("coordinates must be finite")
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise AegisIngressError("coordinates out of range")
        if battery > 100:
            raise AegisIngressError("battery level out of range")
        return latitude, longitude, battery

    def decode_lorawan_payload(self, payload_hex: str, device_eui: str, frame_counter: Optional[int] = None) -> dict[str, Any]:
        """Decode a LoRaWAN payload after network-server authentication."""
        try:
            payload = binascii.unhexlify(payload_hex)
        except (binascii.Error, ValueError) as exc:
            raise AegisIngressError("payload must be hexadecimal") from exc
        return self._build_incident_event(payload, device_eui, frame_counter, "LORAWAN")

    def decode_lorawan_webhook(self, webhook: Mapping[str, Any]) -> dict[str, Any]:
        """Accept a The Things Stack-compatible authenticated uplink webhook."""
        try:
            device_eui = webhook["end_device_ids"]["dev_eui"]
            uplink = webhook["uplink_message"]
            payload = base64.b64decode(uplink["frm_payload"], validate=True)
            frame_counter = uplink.get("f_cnt")
        except (KeyError, TypeError, ValueError, binascii.Error) as exc:
            raise AegisIngressError("invalid LoRaWAN webhook") from exc
        return self._build_incident_event(payload, device_eui, frame_counter, "LORAWAN")

    def decode_radio_packet(self, device_id: str, sequence: int, payload_hex: str, signature: str) -> dict[str, Any]:
        """Authenticate and decode a direct-radio packet with a per-device key."""
        normalized_id = self._validate_device_id(device_id)
        if not isinstance(sequence, int) or sequence < 0:
            raise AegisIngressError("radio sequence must be a non-negative integer")
        secret = self.device_secrets.get(normalized_id)
        if not secret:
            raise AegisIngressError("unregistered radio device")
        expected = hmac.new(secret.encode(), f"{normalized_id}:{sequence}:{payload_hex.lower()}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature.lower()):
            raise AegisIngressError("invalid radio packet signature")
        try:
            payload = binascii.unhexlify(payload_hex)
        except (binascii.Error, ValueError) as exc:
            raise AegisIngressError("payload must be hexadecimal") from exc
        return self._build_incident_event(payload, normalized_id, sequence, "RADIO")

    def _build_incident_event(self, payload: bytes, device_id: str, sequence: Optional[int], transport: str) -> dict[str, Any]:
        device_id = self._validate_device_id(device_id)
        latitude, longitude, battery = self._decode_sos_payload(payload)
        fingerprint = hashlib.sha256(f"{device_id}:{sequence if sequence is not None else '-'}:{payload.hex()}".encode()).hexdigest()
        return {
            "event_id": f"evt-hw-{fingerprint[:24]}", "event_type": "incident.created", "version": 1,
            "timestamp": datetime.now(timezone.utc).isoformat(), "incident_id": f"INC-HW-{uuid.uuid4().hex[:8].upper()}",
            "actor_id": f"hw-{device_id}", "incident_type": "HARDWARE_SOS", "message": f"{transport} SOS; battery={battery}%",
            "correlation_id": f"aegis-{fingerprint[:24]}", "hardware_lat": latitude, "hardware_lon": longitude,
            "hardware": {"transport": transport, "device_id": device_id, "sequence": sequence, "battery_percent": battery},
        }

    async def route_event(self, event: Mapping[str, Any]) -> None:
        if not self.nc.is_connected:
            raise ConnectionError("AEGIS is not connected to NATS")
        await self.nc.publish("incident.created", json.dumps(event).encode())

    async def decode_and_route_payload(self, hex_payload: str, device_eui: str) -> dict[str, Any]:
        event = self.decode_lorawan_payload(hex_payload, device_eui)
        await self.route_event(event)
        return event


async def run_simulation() -> None:
    gateway = AegisHardwareGateway()
    await gateway.connect()
    try:
        await gateway.decode_and_route_payload("01421719c2c2f4d54f0f", "A8B4C9")
    finally:
        await gateway.nc.close()


if __name__ == "__main__":
    asyncio.run(run_simulation())
