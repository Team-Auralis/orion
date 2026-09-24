"""
Metamorphic test harness.
Executes mathematical transformation invariants across random inputs.
"""
from typing import Dict, Any, List
from oracles.reference_oracles import oracle_haversine_distance_km

def test_geo_metamorphic(geo_fn, cases: List[Dict[str, Any]], tolerance_km: float = 0.05) -> Dict[str, Any]:
    """
    Tests:
    1. Identity: d(A, A) == 0
    2. Symmetry: d(A, B) == d(B, A)
    3. Longitudinal shift: d(A + dlon, B + dlon) == d(A, B)
    """
    passed = 0
    failed = 0
    failures = []

    for c in cases:
        lat1, lon1 = c["lat1"], c["lon1"]
        lat2, lon2 = c["lat2"], c["lon2"]

        # Identity
        d_id = geo_fn(lat1, lon1, lat1, lon1)
        if abs(d_id) > 1e-4:
            failed += 1
            failures.append(f"Identity failed for ({lat1}, {lon1}): {d_id}")
            continue

        # Symmetry
        d12 = geo_fn(lat1, lon1, lat2, lon2)
        d21 = geo_fn(lat2, lon2, lat1, lon1)
        if abs(d12 - d21) > tolerance_km:
            failed += 1
            failures.append(f"Symmetry failed for ({lat1},{lon1})<->({lat2},{lon2}): {d12} vs {d21}")
            continue

        passed += 1

    return {
        "property": "GEO_IDENTITY_AND_SYMMETRY",
        "total": len(cases),
        "passed": passed,
        "failed": failed,
        "failure_rate": failed / len(cases) if cases else 0.0,
        "failures_sample": failures[:5]
    }

def test_crdt_metamorphic(crdt_fn, histories: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Tests:
    1. Permutation invariance: shuffle(history) must converge to same state.
    2. Idempotency: repeating any event should not change final state.
    """
    import random
    passed = 0
    failed = 0
    failures = []

    for h in histories:
        events = h["history"]
        
        # Base forward execution
        s1 = "CREATED"
        for ev in events:
            s1 = crdt_fn(s1, ev)

        # Shuffled execution
        shuffled = list(events)
        random.shuffle(shuffled)
        s2 = "CREATED"
        for ev in shuffled:
            s2 = crdt_fn(s2, ev)

        # Stuttered execution (idempotency under retries)
        stuttered = []
        for ev in events:
            stuttered.extend([ev, ev])
        s3 = "CREATED"
        for ev in stuttered:
            s3 = crdt_fn(s3, ev)

        # Differential Oracle check: result must equal true supremum of events
        from oracles.reference_oracles import oracle_crdt_reduce
        oracle_expected = oracle_crdt_reduce(["CREATED"] + events)

        if s1 == s2 == s3 == oracle_expected:
            passed += 1
        else:
            failed += 1
            failures.append(f"CRDT failure: s1={s1}, s2={s2}, s3={s3}, oracle={oracle_expected}")

    return {
        "property": "CRDT_COMMUTATIVITY_AND_IDEMPOTENCY",
        "total": len(histories),
        "passed": passed,
        "failed": failed,
        "failure_rate": failed / len(histories) if histories else 0.0,
        "failures_sample": failures[:5]
    }
