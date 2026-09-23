"""
CIC Layer 3: Quantitative & Semantic Drift Analysis
==================================================
Measures divergence across 5 formal dimensions:
  1. Objective Drift (value weight deltas)
  2. Priority Drift (rank ordering inversions)
  3. Constraint Drift (hard/soft invariant violations)
  4. Semantic Drift (keyword & conceptual degradation)
  5. Institutional Drift (cumulative historical divergence)
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from modules.cic.layer2_intent import IntentVector, IntentConstraint


@dataclass
class DriftReport:
    drift_score: float
    verdict: str  # "PASS", "WARN", "BLOCK"
    drift_types: List[str]
    dimension_deltas: Dict[str, float]
    priority_inversions: int
    constraint_violations: List[str]
    semantic_drift_score: float
    explanation: str


class DriftAnalyzer:
    """Multi-dimensional drift detector combining vector geometry, logic rules, and semantic tracking."""

    def __init__(self, warn_threshold: float = 0.15, block_threshold: float = 0.30):
        self.warn_threshold = warn_threshold
        self.block_threshold = block_threshold

    @staticmethod
    def cosine_drift(v0: Dict[str, float], vt: Dict[str, float]) -> float:
        keys = set(v0) | set(vt)
        dot = sum(v0.get(k, 0.0) * vt.get(k, 0.0) for k in keys)
        mag0 = math.sqrt(sum(v0.get(k, 0.0) ** 2 for k in keys))
        magt = math.sqrt(sum(vt.get(k, 0.0) ** 2 for k in keys))
        if mag0 == 0 or magt == 0:
            return 1.0
        sim = dot / (mag0 * magt)
        return max(0.0, min(1.0, 1.0 - sim))

    @staticmethod
    def composite_drift(v0: Dict[str, float], vt: Dict[str, float]) -> float:
        keys = set(v0) | set(vt)
        if not keys:
            return 0.0
        diffs = [round(abs(v0.get(k, 0.0) - vt.get(k, 0.0)), 6) for k in keys]
        mean_diff = sum(diffs) / len(diffs)
        max_diff = max(diffs)
        return round(max(mean_diff, max_diff), 6)

    @staticmethod
    def calculate_priority_inversions(p_base: List[str], p_target: List[str]) -> int:
        """Count pairwise rank inversions between two priority lists."""
        common = [item for item in p_base if item in p_target]
        inversions = 0
        for i in range(len(common)):
            for j in range(i + 1, len(common)):
                item_a, item_b = common[i], common[j]
                target_idx_a = p_target.index(item_a)
                target_idx_b = p_target.index(item_b)
                if target_idx_a > target_idx_b:
                    inversions += 1
        return inversions

    @staticmethod
    def check_constraints(constraints: List[IntentConstraint], action_context: Dict[str, Any]) -> List[str]:
        """Verify hard constraints against proposed action context."""
        violations = []
        for c in constraints:
            if c.strictness == "HARD":
                # Example rule checks based on standard keywords
                if "zero_civilian_harm" in c.id and action_context.get("expected_casualties", 0) > 0:
                    violations.append(f"HARD CONSTRAINT VIOLATION: {c.rule}")
                if "critical_infrastructure_lock" in c.id and action_context.get("shutdown_unauthorized", False):
                    violations.append(f"HARD CONSTRAINT VIOLATION: {c.rule}")
        return violations

    @staticmethod
    def compute_semantic_drift(expected_concepts: List[str], observed_text: str) -> float:
        """Compute keyword-based semantic coverage loss [0.0 to 1.0]."""
        if not expected_concepts:
            return 0.0
        text_lower = observed_text.lower()
        matched = sum(1 for c in expected_concepts if c.lower() in text_lower)
        coverage = matched / len(expected_concepts)
        return 1.0 - coverage

    def analyze(
        self,
        base_intent: IntentVector,
        action_values: Dict[str, float],
        proposed_priorities: Optional[List[str]] = None,
        action_context: Optional[Dict[str, Any]] = None,
        observed_text: str = "",
        expected_concepts: Optional[List[str]] = None,
    ) -> DriftReport:
        action_context = action_context or {}
        proposed_priorities = proposed_priorities or base_intent.priorities
        expected_concepts = expected_concepts or []

        # 1. Objective drift
        comp_drift = self.composite_drift(base_intent.values, action_values)
        deltas = {
            k: round(abs(base_intent.values.get(k, 0.0) - action_values.get(k, 0.0)), 4)
            for k in (set(base_intent.values) | set(action_values))
        }

        # 2. Priority drift
        inversions = self.calculate_priority_inversions(base_intent.priorities, proposed_priorities)

        # 3. Constraint drift
        violations = self.check_constraints(base_intent.constraints, action_context)

        # 4. Semantic drift
        sem_drift = self.compute_semantic_drift(expected_concepts, observed_text) if observed_text else 0.0

        # Aggregate drift classification
        detected_types = []
        if comp_drift >= self.warn_threshold:
            detected_types.append("OBJECTIVE_DRIFT")
        if inversions > 0:
            detected_types.append("PRIORITY_DRIFT")
        if violations:
            detected_types.append("CONSTRAINT_DRIFT")
        if sem_drift > 0.4:
            detected_types.append("SEMANTIC_DRIFT")

        # Total combined score
        score = max(comp_drift, (inversions * 0.05), sem_drift * 0.5)
        if violations:
            score = 1.0  # Constraint violations immediately saturate score

        # Verdict
        if violations or score >= self.block_threshold:
            verdict = "BLOCK"
        elif score >= self.warn_threshold or detected_types:
            verdict = "WARN"
        else:
            verdict = "PASS"

        explanation = f"Verdict: {verdict}. Composite drift: {comp_drift:.3f}, Priority inversions: {inversions}, Violations: {len(violations)}"

        return DriftReport(
            drift_score=round(score, 4),
            verdict=verdict,
            drift_types=detected_types,
            dimension_deltas=deltas,
            priority_inversions=inversions,
            constraint_violations=violations,
            semantic_drift_score=round(sem_drift, 4),
            explanation=explanation,
        )
