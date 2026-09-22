"""Safety and audit layer — CHRONOS-grade immutable audit log for NECTAR."""

import json
import time
from datetime import datetime, timezone


def audit_event(event_type: str, payload: dict) -> dict:
    """
    Emit a structured audit event to the nectar audit log.

    No fabrications, no silent suppressions.
    """
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "epoch": time.time(),
        "event_type": event_type,
        "component": "NECTAR",
        "mock": event_type.startswith("mock."),
        "payload": payload,
    }
    _write_to_jsonl(event)
    return event


def _write_to_jsonl(event: dict):
    import os

    log_path = os.environ.get("NECTAR_AUDIT_LOG", "logs/nectar_audit.jsonl")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a") as f:
        f.write(json.dumps(event) + "\n")
