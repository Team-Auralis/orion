"""FORGE CYBER kernel: normalized security event schema (OSES)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Actor:
    subject: str = "unknown"
    role: str = "unknown"
    kind: str = "human"


@dataclass
class SecurityEvent:
    event_id: str
    ts: datetime
    source: str
    category: str
    action: str
    outcome: str
    actor: Actor
    resource: str = ""
    severity: str = "info"
    attrs: dict = field(default_factory=dict)

    @staticmethod
    def create(source: str, category: str, action: str, outcome: str,
               subject: str = "unknown", role: str = "unknown",
               actor_kind: str = "human", resource: str = "",
               attrs: dict | None = None, ts: datetime | None = None,
               severity: str = "info") -> "SecurityEvent":
        return SecurityEvent(
            event_id=f"sev-{uuid.uuid4().hex[:12]}",
            ts=ts or _now(),
            source=source,
            category=category,
            action=action,
            outcome=outcome,
            actor=Actor(subject=subject, role=role, kind=actor_kind),
            resource=resource,
            severity=severity,
            attrs=dict(attrs or {}),
        )

    @staticmethod
    def normalize(raw: dict) -> "SecurityEvent":
        actor_raw = raw.get("actor") or {}
        ts_raw = raw.get("ts")
        if isinstance(ts_raw, str):
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        elif isinstance(ts_raw, datetime):
            ts = ts_raw if ts_raw.tzinfo else ts_raw.replace(tzinfo=timezone.utc)
        else:
            ts = _now()
        return SecurityEvent(
            event_id=raw.get("event_id") or f"sev-{uuid.uuid4().hex[:12]}",
            ts=ts,
            source=str(raw.get("source", "unattributed")),
            category=str(raw.get("category", "generic")),
            action=str(raw.get("action", "unknown")),
            outcome=str(raw.get("outcome", "unknown")),
            actor=Actor(
                subject=str(actor_raw.get("subject", raw.get("subject", "unknown"))),
                role=str(actor_raw.get("role", raw.get("role", "unknown"))),
                kind=str(actor_raw.get("kind", "human")),
            ),
            resource=str(raw.get("resource", "")),
            severity=str(raw.get("severity", "info")),
            attrs=dict(raw.get("attrs") or {}),
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        return d


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
