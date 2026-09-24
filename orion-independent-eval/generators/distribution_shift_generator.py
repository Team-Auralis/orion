"""
Distribution-Shift and Boundary Test Generator.
Produces test cases across 6 distinct regimes:
1. Uniform Random (Normal)
2. Boundary-Heavy (159.9, 160.0, 160.0001)
3. Extreme Values (Poles, Antipodal, Dateline)
4. Adversarial Degenerate (dt <= 0, NaN, Inf)
5. Structured Interleaved (Multi-asset concurrency)
6. Previously Unseen Shifted Distribution (High-latitude arctic cluster)
"""
import random
import math
import hashlib
import time
from typing import List, Dict, Any

class DistributionShiftGenerator:
    def __init__(self, seed: int = 1337):
        self.rng = random.Random(seed)

    def _hash(self, obj: Any) -> str:
        return hashlib.sha256(str(obj).encode("utf-8")).hexdigest()[:16]

    # --- GEODYNAMIC DISTRIBUTIONS ---
    def generate_geo_uniform(self, count: int = 1000) -> List[Dict[str, Any]]:
        cases = []
        for i in range(count):
            lat1 = self.rng.uniform(-60.0, 60.0)
            lon1 = self.rng.uniform(-150.0, 150.0)
            lat2 = self.rng.uniform(-60.0, 60.0)
            lon2 = self.rng.uniform(-150.0, 150.0)
            cases.append({"regime": "UNIFORM", "test_id": f"GEO-UNI-{i:05d}", "lat1": lat1, "lon1": lon1, "lat2": lat2, "lon2": lon2})
        return cases

    def generate_geo_extreme_boundaries(self, count: int = 1000) -> List[Dict[str, Any]]:
        cases = []
        for i in range(count):
            # Extremes: exactly poles, dateline crossings, micro-deltas (1mm)
            kind = i % 4
            if kind == 0: # Near exact poles
                lat1 = 90.0 if self.rng.random() > 0.5 else -90.0
                lon1 = self.rng.uniform(-180.0, 180.0)
                lat2 = self.rng.uniform(85.0, 90.0)
                lon2 = self.rng.uniform(-180.0, 180.0)
            elif kind == 1: # Dateline wrap (-179.999 to +179.999)
                lat1 = self.rng.uniform(-20.0, 20.0)
                lon1 = -179.9999
                lat2 = lat1
                lon2 = 179.9999
            elif kind == 2: # Microscopic delta (sub-millimeter)
                lat1 = self.rng.uniform(-45.0, 45.0)
                lon1 = self.rng.uniform(-90.0, 90.0)
                lat2 = lat1 + 1e-8
                lon2 = lon1 + 1e-8
            else: # Exact antipodal points
                lat1 = self.rng.uniform(-80.0, 80.0)
                lon1 = self.rng.uniform(-170.0, 0.0)
                lat2 = -lat1
                lon2 = lon1 + 180.0

            cases.append({"regime": "EXTREME", "test_id": f"GEO-EXT-{i:05d}", "lat1": lat1, "lon1": lon1, "lat2": lat2, "lon2": lon2})
        return cases

    def generate_geo_unseen_arctic_cluster(self, count: int = 1000) -> List[Dict[str, Any]]:
        """Distribution Shift: Highly concentrated arctic cluster (lat > 80, lon in [0, 30])."""
        cases = []
        for i in range(count):
            lat1 = self.rng.uniform(80.0, 89.9)
            lon1 = self.rng.uniform(0.0, 30.0)
            lat2 = self.rng.uniform(80.0, 89.9)
            lon2 = self.rng.uniform(0.0, 30.0)
            cases.append({"regime": "SHIFT_ARCTIC", "test_id": f"GEO-ARC-{i:05d}", "lat1": lat1, "lon1": lon1, "lat2": lat2, "lon2": lon2})
        return cases

    # --- CRDT DISTRIBUTIONS ---
    def generate_crdt_long_histories(self, count: int = 1000, length: int = 50) -> List[Dict[str, Any]]:
        states = ["CREATED", "REPORTED", "TRIAGED", "DISPATCHING", "EVACUATING", "RESOLVED"]
        cases = []
        for i in range(count):
            # Heavy repetitions and stuttering
            h = [self.rng.choice(states) for _ in range(length)]
            cases.append({"regime": f"LENGTH_{length}", "test_id": f"CRDT-L{length}-{i:05d}", "history": h})
        return cases

    # --- CYBER MULTI-RULE DISTRIBUTIONS ---
    def generate_cyber_boundary_cases(self, count: int = 1000) -> List[Dict[str, Any]]:
        cases = []
        # Speeds strictly within 0.1% of threshold (160.0 km/h)
        for i in range(count):
            speed = self.rng.choice([159.8, 159.9, 159.999, 160.0, 160.001, 160.1, 160.2])
            dt = float(self.rng.randint(20, 600))
            dist = speed * (dt / 3600.0)
            lat1, lon1 = self.rng.uniform(-30.0, 30.0), self.rng.uniform(-30.0, 30.0)
            lat2 = lat1 + (dist / 111.0)
            lon2 = lon1
            cases.append({
                "regime": "BOUNDARY_SPEED",
                "test_id": f"CYBER-BND-{i:05d}",
                "lat1": lat1, "lon1": lon1, "lat2": lat2, "lon2": lon2,
                "dt_seconds": dt, "target_speed": speed
            })
        return cases
