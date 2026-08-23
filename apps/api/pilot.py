import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from fastapi import HTTPException

# In-memory kill switch. Cleared on process restart; re-assert via /v1/pilot/suspend.
_suspended = False
_suspended_by = None
_suspension_reason = None


def _audit_log(event_type: str, payload: Dict[str, Any]):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        **payload,
    }
    try:
        log_dir = os.path.join(os.getcwd(), "logs")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "chronos_audit.jsonl"), "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"PILOT AUDIT WRITE FAILED: {e}")


def get_pilot_config() -> Optional[Dict[str, Any]]:
    """Returns the active pilot configuration, or None when pilot mode is off.

    Geofence format: "min_lat,min_lon,max_lat,max_lon".
    Config is read per-request so changes take effect without redeploy.
    """
    if os.environ.get("PILOT_MODE", "").strip().lower() not in ("1", "true", "yes"):
        return None

    raw = os.environ.get("PILOT_GEOFENCE", "")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) != 4:
        raise ValueError(f"PILOT_GEOFENCE must be 'min_lat,min_lon,max_lat,max_lon', got '{raw}'")
    min_lat, min_lon, max_lat, max_lon = (float(p) for p in parts)
    if not (min_lat < max_lat and min_lon < max_lon):
        raise ValueError(f"PILOT_GEOFENCE corners are inverted: '{raw}'")
    return {
        "min_lat": min_lat,
        "min_lon": min_lon,
        "max_lat": max_lat,
        "max_lon": max_lon,
    }


def is_suspended() -> bool:
    return _suspended


def suspend_pilot(actor_id: str, reason: str):
    global _suspended, _suspended_by, _suspension_reason
    _suspended = True
    _suspended_by = actor_id
    _suspension_reason = reason
    _audit_log("PILOT_SUSPENDED", {"actor_id": actor_id, "reason": reason})


def resume_pilot(actor_id: str):
    global _suspended, _suspended_by, _suspension_reason
    _suspended = False
    prev = (_suspended_by, _suspension_reason)
    _suspended_by = None
    _suspension_reason = None
    _audit_log("PILOT_RESUMED", {"actor_id": actor_id, "previous": {"by": prev[0], "reason": prev[1]}})


def pilot_status() -> Dict[str, Any]:
    try:
        cfg = get_pilot_config()
        fence = {k: cfg[k] for k in ("min_lat", "min_lon", "max_lat", "max_lon")} if cfg else None
        config_error = None
    except ValueError as e:
        fence = None
        config_error = str(e)
    return {
        "pilot_mode": fence is not None or config_error is not None,
        "geofence": fence,
        "config_error": config_error,
        "suspended": _suspended,
        "suspended_by": _suspended_by,
        "suspension_reason": _suspension_reason,
    }


def enforce_pilot_constraints(latitude: float, longitude: float):
    """Gate for civilian ingestion during the closed pilot. Fails closed."""
    if _suspended:
        raise HTTPException(
            status_code=503,
            detail="Pilot operations are suspended by an operator kill switch.",
        )

    try:
        cfg = get_pilot_config()
    except ValueError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Pilot misconfiguration, failing closed: {e}",
        )
    if cfg is None:
        return

    inside = (
        cfg["min_lat"] <= latitude <= cfg["max_lat"]
        and cfg["min_lon"] <= longitude <= cfg["max_lon"]
    )
    if inside:
        return

    _audit_log(
        "PILOT_GEOFENCE_REJECTED",
        {"latitude": latitude, "longitude": longitude},
    )
    raise HTTPException(
        status_code=403,
        detail="Location is outside the authorized pilot geofence.",
    )
