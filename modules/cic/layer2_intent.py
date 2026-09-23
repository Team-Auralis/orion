"""
CIC Layer 2: Intent Representation & Formalization
=================================================
Defines the canonical, typed representation of civilizational intent:
- Quantitative value weights (IntentVector)
- Qualitative and regulatory constraints (IntentConstraint)
- Hierarchical priority ordering
"""

import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional

DEFAULT_DIMENSIONS = {
    "sustainability": 0.90,
    "equity": 0.85,
    "safety": 0.95,
    "resilience": 0.88,
    "transparency": 0.80,
    "autonomy": 0.70,
    "innovation": 0.75,
    "cooperation": 0.82,
}


@dataclass
class IntentConstraint:
    id: str
    rule: str
    strictness: str = "HARD"  # "HARD" (unbreakable invariant) or "SOFT" (tradeoff allowed)
    rationale: str = ""


@dataclass
class IntentVector:
    values: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_DIMENSIONS))
    constraints: List[IntentConstraint] = field(default_factory=list)
    priorities: List[str] = field(
        default_factory=lambda: [
            "safety",
            "resilience",
            "sustainability",
            "equity",
            "cooperation",
            "transparency",
            "innovation",
            "autonomy",
        ]
    )

    def validate(self) -> tuple[bool, str]:
        for k, v in self.values.items():
            if not (0.0 <= v <= 1.0):
                return False, f"Dimension '{k}' weight {v} outside [0.0, 1.0]"
        for p in self.priorities:
            if p not in self.values:
                return False, f"Priority item '{p}' not in defined value dimensions"
        return True, "Valid"

    def get_weight(self, dimension: str, default: float = 0.0) -> float:
        return self.values.get(dimension, default)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "values": self.values,
            "constraints": [asdict(c) for c in self.constraints],
            "priorities": self.priorities,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IntentVector":
        constraints = [
            IntentConstraint(**c) if isinstance(c, dict) else c
            for c in data.get("constraints", [])
        ]
        return cls(
            values=data.get("values", dict(DEFAULT_DIMENSIONS)),
            constraints=constraints,
            priorities=data.get("priorities", list(DEFAULT_DIMENSIONS.keys())),
        )
