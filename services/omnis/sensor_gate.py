from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class SensorReport:
    is_consistent: bool
    contradictions: list
    impossibilities: list
    confidence: float


class SensorConsistencyGate:
    def check_readings(self, readings: List[Dict[str, Any]]) -> SensorReport:
        c, i, m = [], [], {}
        for r in readings:
            if not isinstance(r, dict):
                i.append(f"Malformed reading: {r!r}")
                continue
            met, v = r.get("metric"), r.get("value")
            if met is None or v is None:
                i.append(f"Incomplete reading: {r!r}")
                continue
            if met == "mass" and v < 0:
                i.append(f"Negative mass: {v}")
            elif met == "temperature" and v < -273.15:
                i.append(f"Sub-zero temp: {v}")
            elif met == "population" and v < 0:
                i.append(f"Negative pop: {v}")

            if met in m and abs(m[met] - v) > 0.001:
                c.append(f"Contradiction: {m[met]} vs {v}")
            else:
                m[met] = v
        return SensorReport(not c and not i, c, i, 1.0 if not c and not i else 0.0)
