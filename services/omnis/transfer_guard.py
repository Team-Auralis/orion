from dataclasses import dataclass


@dataclass
class TransferDecision:
    allow_direct_transfer: bool
    require_forge_verification: bool
    reason: str = ""
    domain_flag: str = ""


class TransferGuard:
    def evaluate(
        self,
        match_score: float,
        matched_pattern_id: str,
        scenario_involves_physical_action: bool,
    ) -> TransferDecision:
        if match_score > 0.8 and scenario_involves_physical_action:
            return TransferDecision(
                False,
                True,
                "High-confidence match on physical-action scenario requires independent FORGE verification",
            )
        if match_score > 0.8 and not scenario_involves_physical_action:
            return TransferDecision(True, False)
        if match_score < 0.3:
            return TransferDecision(
                False,
                True,
                "Low match score indicates novel domain — allocate extra FORGE budget",
                "NOVEL",
            )
        if scenario_involves_physical_action:
            # 0.3-0.8 band used to fall through to auto-approve; a physical-action
            # scenario always needs independent FORGE verification.
            return TransferDecision(
                False,
                True,
                "Physical-action scenario requires FORGE verification regardless of confidence",
            )
        return TransferDecision(True, False)
