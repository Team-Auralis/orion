"""Pure-numeric opportunity scorer — deterministic, NEVER an LLM.

Formula (weights from config/default.yaml ``scoring:``, defaults sum 100)::

    score_0_100 = 100 * sum(weight_i * factor_i) / sum(weight_i)

Factors, each in 0..1 (higher = better opportunity):

=========================  ==================================================
factor                     formula
=========================  ==================================================
expected_value             min(max(value-cost, 0), EV_CAP_Paise) / EV_CAP_Paise
                           EV_CAP_Paise = 5000 (₹50); capped-linear net payout
demand_confidence          demand_hint * confidence
competition_risk           1.0 - competition_hint          (inverted)
execution_cost             1.0 - min(cost, COST_CAP_Paise)/COST_CAP_Paise
                           COST_CAP_Paise = 1000 (₹10)     (inverted)
safety_compat              1.0 if (automation_allowed and not suspicious)
                           else 0.0
time_to_revenue            no deadline -> 1.0 (immediate);
                           ISO deadline -> clamp(1 - days_left/60, 0, 1);
                           unparseable -> 0.5               (inverted)
automation_feasibility     1.0 if automation_allowed else 0.0
=========================  ==================================================

Suspicious detection is HARD-CODED regex/heuristics (see
``SCAM_MARKERS`` + the payout-sanity rules) — deterministic logic, not a
model call. A suspicious offer is hard-capped at ``SUSPICIOUS_SCORE_CAP``
(10/100), flagged with a reason, and recorded ``REJECTED`` so it can never
enter the approval flow.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from orion.config import get_config
from orion.connectors.base import SourceOffer, offer_hash
from orion.log import get_logger
from orion.models import Opportunity

log = get_logger("scoring")

# Hard caps for the factor formulas (documented above).
EV_CAP_Paise = 5000          # ₹50 net payout saturates expected_value
COST_CAP_Paise = 1000        # ₹10 startup cost zeroes execution_cost
PAYOUT_SANITY_CAP_Paise = 10000  # ₹100+ payouts are implausible here
DEADLINE_HORIZON_DAYS = 60
SUSPICIOUS_SCORE_CAP = 10.0  # hard score ceiling for suspicious offers

FACTOR_KEYS = (
    "expected_value",
    "demand_confidence",
    "competition_risk",
    "execution_cost",
    "safety_compat",
    "time_to_revenue",
    "automation_feasibility",
)

# Hard-coded scam markers: (pattern name, case-insensitive regex).
# Scanned over title + description + platform_notes.
SCAM_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("guaranteed_returns", re.compile(r"guaranteed\s+returns?", re.I)),
    ("guaranteed_profit", re.compile(r"guaranteed\s+(?:profit|income|earnings?)", re.I)),
    ("pay_to_unlock", re.compile(
        r"pay\s*[₹$]?\s*\d[\d,]*\s*(?:to|and)\s*(?:unlock|access|claim|start)", re.I
    )),
    ("unlock_large_sum", re.compile(r"unlock\s*[₹$]?\s*\d[\d,]*", re.I)),
    ("crypto", re.compile(r"\bcrypto(?:currency)?\b", re.I)),
    ("get_rich", re.compile(r"get\s+rich", re.I)),
    ("double_your_money", re.compile(r"double\s+your\s+(?:money|investment)", re.I)),
    ("risk_free_returns", re.compile(r"risk[-\s]?free\s+(?:profit|returns?|earnings?)", re.I)),
    ("no_experience_big_earn", re.compile(
        r"no\s+experience[^.!?\n]{0,40}earn\s*[₹$]?\s*\d", re.I
    )),
)


@dataclass(frozen=True)
class ScoreBreakdown:
    """Result of one scoring pass. ``score_0_100`` is always 0..100."""

    score_0_100: float
    factors: dict[str, float] = field(default_factory=dict)
    suspicious: bool = False
    suspicious_reason: str = ""
    rejected_reason: str = ""


def detect_suspicious(offer: SourceOffer) -> str:
    """Return the first scam reason for ``offer``, or ``""`` if clean.

    Pure deterministic heuristics — keyword/regex markers plus payout
    sanity: absolute cap, cost>payout, and an absurd payout/effort ratio.
    """
    text = " ".join(
        filter(None, (offer.title, offer.description, offer.platform_notes))
    )
    for name, pattern in SCAM_MARKERS:
        if pattern.search(text):
            return f"scam marker '{name}' matched in offer text"
    value = offer.estimated_value_paise
    cost = offer.cost_paise
    if value > PAYOUT_SANITY_CAP_Paise:
        return (
            f"payout-effort implausible: {value} paise exceeds sanity cap "
            f"{PAYOUT_SANITY_CAP_Paise} paise"
        )
    if cost > 0 and cost > value:
        return f"cost {cost} paise exceeds payout {value} paise"
    if cost > 0 and value / cost >= 50 and value > EV_CAP_Paise:
        return f"payout/cost ratio absurd: {value}/{cost} paise"
    return ""


def _time_to_revenue(deadline: Optional[str]) -> float:
    """1.0 when revenue can start immediately; decays over a 60-day horizon."""
    if not deadline or not deadline.strip():
        return 1.0
    try:
        due = datetime.fromisoformat(deadline.strip().replace("Z", "+00:00"))
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        days_left = (due.date() - datetime.now(timezone.utc).date()).days
    except ValueError:
        try:
            days_left = (date.fromisoformat(deadline.strip())
                         - datetime.now(timezone.utc).date()).days
        except ValueError:
            return 0.5  # deadline present but unparseable: assume slow-ish
    return max(0.0, min(1.0, 1.0 - days_left / DEADLINE_HORIZON_DAYS))


class OpportunityScorer:
    """Scores :class:`SourceOffer`s. Weights come from config ``scoring:``;
    pass ``weights`` to override individual keys (tests use this to prove
    weight changes reorder scores predictably)."""

    def __init__(self, weights: Optional[dict[str, float]] = None):
        self.weights: dict[str, float] = get_config().scoring.as_weights()
        if weights:
            unknown = set(weights) - set(FACTOR_KEYS)
            if unknown:
                raise ValueError(f"unknown scoring weights: {sorted(unknown)}")
            self.weights.update(weights)

    def score(self, offer: SourceOffer) -> ScoreBreakdown:
        """Pure numeric score for one offer (no I/O, no LLM)."""
        suspicious_reason = detect_suspicious(offer)
        suspicious = bool(suspicious_reason)

        net = max(offer.estimated_value_paise - offer.cost_paise, 0)
        factors: dict[str, float] = {
            "expected_value": min(net, EV_CAP_Paise) / EV_CAP_Paise,
            "demand_confidence": offer.demand_hint * offer.confidence,
            "competition_risk": 1.0 - offer.competition_hint,
            "execution_cost": 1.0 - min(offer.cost_paise, COST_CAP_Paise) / COST_CAP_Paise,
            "safety_compat": 1.0 if (offer.automation_allowed and not suspicious) else 0.0,
            "time_to_revenue": _time_to_revenue(offer.deadline),
            "automation_feasibility": 1.0 if offer.automation_allowed else 0.0,
        }

        total_weight = sum(self.weights.get(k, 0.0) for k in FACTOR_KEYS)
        if total_weight <= 0:
            raw = 0.0
        else:
            raw = 100.0 * sum(
                self.weights.get(k, 0.0) * factors[k] for k in FACTOR_KEYS
            ) / total_weight
        raw = max(0.0, min(100.0, raw))

        if suspicious:
            score = min(raw, SUSPICIOUS_SCORE_CAP)
            rejected_reason = suspicious_reason
            log.warning(
                "suspicious offer rejected by scorer",
                extra={"title": offer.title, "reason": suspicious_reason},
            )
        else:
            score = raw
            rejected_reason = ""

        return ScoreBreakdown(
            score_0_100=round(score, 2),
            factors=factors,
            suspicious=suspicious,
            suspicious_reason=suspicious_reason,
            rejected_reason=rejected_reason,
        )

    def score_opportunity_from_offer(
        self, offer: SourceOffer, session
    ) -> Opportunity:
        """Store a :class:`ScoreBreakdown` on the Opportunity row for ``offer``.

        The row is located by content hash (must already exist — run
        ``DiscoveryService.scan`` first). Status becomes ``SCORED``, or
        ``REJECTED`` directly when suspicious (reason recorded) so the
        offer can never reach the approval flow.
        """
        breakdown = self.score(offer)
        row = (
            session.query(Opportunity)
            .filter(Opportunity.content_hash == offer_hash(offer))
            .first()
        )
        if row is None:
            raise ValueError(
                f"no Opportunity row for offer {offer.title!r} — scan first"
            )
        row.score_0_100 = breakdown.score_0_100
        row.factors_json = json.dumps(breakdown.factors, sort_keys=True)
        row.suspicious = breakdown.suspicious
        row.suspicious_reason = breakdown.suspicious_reason or None
        row.rejected_reason = breakdown.rejected_reason or None
        row.status = "REJECTED" if breakdown.suspicious else "SCORED"
        session.flush()
        return row
