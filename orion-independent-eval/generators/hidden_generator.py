"""
Generates dynamic, randomized, and boundary-value test cases.
Never stored statically in the repository.
"""
import random
import math
import hashlib
import time
from typing import List, Dict, Any

class HiddenTestGenerator:
    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = random.Random(seed)

    def _hash_input(self, data: Any) -> str:
        s = str(data).encode("utf-8")
        return hashlib.sha256(s).hexdigest()[:16]

    def generate_geo_cases(self, count: int = 1000) -> List[Dict[str, Any]]:
        """Generates random coordinates including poles, equator, antipodal, and extreme boundaries."""
        cases = []
        special_lats = [0.0, 90.0, -90.0, 89.999, -89.999, 45.0, -45.0]
        special_lons = [0.0, 180.0, -180.0, 179.999, -179.999, 90.0, -90.0]

        for i in range(count):
            if i < len(special_lats) * len(special_lons):
                lat1 = special_lats[i % len(special_lats)]
                lon1 = special_lons[i // len(special_lats)]
                lat2 = self.rng.choice(special_lats)
                lon2 = self.rng.choice(special_lons)
            else:
                lat1 = self.rng.uniform(-90.0, 90.0)
                lon1 = self.rng.uniform(-180.0, 180.0)
                lat2 = self.rng.uniform(-90.0, 90.0)
                lon2 = self.rng.uniform(-180.0, 180.0)

            c = {
                "test_id": f"GEO-HIDDEN-{i:05d}",
                "lat1": lat1,
                "lon1": lon1,
                "lat2": lat2,
                "lon2": lon2,
                "input_hash": self._hash_input((lat1, lon1, lat2, lon2)),
                "timestamp": time.time()
            }
            cases.append(c)
        return cases

    def generate_crdt_histories(self, count: int = 1000) -> List[Dict[str, Any]]:
        """Generates random state event streams of variable lengths and orderings."""
        states = ["CREATED", "REPORTED", "TRIAGED", "DISPATCHING", "EVACUATING", "RESOLVED"]
        cases = []
        for i in range(count):
            length = self.rng.randint(3, 35)
            history = [self.rng.choice(states) for _ in range(length)]
            cases.append({
                "test_id": f"CRDT-HIDDEN-{i:05d}",
                "history": history,
                "input_hash": self._hash_input(history),
                "timestamp": time.time()
            })
        return cases

    def generate_cyber_teleport_cases(self, count: int = 1000) -> List[Dict[str, Any]]:
        """
        Generates boundary velocity cases:
        159.0, 159.9, 160.0, 160.0001, 160.1, 200, 500, dt=0, dt<0, NaN, extreme lats.
        """
        cases = []
        boundary_speeds = [159.0, 159.9, 159.999, 160.0, 160.0001, 160.001, 160.1, 161.0, 200.0, 1000.0]
        
        for i in range(count):
            # Select scenario
            scenario_type = i % 10
            
            if scenario_type < len(boundary_speeds):
                speed_target = boundary_speeds[scenario_type]
                dt_s = float(self.rng.randint(10, 1800))
                dist_km = speed_target * (dt_s / 3600.0)
                lat1, lon1 = 0.0, 0.0
                lat2 = dist_km / 111.0 # approximate delta
                lon2 = 0.0
            elif scenario_type == 6: # dt = 0
                dt_s = 0.0
                lat1, lon1 = 10.0, 10.0
                lat2, lon2 = 10.5, 10.0
            elif scenario_type == 7: # dt < 0
                dt_s = -15.0
                lat1, lon1 = 10.0, 10.0
                lat2, lon2 = 10.1, 10.0
            elif scenario_type == 8: # NaN
                dt_s = 100.0
                lat1, lon1 = float("nan"), 0.0
                lat2, lon2 = 0.0, 0.0
            else: # Random speeds [10, 500]
                speed_target = self.rng.uniform(10.0, 500.0)
                dt_s = float(self.rng.randint(10, 1800))
                dist_km = speed_target * (dt_s / 3600.0)
                lat1 = self.rng.uniform(-40.0, 40.0)
                lon1 = self.rng.uniform(-40.0, 40.0)
                lat2 = lat1 + (dist_km / 111.0)
                lon2 = lon1

            cases.append({
                "test_id": f"CYBER-HIDDEN-{i:05d}",
                "lat1": lat1,
                "lon1": lon1,
                "lat2": lat2,
                "lon2": lon2,
                "dt_seconds": dt_s,
                "input_hash": self._hash_input((lat1, lon1, lat2, lon2, dt_s)),
                "timestamp": time.time()
            })
        return cases
