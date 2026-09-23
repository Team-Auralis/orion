"""
CIC Layered Architecture Verification Suite
===========================================
Validates the complete 5-layer Civilizational Intent Conservation pipeline:
- Layer 1: Cryptographic provenance & tamper detection
- Layer 2: IntentVector validation & invariants
- Layer 3: Objective, priority, constraint, and semantic drift detection
- Layer 4: Contextual emergency override & false-positive elimination
- Layer 5: HITL escalation, governance authorization, and evolution ledger
"""

import pytest
from modules.cic.layer1_integrity import IntentProvenanceChain
from modules.cic.layer2_intent import IntentVector, IntentConstraint
from modules.cic.layer3_drift import DriftAnalyzer
from modules.cic.layer4_contextual import ContextualCausalEvaluator
from modules.cic.layer5_governance import IntentGovernanceGate


def test_layer1_cryptographic_integrity():
    chain = IntentProvenanceChain()
    b1 = chain.append(version=1, author="operator_1", rationale="Founding", intent_payload={"safety": 0.95})
    b2 = chain.append(version=2, author="operator_2", rationale="Refine", intent_payload={"safety": 0.96})

    # Integrity verification
    valid, msg = chain.verify_integrity()
    assert valid is True
    assert len(chain.chain) == 2
    assert b2.prev_hash == b1.block_hash

    # Tamper detection
    chain.chain[0].intent_payload["safety"] = 0.50  # Tamper payload
    tampered, msg = chain.verify_integrity()
    assert tampered is False
    assert "Tamper detected" in msg


def test_layer2_intent_representation():
    iv = IntentVector()
    valid, msg = iv.validate()
    assert valid is True
    assert iv.get_weight("safety") == 0.95

    # Out of range test
    invalid_iv = IntentVector(values={"safety": 1.5})
    valid, msg = invalid_iv.validate()
    assert valid is False


def test_layer3_objective_drift():
    analyzer = DriftAnalyzer(warn_threshold=0.15, block_threshold=0.30)
    base = IntentVector(values={"safety": 0.95, "sustainability": 0.90, "equity": 0.85})

    # Massive reduction in sustainability
    drifted_values = {"safety": 0.95, "sustainability": 0.20, "equity": 0.85}
    report = analyzer.analyze(base, drifted_values)

    assert "OBJECTIVE_DRIFT" in report.drift_types
    assert report.verdict == "BLOCK"
    assert report.dimension_deltas["sustainability"] == 0.70


def test_layer3_priority_drift():
    analyzer = DriftAnalyzer()
    base = IntentVector(
        values={"safety": 0.95, "autonomy": 0.70},
        priorities=["safety", "autonomy"]
    )

    # Invert priorities: autonomy over safety
    drifted_priorities = ["autonomy", "safety"]
    report = analyzer.analyze(base, base.values, proposed_priorities=drifted_priorities)

    assert "PRIORITY_DRIFT" in report.drift_types
    assert report.priority_inversions == 1
    assert report.verdict in ("WARN", "BLOCK")


def test_layer3_constraint_drift():
    analyzer = DriftAnalyzer()
    c = IntentConstraint(id="zero_civilian_harm", rule="Casualties must be strictly 0", strictness="HARD")
    base = IntentVector(constraints=[c])

    report = analyzer.analyze(
        base,
        base.values,
        action_context={"expected_casualties": 5}
    )

    assert "CONSTRAINT_DRIFT" in report.drift_types
    assert report.verdict == "BLOCK"
    assert len(report.constraint_violations) == 1


def test_layer3_semantic_drift():
    analyzer = DriftAnalyzer()
    base = IntentVector()
    concepts = ["renewable", "sustainability", "preservation"]
    corrupted_text = "Accelerating coal combustion and industrial extraction without quota limits."

    report = analyzer.analyze(
        base,
        base.values,
        observed_text=corrupted_text,
        expected_concepts=concepts
    )

    assert "SEMANTIC_DRIFT" in report.drift_types
    assert report.semantic_drift_score > 0.5


def test_layer4_false_positive_emergency_mitigation():
    analyzer = DriftAnalyzer()
    evaluator = ContextualCausalEvaluator()

    base = IntentVector(values={"safety": 0.95, "sustainability": 0.90})
    # Action temporarily spikes emissions (sustainability drift) during disaster to power ICU
    action_values = {"safety": 0.95, "sustainability": 0.60}
    report = analyzer.analyze(base, action_values)
    assert report.verdict in ("WARN", "BLOCK")

    # Contextual evaluation: Active emergency + transient + preserves higher imperative
    assessment = evaluator.evaluate(
        report,
        context={
            "action_name": "Emergency Diesel ICU Generator",
            "is_emergency": True,
            "temporal_scope": "TRANSIENT",
            "preserves_higher_imperative": True,
        }
    )

    assert assessment.is_mitigated is True
    assert assessment.adjusted_verdict == "CONDITIONAL_PASS"
    assert assessment.is_emergency_override is True


def test_layer4_false_negative_prevention_on_permanent_creep():
    analyzer = DriftAnalyzer()
    evaluator = ContextualCausalEvaluator()

    base = IntentVector(values={"sustainability": 0.90})
    action_values = {"sustainability": 0.60}
    report = analyzer.analyze(base, action_values)

    # Claimed justification without genuine emergency and marked PERMANENT
    assessment = evaluator.evaluate(
        report,
        context={
            "action_name": "Permanent Cost Cutting",
            "is_emergency": False,
            "temporal_scope": "PERMANENT",
            "preserves_higher_imperative": False,
        }
    )

    assert assessment.is_mitigated is False
    assert assessment.adjusted_verdict in ("WARN", "BLOCK")


def test_layer5_governance_escalate_vs_authorized_evolution():
    chain = IntentProvenanceChain()
    base = IntentVector(values={"safety": 0.95, "equity": 0.85})
    chain.append(version=1, author="genesis", rationale="Genesis", intent_payload=base.to_dict())

    gate = IntentGovernanceGate(provenance_chain=chain, current_intent=base)
    analyzer = DriftAnalyzer()
    evaluator = ContextualCausalEvaluator()

    # 1. Unauthorized drift -> ESCALATE TO HITL
    action_values = {"safety": 0.75, "equity": 0.85}
    report = analyzer.analyze(base, action_values)
    assessment = evaluator.evaluate(report, {})
    decision1 = gate.adjudicate(report, assessment, action_name="autonomous_protocol_alpha")

    assert decision1.action == "ESCALATE_TO_HITL"
    assert decision1.requires_human_approval is True
    assert decision1.intent_evolved is False

    # 2. Authorized evolution -> LOG_AND_APPLY
    decision2 = gate.adjudicate(
        report,
        assessment,
        action_name="formal_treaty_revision",
        auth_context={
            "is_evolution_proposal": True,
            "hitl_approved": True,
            "operator_id": "chief_governor",
            "proposal_reason": "Post-crisis structural adjustment",
            "new_values": {"safety": 0.98, "equity": 0.90},
        }
    )

    assert decision2.action == "LOG_AND_APPLY"
    assert decision2.intent_evolved is True
    assert decision2.new_version == 2
    assert gate.current_intent.get_weight("safety") == 0.98
    assert len(chain.chain) == 2
    valid, _ = chain.verify_integrity()
    assert valid is True
