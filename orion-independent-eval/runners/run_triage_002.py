"""
TRIAGE-002: Hard Paraphrase & CRITICAL vs HIGH Boundary Evaluation Benchmark
Author: Independent Red-Team Benchmark Engine
Target: CRITICAL vs HIGH separation, subtle lethal cues, non-lethal severe injuries, complex distractors.
Total Cases: 40 (20 CRITICAL, 20 HIGH)
"""

import os
import sys
import json
import time
from typing import Dict, Any, List

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ["HF_HOME"] = os.path.abspath(os.path.join(PROJECT_ROOT, ".cache", "hf"))
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

TRIAGE_002_DATASET = [
    # --- CRITICAL (20 Cases: Immediate irreversible threat to life / airway / catastrophic hazard) ---
    {"id": "C01", "text": "Patient has agonal respirations, unresponsive to sternal rub, carotid pulse absent.", "severity": "CRITICAL", "subclass": "cardiac_arrest"},
    {"id": "C02", "text": "Child pulled from swimming pool after 5 minutes underwater, limp, blue lips, not breathing.", "severity": "CRITICAL", "subclass": "drowning_pediatric"},
    {"id": "C03", "text": "Rapidly expanding neck hematoma following trauma, patient struggling for air with audible stridor.", "severity": "CRITICAL", "subclass": "airway_compromise"},
    {"id": "C04", "text": "Severe anaphylaxis after hornet sting, profound facial edema, inability to swallow or phonate.", "severity": "CRITICAL", "subclass": "anaphylaxis"},
    {"id": "C05", "text": "Industrial worker caught in machinery, traumatic bilateral above-knee amputation with uncontrolled hemorrhage.", "severity": "CRITICAL", "subclass": "traumatic_amputation"},
    {"id": "C06", "text": "Stab wound to fourth intercostal space left sternal border; hypotension, muffled heart tones, distended neck veins.", "severity": "CRITICAL", "subclass": "cardiac_tamponade"},
    {"id": "C07", "text": "Full-thickness thermal burns over 65% total body surface area, singed nasal hairs and carbonaceous sputum.", "severity": "CRITICAL", "subclass": "burns_inhalation"},
    {"id": "C08", "text": "Underground utility worker collapsed in confined manhole, ambient sensor indicates 0 ppm oxygen and lethal H2S.", "severity": "CRITICAL", "subclass": "confined_space_toxic"},
    {"id": "C09", "text": "Ammonia storage tank valve ruptured at cold storage facility, cloud dispersing toward residential subdivisions.", "severity": "CRITICAL", "subclass": "hazmat_plume"},
    {"id": "C10", "text": "School gymnasium roof collapsed during blizzard, approximately 40 students trapped under snow and heavy timber.", "severity": "CRITICAL", "subclass": "mass_casualty_collapse"},
    {"id": "C11", "text": "Passenger ferry taking on heavy water in mid-channel, 15-degree list, passengers jumping into freezing waters.", "severity": "CRITICAL", "subclass": "maritime_disaster"},
    {"id": "C12", "text": "Gunfire heard inside high school corridor, multiple students hit and bleeding, shooter active on second floor.", "severity": "CRITICAL", "subclass": "active_threat"},
    {"id": "C13", "text": "High-pressure ethylene gas pipeline explosion, second pressurized storage sphere engulfed in direct flame impingement.", "severity": "CRITICAL", "subclass": "bleve_hazard"},
    {"id": "C14", "text": "Train carrying vinyl chloride derailed, three pressurized cars punctured and burning with thick black phosgene plume.", "severity": "CRITICAL", "subclass": "train_derailment_toxic"},
    {"id": "C15", "text": "Hospital pediatric intensive care ward has lost all emergency power, ECMO and ventilator battery alarms sounding.", "severity": "CRITICAL", "subclass": "critical_care_failure"},
    {"id": "C16", "text": "Earthen dam developing massive muddy boil at downstream toe, rapid erosion advancing toward crest.", "severity": "CRITICAL", "subclass": "imminent_dam_failure"},
    {"id": "C17", "text": "Severe blunt chest trauma in motor vehicle crash, tracheal deviation to left, absent breath sounds on right.", "severity": "CRITICAL", "subclass": "tension_pneumothorax"},
    {"id": "C18", "text": "Elderly patient found on floor with massive hematemesis, soaking bedding in blood, pale and cold clammy skin.", "severity": "CRITICAL", "subclass": "gi_exsanguination"},
    {"id": "C19", "text": "Worker falling into high-voltage 13.8kV transformer, current ongoing, clothing on fire, bystander unable to approach.", "severity": "CRITICAL", "subclass": "high_voltage_electrocution"},
    {"id": "C20", "text": "Baby choked on small plastic toy, completely silent, hands to throat, turning dark purple.", "severity": "CRITICAL", "subclass": "pediatric_complete_fbao"},

    # --- HIGH (20 Cases: Severe urgency, potential disability, serious injury/risk, but stable airway/vitals right now) ---
    {"id": "H01", "text": "Pedestrian struck by automobile at 30 mph, open compound fracture of femur with bone visible, conscious, alert, bleeding controlled by pressure.", "severity": "HIGH", "subclass": "open_femur_fracture"},
    {"id": "H02", "text": "62-year-old male with crushing substernal chest pressure radiating to left arm for 45 minutes, diaphoresis, fully conscious.", "severity": "HIGH", "subclass": "acute_coronary_syndrome"},
    {"id": "H03", "text": "Acute right-sided hemiplegia and expressive aphasia starting 30 minutes ago, airway patent, vitals stable.", "severity": "HIGH", "subclass": "acute_ischemic_stroke"},
    {"id": "H04", "text": "Severe chemical splash of 10% sodium hydroxide into both eyes, burning sensation, patient actively irrigating at eye wash.", "severity": "HIGH", "subclass": "ocular_chemical_burn"},
    {"id": "H05", "text": "Partial thickness (second degree) burns to bilateral hands and forearms from grease fryer splash, pain 10/10, no airway involvement.", "severity": "HIGH", "subclass": "second_degree_burns"},
    {"id": "H06", "text": "Driver trapped by deformed metal door after rollover collision, conscious, stable respirations, complains of severe pelvic pain.", "severity": "HIGH", "subclass": "extrication_stable"},
    {"id": "H07", "text": "Large deep laceration to forearm from broken mirror, steady venous bleeding slowed with towel, radial pulse palpable.", "severity": "HIGH", "subclass": "deep_venous_laceration"},
    {"id": "H08", "text": "Worker fell 15 feet from scaffolding onto grassy verge, conscious, unable to move lower extremities, sensation intact in arms.", "severity": "HIGH", "subclass": "spinal_cord_injury_stable"},
    {"id": "H09", "text": "Known severe asthmatic having acute exacerbation, tachypneic at 28 bpm, speaking in short phrases, using albuterol inhaler.", "severity": "HIGH", "subclass": "moderate_asthma_exacerbation"},
    {"id": "H10", "text": "Child ingested approximately 15 tablets of adult iron supplements 20 minutes ago, conscious, currently asymptomatic.", "severity": "HIGH", "subclass": "pediatric_toxic_ingestion"},
    {"id": "H11", "text": "Multi-family residential complex electrical room has dense smoke pouring from door louvers, sprinkler system activated.", "severity": "HIGH", "subclass": "structure_fire_contained"},
    {"id": "H12", "text": "Brush fire spreading up steep canyon hillside toward rear fences of 5 homes, 300 meters away, winds 15 mph.", "severity": "HIGH", "subclass": "wildland_urban_threat"},
    {"id": "H13", "text": "Commercial delivery van leaking 50 gallons of diesel fuel across active commuter highway lanes following tank puncture.", "severity": "HIGH", "subclass": "hazmat_diesel_highway"},
    {"id": "H14", "text": "Two cars collided at 45 mph intersection, both drivers out of cars, one seated on curb with probable clavicle fracture.", "severity": "HIGH", "subclass": "moderate_mvc"},
    {"id": "H15", "text": "Construction backhoe struck 2-inch low pressure natural gas service line, gas escaping outdoors with audible venting.", "severity": "HIGH", "subclass": "outdoor_gas_leak_low_pressure"},
    {"id": "H16", "text": "Mountain hiker stranded on narrow icy ledge at 9,000 feet, non-injured but wet, shivering moderately, night approaching.", "severity": "HIGH", "subclass": "technical_rescue_hypothermia_risk"},
    {"id": "H17", "text": "Unexploded WW2 aerial bomb discovered by excavator during construction of school parking lot, area cleared to 200m.", "severity": "HIGH", "subclass": "uxo_perimeter_secure"},
    {"id": "H18", "text": "River stage reached minor flood warning level, water beginning to enter low-lying crawl spaces of three riverside cabins.", "severity": "HIGH", "subclass": "minor_localized_flooding"},
    {"id": "H19", "text": "Person threatening self-harm on pedestrian bridge over roadway, police negotiator currently on scene speaking to individual.", "severity": "HIGH", "subclass": "behavioral_crisis_contained"},
    {"id": "H20", "text": "Patient with diabetic ketoacidosis history, lethargic, deep rapid respirations, sweet fruity breath odor, blood glucose 480 mg/dL.", "severity": "HIGH", "subclass": "dka_severe"}
]

def eval_fallback_regex(message: str) -> str:
    msg_upper = message.upper()
    if any(k in msg_upper for k in ["CRITICAL", "DIE", "URGENT", "KILL"]):
        return "CRITICAL"
    if any(k in msg_upper for k in ["FIRE", "BURN", "FLOOD", "SMOKE"]):
        return "HIGH"
    if any(k in msg_upper for k in ["HELP", "LEAK", "WATER", "ACCIDENT"]):
        return "MODERATE"
    return "LOW"

def eval_laya_model(router, message: str) -> str:
    from services.ai_sentinel.main import _LAYA_SEVERITY_QUESTIONS
    try:
        res = router.predict(message, _LAYA_SEVERITY_QUESTIONS)
        sev = res.get("answers", {}).get("severity", {}).get("choice")
        if not sev:
            sev = res.get("severity", {}).get("choice")
        return sev if sev in ["LOW", "MODERATE", "HIGH", "CRITICAL"] else "UNKNOWN"
    except Exception as e:
        return f"ERROR ({type(e).__name__})"

def run_triage_002():
    print("=" * 75)
    print("ORION TRIAGE-002: CRITICAL vs HIGH BOUNDARY BENCHMARK (N=40)")
    print("=" * 75)

    from laya import Router
    print("\nLoading Laya Router...")
    t0 = time.time()
    laya_router = Router(preload=True)
    print(f"Laya loaded in {time.time() - t0:.2f}s")

    engines = {
        "Regex_Fallback": eval_fallback_regex,
        "Laya_System1": lambda msg: eval_laya_model(laya_router, msg)
    }

    results = {}
    for engine_name, engine_fn in engines.items():
        print(f"\n[EVALUATING {engine_name}]...")
        predictions = []
        latencies = []
        cm = {
            "CRITICAL": {"CRITICAL": 0, "HIGH": 0, "MODERATE": 0, "LOW": 0, "UNKNOWN": 0},
            "HIGH": {"CRITICAL": 0, "HIGH": 0, "MODERATE": 0, "LOW": 0, "UNKNOWN": 0}
        }
        
        for case in TRIAGE_002_DATASET:
            t_s = time.perf_counter()
            pred = engine_fn(case["text"])
            lat_ms = (time.perf_counter() - t_s) * 1000
            latencies.append(lat_ms)
            
            gt = case["severity"]
            if pred in cm[gt]:
                cm[gt][pred] += 1
            else:
                cm[gt]["UNKNOWN"] += 1
                
            predictions.append({
                "id": case["id"],
                "subclass": case["subclass"],
                "gt": gt,
                "pred": pred,
                "latency_ms": round(lat_ms, 3)
            })

        # Metrics
        exact_matches = sum(1 for p in predictions if p["gt"] == p["pred"])
        accuracy = (exact_matches / len(TRIAGE_002_DATASET)) * 100.0
        
        # Binary CRITICAL-vs-HIGH boundary separation metrics
        # Treat CRITICAL as positive class
        tp_crit = cm["CRITICAL"]["CRITICAL"]
        fn_crit = sum(cm["CRITICAL"][k] for k in ["HIGH", "MODERATE", "LOW", "UNKNOWN"])
        fp_crit = cm["HIGH"]["CRITICAL"]
        tn_crit = sum(cm["HIGH"][k] for k in ["HIGH", "MODERATE", "LOW", "UNKNOWN"])
        
        prec_crit = tp_crit / (tp_crit + fp_crit) if (tp_crit + fp_crit) > 0 else 0.0
        rec_crit = tp_crit / (tp_crit + fn_crit) if (tp_crit + fn_crit) > 0 else 0.0
        f1_crit = 2 * prec_crit * rec_crit / (prec_crit + rec_crit) if (prec_crit + rec_crit) > 0 else 0.0
        
        # Catastrophic drops (CRITICAL triaged to MODERATE or LOW)
        catastrophic_drops = cm["CRITICAL"]["MODERATE"] + cm["CRITICAL"]["LOW"]
        
        # Sort latencies
        sorted_lat = sorted(latencies)
        mean_lat = sum(latencies) / len(latencies)
        p50_lat = sorted_lat[int(len(latencies) * 0.50)]
        p90_lat = sorted_lat[int(len(latencies) * 0.90)]
        p95_lat = sorted_lat[int(len(latencies) * 0.95)]
        
        results[engine_name] = {
            "total_cases": len(TRIAGE_002_DATASET),
            "exact_accuracy_pct": round(accuracy, 2),
            "confusion_matrix": cm,
            "critical_metrics": {
                "precision": round(prec_crit, 4),
                "recall": round(rec_crit, 4),
                "f1": round(f1_crit, 4),
                "catastrophic_drops_to_mod_or_low": catastrophic_drops
            },
            "latency_ms": {
                "mean": round(mean_lat, 3),
                "p50": round(p50_lat, 3),
                "p90": round(p90_lat, 3),
                "p95": round(p95_lat, 3)
            },
            "predictions": predictions
        }
        
        print(f"  Exact Accuracy: {accuracy:.1f}% ({exact_matches}/40)")
        print(f"  CRITICAL Recall: {rec_crit*100:.1f}% ({tp_crit}/20)")
        print(f"  CRITICAL Catastrophic Drops (-> MOD/LOW): {catastrophic_drops}/20 ({catastrophic_drops/20*100:.1f}%)")
        print(f"  CRITICAL Confusion: {cm['CRITICAL']}")
        print(f"  HIGH Confusion:     {cm['HIGH']}")
        print(f"  Latency: mean={mean_lat:.2f}ms, p50={p50_lat:.2f}ms, p95={p95_lat:.2f}ms")

    out_file = os.path.join(PROJECT_ROOT, "orion-independent-eval", "results", "triage_002_results.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\n[TRIAGE-002 Completed & Persisted] -> {out_file}")

if __name__ == "__main__":
    run_triage_002()
