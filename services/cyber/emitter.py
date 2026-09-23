"""FORGE CYBER event emitter (wiring side).

Emits normalized security events to a JSONL sink when FORGE_CYBER_EVENTS is
set to a writable file path. With the variable unset (the default, including
all tests) emission is a no-op, so wiring is inert unless explicitly enabled.

Emission NEVER raises: telemetry must not break request handling.
"""

import json
import os
import threading
from datetime import datetime, timezone

_lock = threading.Lock()


def _sink_path() -> str:
    return os.environ.get("FORGE_CYBER_EVENTS", "")


def emit(category: str, source: str = "api", actor=None,
         outcome: str = "unknown", **attributes) -> None:
    path = _sink_path()
    if not path:
        return
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "category": category,
        "actor": actor or {},
        "outcome": outcome,
        "attributes": attributes,
    }
    try:
        with _lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
    except Exception:
        pass
