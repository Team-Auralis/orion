"""
CIC Layer 5: Governance, Authorization & Evolution Gate
======================================================
The constitutional enforcement and evolution gateway:
- Escalates unauthorized drift to Human-in-the-Loop (HITL) operators
- Authorizes and commits formal intent evolution proposals into the Layer 1 chain
- Manages transient emergency permits and audit logging
"""

import time
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional
from modules.cic.layer1_integrity import IntentProvenanceChain
from modules.cic.layer2_intent import IntentVector
from modules.cic.layer3_drift import DriftReport
from modules.cic.layer4_contextual import ContextualAssessment


@dataclass
class GovernanceDecision:
    action: str  # "PERMIT", "ALLOW_TRANSIENT_OVERRIDE", "ESCALATE_TO_HITL", "BLOCK_ACTION", "LOG_AND_APPLY"
    requires_human_approval: bool
    intent_evolved: bool
    new_version: Optional[int]
    rationale: str
    audit_entry: Dict[str, Any]


class IntentGovernanceGate:
    """Orchestrates authorization between drift detection, context evaluation, and human governance."""

    def __init__(self, provenance_chain: IntentProvenanceChain, current_intent: IntentVector):
        self.chain = provenance_chain
        self.current_intent = current_intent
        self.audit_log = []

    def adjudicate(
        self,
        drift_report: DriftReport,
        context_assessment: ContextualAssessment,
        action_name: str,
        auth_context: Optional[Dict[str, Any]] = None,
    ) -> GovernanceDecision:
        auth_context = auth_context or {}
        is_formal_proposal = auth_context.get("is_evolution_proposal", False)
        hitl_approved = auth_context.get("hitl_approved", False)
        operator_id = auth_context.get("operator_id", "anonymous")
        proposal_reason = auth_context.get("proposal_reason", "")

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Case 1: Formal Intent Evolution Proposal with HITL Approval
        if is_formal_proposal and hitl_approved:
            new_values = auth_context.get("new_values", self.current_intent.values)
            new_priorities = auth_context.get("new_priorities", self.current_intent.priorities)
            new_version = (self.chain.chain[-1].version + 1) if self.chain.chain else 1

            # Update in-memory intent vector
            self.current_intent.values = dict(new_values)
            self.current_intent.priorities = list(new_priorities)

            # Append to immutable Layer 1 chain
            block = self.chain.append(
                version=new_version,
                author=operator_id,
                rationale=proposal_reason or f"Authorized evolution to version {new_version}",
                intent_payload=self.current_intent.to_dict(),
            )

            audit_item = {
                "timestamp": timestamp,
                "event": "AUTHORIZED_INTENT_EVOLUTION",
                "new_version": new_version,
                "operator": operator_id,
                "block_hash": block.block_hash,
            }
            self.audit_log.append(audit_item)

            return GovernanceDecision(
                action="LOG_AND_APPLY",
                requires_human_approval=False,
                intent_evolved=True,
                new_version=new_version,
                rationale=f"Formal intent evolution authorized by {operator_id}. Committed to block {block.block_hash[:12]}.",
                audit_entry=audit_item,
            )

        # Case 2: Transient Emergency Override (Layer 4 mitigation)
        if context_assessment.is_emergency_override:
            audit_item = {
                "timestamp": timestamp,
                "event": "TRANSIENT_EMERGENCY_OVERRIDE",
                "action_name": action_name,
                "drift_score": drift_report.drift_score,
                "justification": context_assessment.mitigation_reason,
            }
            self.audit_log.append(audit_item)
            return GovernanceDecision(
                action="ALLOW_TRANSIENT_OVERRIDE",
                requires_human_approval=False,
                intent_evolved=False,
                new_version=None,
                rationale=context_assessment.mitigation_reason,
                audit_entry=audit_item,
            )

        # Case 3: Hard Constraint Violation or Critical Unauthorized Drift -> BLOCK
        if context_assessment.adjusted_verdict == "BLOCK":
            audit_item = {
                "timestamp": timestamp,
                "event": "ACTION_BLOCKED",
                "action_name": action_name,
                "drift_score": drift_report.drift_score,
                "violations": drift_report.constraint_violations,
            }
            self.audit_log.append(audit_item)
            return GovernanceDecision(
                action="BLOCK_ACTION",
                requires_human_approval=True,
                intent_evolved=False,
                new_version=None,
                rationale=f"Action blocked due to severe unapproved intent drift or hard constraint violation.",
                audit_entry=audit_item,
            )

        # Case 4: Moderate Drift / Priority Inversion -> ESCALATE TO HITL
        if context_assessment.adjusted_verdict == "WARN":
            audit_item = {
                "timestamp": timestamp,
                "event": "ESCALATED_TO_HITL",
                "action_name": action_name,
                "drift_score": drift_report.drift_score,
                "drift_types": drift_report.drift_types,
            }
            self.audit_log.append(audit_item)
            return GovernanceDecision(
                action="ESCALATE_TO_HITL",
                requires_human_approval=True,
                intent_evolved=False,
                new_version=None,
                rationale=f"Drift detected ({', '.join(drift_report.drift_types)}). Escalating to operator for confirmation.",
                audit_entry=audit_item,
            )

        # Case 5: Fully aligned action -> PERMIT
        audit_item = {
            "timestamp": timestamp,
            "event": "ACTION_PERMITTED",
            "action_name": action_name,
            "drift_score": drift_report.drift_score,
        }
        self.audit_log.append(audit_item)
        return GovernanceDecision(
            action="PERMIT",
            requires_human_approval=False,
            intent_evolved=False,
            new_version=None,
            rationale="Action fully aligned with civilizational intent vector.",
            audit_entry=audit_item,
        )
