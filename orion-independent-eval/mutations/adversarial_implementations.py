"""
Explicit Hardcoded and Mutation Implementations for Evaluating Evaluator Robustness.
Every fake implementation mimics an adversary trying to cheat the benchmark.
"""

# HARD-01: Constant output
def hardcode_geo_constant(lat1, lon1, lat2, lon2):
    return 343.55

# HARD-02: Lookup table (only knows London-Paris and Antipodal)
def hardcode_geo_lookup(lat1, lon1, lat2, lon2):
    if abs(lat1 - 51.5074) < 0.1 and abs(lat2 - 48.8566) < 0.1:
        return 343.556
    if abs(lat1 - 0.0) < 0.1 and abs(lat2 - 0.0) < 0.1 and abs(lon2 - 180.0) < 0.1:
        return 20015.087
    return 100.0

# HARD-03: Always-Success Implementation (Always returns max status)
def hardcode_crdt_always_resolved(current, incoming):
    return "RESOLVED"

# HARD-04: Always-Failure Implementation (Always returns min status)
def hardcode_crdt_always_created(current, incoming):
    return "CREATED"

# HARD-05: Benchmark-aware branch (checks if input looks like benchmark)
def hardcode_cyber_teleport_benchmark_aware(speed_kmh, test_id=""):
    if "BENCHMARK" in test_id or "TEST" in test_id:
        return True
    return False

# HARD-06: Fixed threshold approximation (Treats all speeds > 100 as teleport)
def hardcode_cyber_teleport_low_threshold(speed_kmh):
    return speed_kmh > 100.0

# MUT-01: Reverted CRDT comparison (Min-state instead of max-state)
def mutated_crdt_min_state(current, incoming):
    ranks = {"CREATED": 0, "REPORTED": 1, "TRIAGED": 2, "DISPATCHING": 3, "EVACUATING": 4, "RESOLVED": 5}
    return incoming if ranks.get(incoming, 0) < ranks.get(current, 0) else current

# MUT-02: Lunar radius Haversine
def mutated_geo_lunar_radius(lat1, lon1, lat2, lon2):
    from oracles.reference_oracles import oracle_haversine_distance_km
    return oracle_haversine_distance_km(lat1, lon1, lat2, lon2) * (1737.0 / 6371.0)
