"""
CIC Layer 4: Contextual & Causal Drift Discrimination
====================================================
Prevents False Positives by analyzing the causal and temporal context of an action:
- Distinguishes transient tactical emergency overrides from systemic value creep.
- Evaluates if a lower-priority value trade-off is causally necessary to preserve
  a higher-priority foundational imperative (e.g. temporary emissions increase to save ICU lives).
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional
from modules.cic.layer3_drift import DriftReport


@dataclass
class ContextualAssessment:
    is_mitigated: bool
    adjusted_verdict: str
    mitigation_reason: str
    is_emergency_override: bool
    temporal_scope: str  # "TRANSIENT" or "PERMANENT"
    causal_justification: str


class ContextualCausalEvaluator:
    """Evaluates the situational legitimacy of apparent value drifts."""

    @staticmethod
    def evaluate(
        drift_report: DriftReport,
        context: Dict[str, Any],
    ) -> ContextualAssessment:
        is_emergency = context.get("is_emergency", False)
        temporal_scope = context.get("temporal_scope", "PERMANENT").upper()
        preserves_higher_imperative = context.get("preserves_higher_imperative", False)
        action_name = context.get("action_name", "unspecified_action")

        # Hard constraint violations cannot be contextually bypassed
        if drift_report.constraint_violations:
            return ContextualAssessment(
                is_mitigated=False,
                adjusted_verdict="BLOCK",
                mitigation_reason="Hard constraint violations cannot be contextually overridden.",
                is_emergency_override=False,
                temporal_scope=temporal_scope,
                causal_justification="Strict invariant breached.",
            )

        # Emergency transient override: e.g. temporary emissions to save hospital lives
        if is_emergency and temporal_scope == "TRANSIENT" and preserves_higher_imperative:
            if drift_report.verdict in ("WARN", "BLOCK"):
                return ContextualAssessment(
                    is_mitigated=True,
                    adjusted_verdict="CONDITIONAL_PASS",
                    mitigation_reason=(
                        f"Action '{action_name}' causes temporary drift ({drift_report.drift_score:.2f}) "
                        f"but causally protects critical imperative during active emergency."
                    ),
                    is_emergency_override=True,
                    temporal_scope="TRANSIENT",
                    causal_justification="Emergency life preservation supersedes transient operational drift.",
                )

        # Normal execution - verdict remains as analyzed
        return ContextualAssessment(
            is_mitigated=False,
            adjusted_verdict=drift_report.verdict,
            mitigation_reason="No legitimate emergency override or causal justification detected.",
            is_emergency_override=False,
            temporal_scope=temporal_scope,
            causal_justification="Standard operational context.",
        )
