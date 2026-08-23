import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from fastapi import HTTPException

# We use Redis for the kill switch so it applies across all API nodes and the worker immediately.
# If Redis is down, we fail closed.
import redis

# Use the same redis URL as main
redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
try:
    redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
except Exception:
    redis_client = None

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
    if os.environ.get("PILOT_MODE", "").strip().lower() not in ("1", "true", "yes"):
        return None

    raw = os.environ.get("PILOT_GEOFENCE", "")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) != 4:
        raise ValueError(f"PILOT_GEOFENCE must be 'min_lat,min_lon,max_lat,max_lon'")
    min_lat, min_lon, max_lat, max_lon = (float(p) for p in parts)
    if not (min_lat < max_lat and min_lon < max_lon):
        raise ValueError(f"PILOT_GEOFENCE corners are inverted")
    return {
        "min_lat": min_lat,
        "min_lon": min_lon,
        "max_lat": max_lat,
        "max_lon": max_lon,
    }

def is_suspended() -> bool:
    """True / False / None (None = state unknown because Redis is unavailable)."""
    if not redis_client:
        return None
    try:
        return redis_client.get("pilot:suspended") == "1"
    except Exception:
        return None

def suspend_pilot(actor_id: str, reason: str):
    if not redis_client:
        raise HTTPException(status_code=500, detail="Redis unavailable")
    redis_client.set("pilot:suspended", "1")
    redis_client.set("pilot:suspended_by", actor_id)
    redis_client.set("pilot:suspension_reason", reason)
    _audit_log("PILOT_SUSPENDED", {"actor_id": actor_id, "reason": reason})

def resume_pilot(actor_id: str):
    if not redis_client:
        raise HTTPException(status_code=500, detail="Redis unavailable")
    prev_by = redis_client.get("pilot:suspended_by")
    prev_reason = redis_client.get("pilot:suspension_reason")
    redis_client.delete("pilot:suspended")
    redis_client.delete("pilot:suspended_by")
    redis_client.delete("pilot:suspension_reason")
    _audit_log("PILOT_RESUMED", {"actor_id": actor_id, "previous": {"by": prev_by, "reason": prev_reason}})

def pilot_status() -> Dict[str, Any]:
    try:
        cfg = get_pilot_config()
        fence = {k: cfg[k] for k in ("min_lat", "min_lon", "max_lat", "max_lon")} if cfg else None
        config_error = None
    except ValueError as e:
        fence = None
        config_error = str(e)
        
    suspended = is_suspended()
    try:
        by = redis_client.get("pilot:suspended_by") if redis_client else None
        reason = redis_client.get("pilot:suspension_reason") if redis_client else None
    except Exception:
        by = None
        reason = None

    return {
        "pilot_mode": fence is not None or config_error is not None,
        "geofence": fence,
        "config_error": config_error,
        "kill_switch_state": {True: "SUSPENDED", False: "ACTIVE", None: "UNKNOWN"}[suspended],
        "suspended": suspended is True,
        "suspended_by": by,
        "suspension_reason": reason,
    }

def enforce_pilot_active():
    """Fail-closed check to ensure the pilot is not suspended by the kill switch.

    Semantics:
    - An explicit suspension record ALWAYS blocks, even if PILOT_MODE was later
      turned off (the kill switch outranks configuration).
    - When the pilot is ON (or misconfigured), an UNKNOWN state (Redis down)
      also blocks: fail closed.
    - When the pilot is OFF and no suspension record exists, ingestion is free
      (dev environments without Redis must not be dead).
    """
    state = is_suspended()

    try:
        cfg = get_pilot_config()
        config_error = None
    except ValueError as e:
        cfg = None
        config_error = e

    if state is True:
        raise HTTPException(
            status_code=503,
            detail="Pilot operations are suspended by an operator kill switch. Fail-closed state active.",
        )

    if cfg is None and config_error is None:
        return  # Pilot mode off, no suspension record.

    # Pilot ON or misconfigured: unknown kill-switch state fails closed.
    if state is None:
        raise HTTPException(
            status_code=503,
            detail="Pilot kill-switch state cannot be verified (Redis unavailable). Failing closed.",
        )

    if config_error is not None:
        raise HTTPException(
            status_code=503,
            detail=f"Pilot misconfiguration, failing closed",
        )

def enforce_pilot_constraints(latitude: float, longitude: float):
    """Gate for civilian ingestion during the closed pilot."""
    enforce_pilot_active()

    cfg = get_pilot_config()
    if cfg is None:
        return # Not in pilot mode

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
