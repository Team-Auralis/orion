"""
ORION Civilizational Intent Conservation (CIC) Framework
========================================================
A 5-layer formal architecture for detecting, auditing, and governing
societal intent continuity in civilization-scale AI:

  Layer 1: Deterministic Provenance (SHA-256 Hash Chaining)
  Layer 2: Intent Representation (IntentVector, Invariants, Constraints)
  Layer 3: Multi-dimensional Drift Analysis (Objective, Priority, Constraint, Semantic)
  Layer 4: Contextual & Causal Discrimination (Emergency vs Systemic)
  Layer 5: Governance & Evolution Gate (HITL Escalation & Authorized Ledger)
"""

from modules.cic.layer1_integrity import IntentProvenanceChain, IntentBlock
from modules.cic.layer2_intent import IntentVector, IntentConstraint
from modules.cic.layer3_drift import DriftAnalyzer, DriftReport
from modules.cic.layer4_contextual import ContextualCausalEvaluator, ContextualAssessment
from modules.cic.layer5_governance import IntentGovernanceGate, GovernanceDecision

__all__ = [
    "IntentProvenanceChain",
    "IntentBlock",
    "IntentVector",
    "IntentConstraint",
    "DriftAnalyzer",
    "DriftReport",
    "ContextualCausalEvaluator",
    "ContextualAssessment",
    "IntentGovernanceGate",
    "GovernanceDecision",
]
