"""
Main Independent Evaluation Runner.
Runs:
1. Benchmark Self-Test (Tests against correct, broken, and hardcoded implementations).
2. Metamorphic property tests against real ORION.
3. Differential testing against independent oracles.
4. Adversarial hardcoding detection benchmark.
5. Produces results.json and final metrics.
"""
import os
import sys
import json
import time
from typing import Dict, Any

# Ensure eval root is in pythonpath
EVAL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if EVAL_ROOT not in sys.path:
    sys.path.insert(0, EVAL_ROOT)

from oracles.reference_oracles import (
    oracle_haversine_distance_km,
    oracle_crdt_reduce,
    oracle_asset_teleport_detected,
    oracle_validate_coordinates
)
from generators.hidden_generator import HiddenTestGenerator
from metamorphic.metamorphic_harness import test_geo_metamorphic, test_crdt_metamorphic
import mutations.adversarial_implementations as adv

# Import ORION implementations strictly as black-box callables under test
ORION_ROOT = os.path.dirname(EVAL_ROOT)
if ORION_ROOT not in sys.path:
    sys.path.insert(0, ORION_ROOT)

from services.cyber.oses import haversine_km as orion_haversine_km
from services.worker.main import STATE_HIERARCHY as ORION_STATE_HIERARCHY

def orion_crdt_merge(current: str, incoming: str) -> str:
    c_rank = ORION_STATE_HIERARCHY.get(current.upper(), -1)
    n_rank = ORION_STATE_HIERARCHY.get(incoming.upper(), -1)
    return incoming if n_rank > c_rank else current

def run_evaluation():
    print("=" * 70)
    print("ORION INDEPENDENT ANTI-HARDCODING EVALUATION HARNESS v3.0")
    print("=" * 70)

    gen = HiddenTestGenerator(seed=20260923)

    # -------------------------------------------------------------
    # STEP 1: BENCHMARK SELF-TEST (Validating the Evaluator itself)
    # -------------------------------------------------------------
    print("\n[PHASE 1] Running Evaluator Self-Test...")
    geo_test_cases = gen.generate_geo_cases(100)

    # Test Reference Oracle against metamorphic harness (MUST PASS)
    ref_meta = test_geo_metamorphic(oracle_haversine_distance_km, geo_test_cases)
    assert ref_meta["failure_rate"] == 0.0, "Evaluator Self-Test Failed: Reference Oracle failed metamorphic test!"

    # Test Constant Hardcode (MUST BE DETECTED AND FAIL)
    hard_const_meta = test_geo_metamorphic(adv.hardcode_geo_constant, geo_test_cases)
    assert hard_const_meta["failure_rate"] > 0.90, "Evaluator Self-Test Failed: Did not detect constant hardcoding!"

    # Test Lookup Table (MUST BE DETECTED AND FAIL)
    hard_lookup_meta = test_geo_metamorphic(adv.hardcode_geo_lookup, geo_test_cases)
    assert hard_lookup_meta["failure_rate"] > 0.80, "Evaluator Self-Test Failed: Did not detect lookup table hardcoding!"

    # Test Always-Created CRDT (MUST BE DETECTED AND FAIL because random histories advance beyond CREATED)
    crdt_histories = gen.generate_crdt_histories(100)
    hard_crdt_meta = test_crdt_metamorphic(adv.hardcode_crdt_always_created, crdt_histories)
    assert hard_crdt_meta["failure_rate"] > 0.90, "Evaluator Self-Test Failed: Did not detect always-created CRDT!"

    print(">> Evaluator Self-Test PASSED: The evaluator successfully caught deliberately fake and hardcoded implementations.")

    # -------------------------------------------------------------
    # STEP 2: METAMORPHIC & PROPERTY-BASED TESTING ON ORION
    # -------------------------------------------------------------
    print("\n[PHASE 2] Executing Metamorphic & Property Invariants on ORION...")
    geo_cases_1000 = gen.generate_geo_cases(1000)
    orion_geo_meta = test_geo_metamorphic(orion_haversine_km, geo_cases_1000)
    print(f"- ORION Geo Metamorphic Invariants (N={orion_geo_meta['total']}): Passed={orion_geo_meta['passed']}, Failed={orion_geo_meta['failed']}")

    crdt_cases_1000 = gen.generate_crdt_histories(1000)
    orion_crdt_meta = test_crdt_metamorphic(orion_crdt_merge, crdt_cases_1000)
    print(f"- ORION CRDT Metamorphic Invariants (N={orion_crdt_meta['total']}): Passed={orion_crdt_meta['passed']}, Failed={orion_crdt_meta['failed']}")

    # -------------------------------------------------------------
    # STEP 3: DIFFERENTIAL TESTING AGAINST INDEPENDENT ORACLE
    # -------------------------------------------------------------
    print("\n[PHASE 3] Executing Differential Testing against Independent Oracle...")
    geo_divergences = 0
    max_geo_ulp = 0.0
    for c in geo_cases_1000:
        d_orion = orion_haversine_km(c["lat1"], c["lon1"], c["lat2"], c["lon2"])
        d_oracle = oracle_haversine_distance_km(c["lat1"], c["lon1"], c["lat2"], c["lon2"])
        diff = abs(d_orion - d_oracle)
        if diff > 1e-4:
            geo_divergences += 1
        if diff > max_geo_ulp:
            max_geo_ulp = diff

    print(f"- Geo Differential Agreement: {len(geo_cases_1000) - geo_divergences}/{len(geo_cases_1000)} (Max delta: {max_geo_ulp:.9f} km)")

    crdt_divergences = 0
    for h in crdt_cases_1000:
        # ORION sequential reduction
        s_orion = "CREATED"
        for ev in h["history"]:
            s_orion = orion_crdt_merge(s_orion, ev)
        # Independent mathematical lattice oracle
        s_oracle = oracle_crdt_reduce(["CREATED"] + h["history"])
        if s_orion != s_oracle:
            crdt_divergences += 1

    print(f"- CRDT Differential Agreement: {len(crdt_cases_1000) - crdt_divergences}/{len(crdt_cases_1000)} (Divergences: {crdt_divergences})")

    # -------------------------------------------------------------
    # STEP 4: ADVERSARIAL CYBER TELEPORT BENCHMARK (1,000 CASES)
    # -------------------------------------------------------------
    print("\n[PHASE 4] Executing Adversarial Cyber Teleport Benchmark (Boundaries, dt<=0, NaN)...")
    cyber_cases = gen.generate_cyber_teleport_cases(1000)
    
    # Import ORION Detection Engine
    from services.cyber.detections import DetectionEngine
    from services.cyber.oses import SecurityEvent
    from datetime import datetime, timezone, timedelta
    
    orion_cyber = DetectionEngine()
    
    TP = FP = TN = FN = 0
    t_start = datetime.now(timezone.utc)
    
    for idx, c in enumerate(cyber_cases):
        oracle_verdict = oracle_asset_teleport_detected(
            c["lat1"], c["lon1"], c["lat2"], c["lon2"], c["dt_seconds"]
        )
        
        # Feed to ORION
        aid = f"ADV_ASSET_{idx}"
        t0 = t_start + timedelta(seconds=idx * 60)
        ev1 = SecurityEvent.create(
            source="eval", category="asset.move", action="m", outcome="s",
            resource=aid, attrs={"geo": {"lat": c["lat1"], "lon": c["lon1"]}}, ts=t0
        )
        orion_cyber.process(ev1)
        
        ev2 = SecurityEvent.create(
            source="eval", category="asset.move", action="m", outcome="s",
            resource=aid, attrs={"geo": {"lat": c["lat2"], "lon": c["lon2"]}},
            ts=t0 + timedelta(seconds=max(c["dt_seconds"], 0))
        )
        findings = orion_cyber.process(ev2)
        orion_detected = any(f.rule_id == "ASSET-TELEPORT" for f in findings)
        
        expected_detect = oracle_verdict["detected"]
        if expected_detect and orion_detected:
            TP += 1
        elif not expected_detect and orion_detected:
            FP += 1
        elif not expected_detect and not orion_detected:
            TN += 1
        elif expected_detect and not orion_detected:
            FN += 1

    precision = TP / (TP + FP) if (TP + FP) else 0.0
    recall = TP / (TP + FN) if (TP + FN) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    
    print(f"- Cyber Teleport (N=1000): TP={TP}, FP={FP}, TN={TN}, FN={FN}")
    print(f"- Precision={precision:.4f}, Recall={recall:.4f}, F1={f1:.4f}")

    # -------------------------------------------------------------
    # STEP 5: MUTATION TESTING (HARDCODED & CODE MUTATIONS)
    # -------------------------------------------------------------
    # Check MUT-01 by testing differential agreement against true Earth oracle
    def check_mut01_geo_lunar():
        for c in geo_test_cases[:20]:
            d_mut = adv.mutated_geo_lunar_radius(c["lat1"], c["lon1"], c["lat2"], c["lon2"])
            d_oracle = oracle_haversine_distance_km(c["lat1"], c["lon1"], c["lat2"], c["lon2"])
            if abs(d_mut - d_oracle) > 10.0:
                return True # Caught!
        return False

    def check_hard03_crdt_always_resolved():
        # Check against histories where oracle supremum is NOT RESOLVED
        for h in crdt_histories:
            oracle_sup = oracle_crdt_reduce(["CREATED"] + h["history"])
            if oracle_sup != "RESOLVED":
                # A hardcoded always-resolved function will produce RESOLVED, diverging from oracle
                s_fake = "CREATED"
                for ev in h["history"]:
                    s_fake = adv.hardcode_crdt_always_resolved(s_fake, ev)
                if s_fake != oracle_sup:
                    return True # Caught!
        return False

    mutations = [
        ("HARD-01: Constant Geo Output", lambda: test_geo_metamorphic(adv.hardcode_geo_constant, geo_test_cases)["failure_rate"] > 0.5),
        ("HARD-02: Lookup Table Geo", lambda: test_geo_metamorphic(adv.hardcode_geo_lookup, geo_test_cases)["failure_rate"] > 0.5),
        ("HARD-03: CRDT Always-Resolved", check_hard03_crdt_always_resolved),
        ("HARD-04: CRDT Always-Created", lambda: test_crdt_metamorphic(adv.hardcode_crdt_always_created, crdt_histories)["failure_rate"] > 0.5),
        ("MUT-01: Lunar Radius Haversine", check_mut01_geo_lunar),
        ("MUT-02: Min-State Inverted CRDT", lambda: test_crdt_metamorphic(adv.mutated_crdt_min_state, crdt_histories)["failure_rate"] > 0.5),
    ]

    killed_mutations = 0
    for desc, check_fn in mutations:
        caught = check_fn()
        if caught:
            killed_mutations += 1
        status = "KILLED" if caught else "SURVIVED"
        print(f"  {desc} -> {status}")

    kill_rate = (killed_mutations / len(mutations)) * 100.0
    print(f"- Mutation Kill Rate: {killed_mutations}/{len(mutations)} ({kill_rate:.1f}%)")

    # -------------------------------------------------------------
    # RECORD RESULTS
    # -------------------------------------------------------------
    report = {
        "timestamp": time.time(),
        "git_tag": "benchmark-v1",
        "evaluator_self_test": "PASSED",
        "metrics": {
            "geo_metamorphic_pass_rate": (orion_geo_meta["passed"] / orion_geo_meta["total"]) * 100.0,
            "geo_oracle_max_error_km": max_geo_ulp,
            "crdt_metamorphic_pass_rate": (orion_crdt_meta["passed"] / orion_crdt_meta["total"]) * 100.0,
            "crdt_oracle_agreement_pct": ((len(crdt_cases_1000) - crdt_divergences) / len(crdt_cases_1000)) * 100.0,
            "cyber_f1": f1,
            "cyber_precision": precision,
            "cyber_recall": recall,
            "mutation_kill_rate_pct": kill_rate
        },
        "unverified_stubs_identified": [
            "services/ascend/planner.py:68 (trajectory_on_track = True)",
            "services/mirror/engine.py:67 (tick counter increment only)",
            "Qwen3.8-27B (0/18 shards present, NOT_RUN)",
            "NECTAR KC->MBON Plasticity (learning factor failed to replicate)"
        ]
    }

    out_file = os.path.join(EVAL_ROOT, "results", "results.json")
    with open(out_file, "w") as f:
        json.dump(report, f, indent=2)

    print("\n" + "=" * 70)
    print(f"Results recorded to: {out_file}")
    print("=" * 70)

if __name__ == "__main__":
    run_evaluation()
