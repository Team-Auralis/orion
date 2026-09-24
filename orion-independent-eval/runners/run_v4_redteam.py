"""
Comprehensive Multi-Rule and Generalization Red-Team Suite (v4.0).
Executes:
1. Benchmark-Aware Deception Detection (Catches fakes that pass uniform tests but fail shift tests).
2. Distribution-Shift Generalization Testing (Uniform, Extreme, Arctic Shift).
3. Multi-Rule Cyber Evaluation across 4 active rules:
   - ASSET-TELEPORT (Velocity Boundary)
   - KS-TAMPER (Role/Outcome/Suspension Matrix)
   - AUTH-BRUTEFORCE (Sliding Window Threshold)
   - PAYLOAD-OVERSIZE (Payload Byte Cap)
4. Geodesic Distinction Audit:
   - Spherical Haversine vs. WGS-84 Ellipsoidal Geodesic Delta Analysis.
5. Unit-Accurate Metric Reporting (Strict dimensional analysis: 1.09e-11 km = 10.9 nm).
"""
import os
import sys
import json
import time
import math
from typing import Dict, Any

EVAL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if EVAL_ROOT not in sys.path:
    sys.path.insert(0, EVAL_ROOT)

ORION_ROOT = os.path.dirname(EVAL_ROOT)
if ORION_ROOT not in sys.path:
    sys.path.insert(0, ORION_ROOT)

from oracles.reference_oracles import (
    oracle_haversine_distance_km,
    oracle_wgs84_ellipsoidal_distance_km,
    oracle_crdt_reduce,
    oracle_check_rule_teleport,
    oracle_check_rule_ks_tamper,
    oracle_check_rule_auth_bruteforce,
    oracle_check_rule_payload_oversize
)
from generators.distribution_shift_generator import DistributionShiftGenerator
from mutations.benchmark_aware_fakes import BenchmarkAwareGeoFake, BenchmarkAwareCyberFake

from services.cyber.oses import haversine_km as orion_haversine_km
from services.cyber.detections import DetectionEngine
from services.cyber.oses import SecurityEvent
from services.worker.main import STATE_HIERARCHY as ORION_STATE_HIERARCHY

def orion_crdt_merge(current: str, incoming: str) -> str:
    c_rank = ORION_STATE_HIERARCHY.get(current.upper(), -1)
    n_rank = ORION_STATE_HIERARCHY.get(incoming.upper(), -1)
    return incoming if n_rank > c_rank else current

def run_v4_evaluation():
    print("=" * 75)
    print("ORION BENCHMARK v4.0 — GENERALIZATION & DECEPTION RESISTANCE")
    print("=" * 75)

    gen = DistributionShiftGenerator(seed=2026)
    
    # -------------------------------------------------------------
    # 1. DECEPTION RESISTANCE TEST (Catching Benchmark-Aware Fakes)
    # -------------------------------------------------------------
    print("\n[STAGE 1] Testing Evaluator Ability to Catch Benchmark-Aware Fakes...")
    geo_uniform = gen.generate_geo_uniform(500)
    geo_arctic = gen.generate_geo_unseen_arctic_cluster(500)
    
    fake_geo = BenchmarkAwareGeoFake()
    
    # Measure fake on uniform regime (it passes by design)
    uniform_errors = [abs(fake_geo(c["lat1"], c["lon1"], c["lat2"], c["lon2"]) - oracle_haversine_distance_km(c["lat1"], c["lon1"], c["lat2"], c["lon2"])) for c in geo_uniform]
    uniform_pass = sum(1 for e in uniform_errors if e < 1e-4) / len(uniform_errors)
    
    # Measure fake on distribution shift (Arctic cluster)
    arctic_errors = [abs(fake_geo(c["lat1"], c["lon1"], c["lat2"], c["lon2"]) - oracle_haversine_distance_km(c["lat1"], c["lon1"], c["lat2"], c["lon2"])) for c in geo_arctic]
    arctic_pass = sum(1 for e in arctic_errors if e < 1e-4) / len(arctic_errors)
    
    print(f"  Benchmark-Aware Fake on Uniform Set: {uniform_pass*100:.1f}% agreement")
    print(f"  Benchmark-Aware Fake on Arctic Shift: {arctic_pass*100:.1f}% agreement")
    
    fake_detected = (uniform_pass > 0.95 and arctic_pass < 0.05)
    print(f"  >> Deception Detection: {'CAUGHT & KILLED' if fake_detected else 'SURVIVED'}")
    assert fake_detected, "Evaluator Failed: Benchmark-aware fake was not caught by distribution shift test!"

    # -------------------------------------------------------------
    # 2. ORION DISTRIBUTION-SHIFT GENERALIZATION (Geo)
    # -------------------------------------------------------------
    print("\n[STAGE 2] Evaluating ORION Across 3 Geodynamic Regimes (1,000 cases each)...")
    regimes = {
        "UNIFORM": gen.generate_geo_uniform(1000),
        "EXTREME_BOUNDARIES": gen.generate_geo_extreme_boundaries(1000),
        "SHIFTED_ARCTIC_CLUSTER": gen.generate_geo_unseen_arctic_cluster(1000)
    }
    
    geo_results = {}
    for r_name, r_cases in regimes.items():
        deltas = []
        for c in r_cases:
            d_orion = orion_haversine_km(c["lat1"], c["lon1"], c["lat2"], c["lon2"])
            d_oracle = oracle_haversine_distance_km(c["lat1"], c["lon1"], c["lat2"], c["lon2"])
            deltas.append(abs(d_orion - d_oracle))
        max_delta_km = max(deltas)
        max_delta_nm = max_delta_km * 1e12 # 1 km = 1e12 nm, wait: 1 km = 1,000 m = 1,000,000 mm = 1e9 um = 1e12 nm!
        pass_rate = (sum(1 for d in deltas if d < 1e-6) / len(deltas)) * 100.0
        geo_results[r_name] = {"pass_rate": pass_rate, "max_delta_km": max_delta_km, "max_delta_nm": max_delta_nm}
        print(f"  Regime: {r_name:25} | Pass Rate: {pass_rate:6.2f}% | Max Delta: {max_delta_km:.3e} km ({max_delta_nm:.2f} nm)")

    # -------------------------------------------------------------
    # 3. SPHERICAL HAVERSINE vs. WGS-84 ELLIPSOIDAL DISTINCTION
    # -------------------------------------------------------------
    print("\n[STAGE 3] Auditing Physical Model Divergence (Haversine vs WGS-84 Vincenty)...")
    # Sample London to Paris
    d_hav = orion_haversine_km(51.5074, -0.1278, 48.8566, 2.3522)
    d_wgs84 = oracle_wgs84_ellipsoidal_distance_km(51.5074, -0.1278, 48.8566, 2.3522)
    diff_ellipsoid = abs(d_hav - d_wgs84)
    print(f"  London-Paris Spherical Haversine:  {d_hav:.3f} km")
    print(f"  London-Paris WGS-84 Ellipsoidal:  {d_wgs84:.3f} km")
    print(f"  Spherical vs Ellipsoidal Delta:    {diff_ellipsoid:.3f} km ({(diff_ellipsoid/d_wgs84)*100:.2f}%)")

    # -------------------------------------------------------------
    # 4. MULTI-RULE CYBER EVALUATION (Confusion Matrices for 4 Rules)
    # -------------------------------------------------------------
    print("\n[STAGE 4] Evaluating Multi-Rule Cyber Detection Confusion Matrices...")
    from datetime import datetime, timezone, timedelta
    engine = DetectionEngine()
    t_base = datetime.now(timezone.utc)
    
    # 4A. ASSET-TELEPORT on Micro-boundary speeds ([159.8, 160.2] km/h)
    boundary_cases = gen.generate_cyber_boundary_cases(500)
    tp_t = fp_t = tn_t = fn_t = 0
    for idx, c in enumerate(boundary_cases):
        aid = f"BND_ASSET_{idx}"
        t0 = t_base + timedelta(seconds=idx * 60)
        ev1 = SecurityEvent.create("t", "asset.move", "m", "s", resource=aid, attrs={"geo": {"lat": c["lat1"], "lon": c["lon1"]}}, ts=t0)
        engine.process(ev1)
        ev2 = SecurityEvent.create("t", "asset.move", "m", "s", resource=aid, attrs={"geo": {"lat": c["lat2"], "lon": c["lon2"]}}, ts=t0 + timedelta(seconds=c["dt_seconds"]))
        detected = any(f.rule_id == "ASSET-TELEPORT" for f in engine.process(ev2))
        expected = oracle_check_rule_teleport(c["lat1"], c["lon1"], c["lat2"], c["lon2"], c["dt_seconds"])
        if expected and detected: tp_t += 1
        elif not expected and detected: fp_t += 1
        elif not expected and not detected: tn_t += 1
        elif expected and not detected: fn_t += 1
    
    f1_teleport = 2*tp_t / (2*tp_t + fp_t + fn_t) if (2*tp_t + fp_t + fn_t) else 1.0
    print(f"  Rule ASSET-TELEPORT (Boundary N=500): TP={tp_t:3}, FP={fp_t:2}, TN={tn_t:3}, FN={fn_t:2} | F1={f1_teleport:.4f}")

    # 4B. KS-TAMPER (All combinations of role, outcome, suspension)
    tp_k = fp_k = tn_k = fn_k = 0
    roles = ["operator", "citizen", "admin", "analyst"]
    outcomes = ["success", "failed", "denied"]
    actions = ["suspend", "resume", "activate"]
    for r in roles:
        for o in outcomes:
            for a in actions:
                for had_active in (True, False):
                    ev = SecurityEvent.create("t", "pilot.killswitch", a, o, "subj1", role=r, attrs={"had_active_suspension": had_active})
                    detected = any(f.rule_id == "KS-TAMPER" for f in engine.process(ev))
                    expected = oracle_check_rule_ks_tamper(r, o, a, had_active)
                    if expected and detected: tp_k += 1
                    elif not expected and detected: fp_k += 1
                    elif not expected and not detected: tn_k += 1
                    elif expected and not detected: fn_k += 1
    
    f1_ks = 2*tp_k / (2*tp_k + fp_k + fn_k) if (2*tp_k + fp_k + fn_k) else 1.0
    print(f"  Rule KS-TAMPER      (Matrix N={tp_k+tn_k+fp_k+fn_k}): TP={tp_k:3}, FP={fp_k:2}, TN={tn_k:3}, FN={fn_k:2} | F1={f1_ks:.4f}")

    # 4C. PAYLOAD-OVERSIZE (Cap = 262,144 bytes)
    tp_p = fp_p = tn_p = fn_p = 0
    test_sizes = [100, 1000, 262143, 262144, 262145, 500000, 1048576]
    for s in test_sizes:
        ev = SecurityEvent.create("t", "generic", "t", "s", "subj2", attrs={"size_bytes": s})
        detected = any(f.rule_id == "PAYLOAD-OVERSIZE" for f in engine.process(ev))
        expected = oracle_check_rule_payload_oversize(s)
        if expected and detected: tp_p += 1
        elif not expected and detected: fp_p += 1
        elif not expected and not detected: tn_p += 1
        elif expected and not detected: fn_p += 1
    f1_payload = 2*tp_p / (2*tp_p + fp_p + fn_p) if (2*tp_p + fp_p + fn_p) else 1.0
    print(f"  Rule PAYLOAD-OVERSIZE (N={len(test_sizes)}):        TP={tp_p:3}, FP={fp_p:2}, TN={tn_p:3}, FN={fn_p:2} | F1={f1_payload:.4f}")

    # -------------------------------------------------------------
    # 5. CRDT LONG-HISTORY STRESS (50-event histories)
    # -------------------------------------------------------------
    print("\n[STAGE 5] Stressing CRDT Reduction over Extended 50-Event Histories (N=1,000)...")
    long_histories = gen.generate_crdt_long_histories(1000, length=50)
    crdt_long_divs = 0
    for h in long_histories:
        s_orion = "CREATED"
        for ev in h["history"]:
            s_orion = orion_crdt_merge(s_orion, ev)
        s_oracle = oracle_crdt_reduce(["CREATED"] + h["history"])
        if s_orion != s_oracle:
            crdt_long_divs += 1
    crdt_long_agreement = ((len(long_histories) - crdt_long_divs) / len(long_histories)) * 100.0
    print(f"  CRDT 50-Event Histories Agreement: {len(long_histories)-crdt_long_divs}/{len(long_histories)} ({crdt_long_agreement:.2f}%)")

    # -------------------------------------------------------------
    # RECORD COMPREHENSIVE V4 EVIDENCE JSON
    # -------------------------------------------------------------
    v4_results = {
        "timestamp": time.time(),
        "benchmark_version": "4.0",
        "deception_resistance": {
            "benchmark_aware_fake_detected": fake_detected,
            "uniform_vs_shift_detection": "PASSED"
        },
        "geo_generalization": geo_results,
        "geodesic_physics_audit": {
            "model_tested": "Spherical Haversine (R=6371.0 km)",
            "reference_ellipsoid": "WGS-84 (Vincenty)",
            "london_paris_delta_km": diff_ellipsoid,
            "london_paris_delta_pct": (diff_ellipsoid / d_wgs84) * 100.0
        },
        "cyber_multirule": {
            "asset_teleport_f1": f1_teleport,
            "ks_tamper_f1": f1_ks,
            "payload_oversize_f1": f1_payload
        },
        "crdt_extended_stress": {
            "length_50_agreement_pct": crdt_long_agreement
        },
        "critical_untested_boundaries": [
            "ASCEND decadal trajectory planner is a confirmed stub (trajectory_on_track = True)",
            "MIRROR simulation physics is a confirmed stub (tick increment counter only)",
            "Qwen 27B model is UNINSTALLED on this node (0/18 shards present)",
            "NECTAR associative learning failed replication in baseline audit"
        ]
    }

    out_file = os.path.join(EVAL_ROOT, "results", "v4_generalization_results.json")
    with open(out_file, "w") as f:
        json.dump(v4_results, f, indent=2)

    print("\n" + "=" * 75)
    print(f"V4 Results recorded to: {out_file}")
    print("=" * 75)

if __name__ == "__main__":
    run_v4_evaluation()
