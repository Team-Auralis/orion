"""FORGE CYBER detection engine: rule-based, stateful, evidence-cited."""
from __future__ import annotations

import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .oses import SecurityEvent, haversine_km


@dataclass
class Finding:
    rule_id: str
    title: str
    severity: str
    subject: str
    observed: str
    inferred: str = ""
    confidence: float = 0.0
    evidence_event_ids: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Rule:
    rule_id: str
    title: str
    severity: str
    window_s: int
    threshold: int
    key_fn: staticmethod
    match_fn: staticmethod


class DetectionEngine:
    def __init__(self, nats_publisher_allowlist: dict | None = None,
                 payload_cap_bytes: int = 262_144,
                 asset_max_kmh: float = 160.0,
                 offhours_start: int = 20, offhours_end: int = 6):
        self._lock = threading.Lock()
        self._windows: dict = defaultdict(lambda: defaultdict(deque))
        self._last_geo: dict = {}
        self._last_move: dict = {}
        self.rules: list[Rule] = []
        self.nats_allowlist = nats_publisher_allowlist or {}
        self.payload_cap = payload_cap_bytes
        self.asset_max_kmh = asset_max_kmh
        self.offhours = (offhours_start, offhours_end)
        self._register_builtin_rules()

    def _push(self, key: str, rule_id: str, ts: datetime):
        w = self._windows[key][rule_id]
        w.append(ts)
        cutoff = ts - timedelta(seconds=self._rule_window(rule_id))
        while w and w[0] < cutoff:
            w.popleft()

    def _rule_window(self, rule_id: str) -> int:
        for r in self.rules:
            if r.rule_id == rule_id:
                return r.window_s
        return 3600

    def _count(self, key: str, rule_id: str) -> int:
        return len(self._windows[key].get(rule_id, ()))

    def _emit(self, rule: Rule, ev: SecurityEvent, observed: str,
              inferred: str, confidence: float) -> Finding:
        return Finding(
            rule_id=rule.rule_id, title=rule.title, severity=rule.severity,
            subject=ev.actor.subject, observed=observed, inferred=inferred,
            confidence=confidence,
            evidence_event_ids=[ev.event_id],
        )

    def process(self, ev: SecurityEvent) -> list[Finding]:
        findings: list[Finding] = []
        with self._lock:
            findings.extend(self._auth_bruteforce(ev))
            findings.extend(self._impossible_travel(ev))
            findings.extend(self._breakglass_anomalies(ev))
            findings.extend(self._killswitch_tamper(ev))
            findings.extend(self._policy_deny_burst(ev))
            findings.extend(self._nats_unauthorized_publisher(ev))
            findings.extend(self._payload_oversize(ev))
            findings.extend(self._asset_teleport(ev))
        return findings

    # --- rules -------------------------------------------------
    def _is_offhours(self, ts: datetime) -> bool:
        start, end = self.offhours
        h = ts.hour
        return h >= start or h < end

    def _auth_bruteforce(self, ev: SecurityEvent) -> list[Finding]:
        if not (ev.category == "auth" and ev.action == "login" and ev.outcome == "failed"):
            return []
        rule = self._rule("AUTH-BRUTEFORCE")
        key = f"subject:{ev.actor.subject}"
        self._push(key, rule.rule_id, ev.ts)
        if self._count(key, rule.rule_id) >= rule.threshold:
            observed = (f"{self._count(key, rule.rule_id)} failed logins in "
                        f"{rule.window_s}s from source {ev.source}")
            return [self._emit(rule, ev, observed,
                               "credential guessing or spraying SUSPECTED", 0.7)]
        return []

    def _impossible_travel(self, ev: SecurityEvent) -> list[Finding]:
        if not (ev.category == "auth" and ev.action == "login" and ev.outcome == "success"):
            return []
        geo = ev.attrs.get("geo") or {}
        lat, lon = geo.get("lat"), geo.get("lon")
        if lat is None or lon is None:
            return []
        prev = self._last_geo.get(ev.actor.subject)
        self._last_geo[ev.actor.subject] = (lat, lon, ev.ts)
        if not prev:
            return []
        plat, plon, pts = prev
        dist = haversine_km(plat, plon, lat, lon)
        hours = max((ev.ts - pts).total_seconds(), 1) / 3600.0
        speed = dist / hours
        if speed > 1200.0 and dist > 500.0:
            rule = self._rule("IMPOSSIBLE-TRAVEL")
            return [self._emit(
                rule, ev,
                f"{dist:.0f} km between successive logins ({speed:.0f} km/h)",
                "credential reuse from second location INFERRED", 0.8)]
        return []

    def _breakglass_anomalies(self, ev: SecurityEvent) -> list[Finding]:
        out = []
        if ev.category == "breakglass" and ev.action == "activate":
            rule = self._rule("BG-SPIKE")
            key = f"issuer:{ev.actor.subject}"
            self._push(key, rule.rule_id, ev.ts)
            if self._count(key, rule.rule_id) > rule.threshold:
                out.append(self._emit(
                    rule, ev,
                    f"{self._count(key, rule.rule_id)} break-glass activations "
                    f"within {rule.window_s}s",
                    "override abuse or compulsion SUSPECTED", 0.85))
            if self._is_offhours(ev.ts):
                rule2 = self._rule("BG-OFFHOURS")
                out.append(self._emit(
                    rule2, ev,
                    f"activation at {ev.ts.isoformat()} (outside review window)",
                    "unusual-time override; heightened scrutiny RECOMMENDED", 0.5))
        if (ev.category == "breakglass" and ev.action == "use"
                and ev.outcome in ("expired", "replayed", "invalid")):
            rule3 = self._rule("BG-TOKEN-ABUSE")
            out.append(self._emit(
                rule3, ev,
                f"{ev.outcome} break-glass token presented by {ev.actor.subject}",
                "token theft or replay attempt SUSPECTED", 0.9))
        return out

    def _killswitch_tamper(self, ev: SecurityEvent) -> list[Finding]:
        if ev.category != "pilot.killswitch":
            return []
        unauthorized_role = ev.actor.role != "operator"
        failed_or_anomalous = ev.outcome != "success"
        resumed_without_state = (ev.action == "resume" and ev.attrs.get(
            "had_active_suspension") is False)
        if unauthorized_role or failed_or_anomalous or resumed_without_state:
            rule = self._rule("KS-TAMPER")
            return [self._emit(
                rule, ev,
                f"action={ev.action} outcome={ev.outcome} role={ev.actor.role} "
                f"kind={ev.actor.kind}",
                "kill-switch manipulation attempt SUSPECTED", 0.95)]
        return []

    def _policy_deny_burst(self, ev: SecurityEvent) -> list[Finding]:
        if not (ev.category == "authz" and ev.outcome == "denied"):
            return []
        rule = self._rule("POLICY-DENY-BURST")
        key = f"subject:{ev.actor.subject}"
        self._push(key, rule.rule_id, ev.ts)
        if self._count(key, rule.rule_id) >= rule.threshold:
            return [self._emit(
                rule, ev,
                f"{self._count(key, rule.rule_id)} authorization denials in "
                f"{rule.window_s}s",
                "privilege escalation probing SUSPECTED", 0.75)]
        return []

    def _nats_unauthorized_publisher(self, ev: SecurityEvent) -> list[Finding]:
        if ev.category != "nats.publish":
            return []
        subject = ev.resource
        allowed_publishers = self.nats_allowlist.get(subject)
        if allowed_publishers is None:
            rule = self._rule("NATS-UNKNOWN-SUBJECT")
            return [self._emit(
                rule, ev, f"publish to unregistered subject '{subject}'",
                "event-fabric abuse or new integration UNVERIFIED", 0.4)]
        if ev.source not in allowed_publishers:
            rule = self._rule("NATS-UNAUTHORIZED-PUBLISHER")
            return [self._emit(
                rule, ev,
                f"'{ev.source}' published to '{subject}' (allowed: "
                f"{sorted(allowed_publishers)})",
                "forged event injection SUSPECTED", 0.9)]
        return []

    def _payload_oversize(self, ev: SecurityEvent) -> list[Finding]:
        size = ev.attrs.get("size_bytes")
        if size is None or size <= self.payload_cap:
            return []
        rule = self._rule("PAYLOAD-OVERSIZE")
        return [self._emit(
            rule, ev,
            f"payload {size} bytes exceeds cap {self.payload_cap}",
            "resource-exhaustion or parser-abuse attempt SUSPECTED", 0.8)]

    def _asset_teleport(self, ev: SecurityEvent) -> list[Finding]:
        if ev.category != "asset.move":
            return []
        geo = ev.attrs.get("geo") or {}
        lat, lon = geo.get("lat"), geo.get("lon")
        aid = ev.resource
        if lat is None or lon is None or not aid:
            return []
        prev = self._last_move.get(aid)
        self._last_move[aid] = (lat, lon, ev.ts)
        if not prev:
            return []
        plat, plon, pts = prev
        dt_h = max((ev.ts - pts).total_seconds(), 1) / 3600.0
        dist = haversine_km(plat, plon, lat, lon)
        speed = dist / dt_h
        if speed > self.asset_max_kmh:
            rule = self._rule("ASSET-TELEPORT")
            return [self._emit(
                rule, ev,
                f"asset {aid} moved {dist:.1f} km in {(ev.ts - pts).total_seconds():.0f}s "
                f"({speed:.0f} km/h)",
                "forged telemetry, spoofed device, or state corruption SUSPECTED", 0.85)]
        return []

    def _rule(self, rule_id: str) -> Rule:
        for r in self.rules:
            if r.rule_id == rule_id:
                return r
        raise KeyError(f"unregistered rule {rule_id}")

    def _register_builtin_rules(self):
        self.rules = [
            Rule("AUTH-BRUTEFORCE", "Authentication brute force", "high", 300, 5,
                 staticmethod(lambda ev: f"subject:{ev.actor.subject}"),
                 staticmethod(lambda ev: True)),
            Rule("IMPOSSIBLE-TRAVEL", "Impossible travel login", "high", 0, 0,
                 staticmethod(lambda ev: ev.actor.subject),
                 staticmethod(lambda ev: True)),
            Rule("BG-SPIKE", "Break-glass activation spike", "critical", 3600, 2,
                 staticmethod(lambda ev: f"issuer:{ev.actor.subject}"),
                 staticmethod(lambda ev: True)),
            Rule("BG-OFFHOURS", "Break-glass outside review window", "medium", 0, 0,
                 staticmethod(lambda ev: ev.actor.subject),
                 staticmethod(lambda ev: True)),
            Rule("BG-TOKEN-ABUSE", "Expired/replayed break-glass token use", "critical",
                 0, 0, staticmethod(lambda ev: ev.actor.subject),
                 staticmethod(lambda ev: True)),
            Rule("KS-TAMPER", "Kill-switch manipulation", "critical", 0, 0,
                 staticmethod(lambda ev: ev.actor.subject),
                 staticmethod(lambda ev: True)),
            Rule("POLICY-DENY-BURST", "Authorization denial burst", "medium", 600, 10,
                 staticmethod(lambda ev: f"subject:{ev.actor.subject}"),
                 staticmethod(lambda ev: True)),
            Rule("NATS-UNKNOWN-SUBJECT", "Publish to unregistered NATS subject",
                 "low", 0, 0, staticmethod(lambda ev: ev.source),
                 staticmethod(lambda ev: True)),
            Rule("NATS-UNAUTHORIZED-PUBLISHER", "Unauthorized NATS publisher",
                 "critical", 0, 0, staticmethod(lambda ev: ev.source),
                 staticmethod(lambda ev: True)),
            Rule("PAYLOAD-OVERSIZE", "Oversized event payload", "high", 0, 0,
                 staticmethod(lambda ev: ev.actor.subject),
                 staticmethod(lambda ev: True)),
            Rule("ASSET-TELEPORT", "Physically impossible asset movement", "critical",
                 0, 0, staticmethod(lambda ev: ev.resource),
                 staticmethod(lambda ev: True)),
        ]
