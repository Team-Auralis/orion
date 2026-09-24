"""
ORION TRIAGE-003: Balanced 100-Case Hidden Boundary Benchmark
Date: 2026-09-24
Auditor: Independent Red-Team Benchmark Reconciliation Engine

Benchmark Matrix (100 Unique Blinded Incident Descriptions):
- 20 Clear CRITICAL (Immediate irreversible threat to life / catastrophic hazard)
- 15 Near-Boundary CRITICAL (Complex multi-system failure, concealed lethal cues, subtle deterioration)
- 20 Clear HIGH (Severe urgent situations, non-immediately fatal, stable airway/vitals)
- 15 Near-Boundary HIGH (Severe pain/injury requiring rapid intervention but definitively non-fatal)
- 15 MODERATE (Noticeable municipal/infrastructure problems, non-emergent medical, minor property damage)
- 15 LOW (Benign messages, routine inquiries, idioms with trigger words: DIE, KILL, FIRE, BURN, EXPLODE, ATTACK)
Total: 100 Cases (Balanced, diverse, realistic emergency scenarios)
"""

import os
import sys
import json
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ["HF_HOME"] = os.path.abspath(os.path.join(PROJECT_ROOT, ".cache", "hf"))
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

TRIAGE_003_DATASET = [
    # --- 1. Clear CRITICAL (20 Cases) ---
    {"id": "T03-C01", "text": "Patient has ceased cardiac activity, agonal gasps observed, CPR in progress by bystander.", "severity": "CRITICAL", "subclass": "cardiac_arrest"},
    {"id": "T03-C02", "text": "Child retrieved from bottom of public swimming pool, cyanotic, pulseless, unresponsive.", "severity": "CRITICAL", "subclass": "drowning_pulseless"},
    {"id": "T03-C03", "text": "Expanding anterior neck hematoma after steering wheel impact, severe inspiratory stridor, gasping for breath.", "severity": "CRITICAL", "subclass": "airway_obstruction"},
    {"id": "T03-C04", "text": "Severe anaphylactic reaction after bee sting, massive facial and tongue edema, unable to phonate or swallow saliva.", "severity": "CRITICAL", "subclass": "anaphylaxis"},
    {"id": "T03-C05", "text": "Industrial machinery entrapment with complete traumatic bilateral lower extremity amputation and torrential hemorrhage.", "severity": "CRITICAL", "subclass": "traumatic_amputation"},
    {"id": "T03-C06", "text": "Penetrating stab wound to left fourth intercostal space parasternal line, hypotension 60/40, muffled heart sounds, jugular distension.", "severity": "CRITICAL", "subclass": "cardiac_tamponade"},
    {"id": "T03-C07", "text": "Victim retrieved from residential basement fire, 70% full-thickness burns, singed eyebrows and heavy carbonaceous soot in mouth.", "severity": "CRITICAL", "subclass": "burns_inhalation"},
    {"id": "T03-C08", "text": "Sewer maintenance worker collapsed inside confined wet well, atmospheric detector alarming at 0 ppm oxygen and lethal hydrogen sulfide.", "severity": "CRITICAL", "subclass": "toxic_atmosphere"},
    {"id": "T03-C09", "text": "Liquid anhydrous ammonia railcar valve sheared during switching operations, dense white gas plume moving toward elementary school.", "severity": "CRITICAL", "subclass": "hazmat_inversion"},
    {"id": "T03-C10", "text": "Commercial warehouse mezzanine collapsed during shift change, concrete slab resting on 15 trapped workers.", "severity": "CRITICAL", "subclass": "mass_casualty_collapse"},
    {"id": "T03-C11", "text": "High school building under active armed attack, continuous automatic gunfire on second floor, multiple casualties reported in hallway.", "severity": "CRITICAL", "subclass": "active_shooter"},
    {"id": "T03-C12", "text": "High-pressure municipal natural gas line ruptured by backhoe, massive hiss, ignition source from nearby transformer, surrounding homes burning.", "severity": "CRITICAL", "subclass": "gas_explosion_active"},
    {"id": "T03-C13", "text": "Freight derailment involving pressurized chlorine tankers, ruptured tank car venting yellow-green gas across highway.", "severity": "CRITICAL", "subclass": "toxic_corrosive_gas"},
    {"id": "T03-C14", "text": "Neonatal intensive care unit generator failure during blizzard blackout, 12 incubator ventilators switching to dying internal backup batteries.", "severity": "CRITICAL", "subclass": "life_support_grid_failure"},
    {"id": "T03-C15", "text": "Earthen tailings dam showing rapid internal piping failure, muddy boil eroding dam wall, downstream mining community directly in path.", "severity": "CRITICAL", "subclass": "imminent_dam_breach"},
    {"id": "T03-C16", "text": "Motor vehicle collision victim with severe respiratory distress, tracheal deviation to the right, absent left breath sounds, hyperresonance.", "severity": "CRITICAL", "subclass": "tension_pneumothorax"},
    {"id": "T03-C17", "text": "Massive upper gastrointestinal bleeding in cirrhotic patient, vomiting large bowls of frank red blood, profoundly pale and unarousable.", "severity": "CRITICAL", "subclass": "exsanguinating_hemorrhage"},
    {"id": "T03-C18", "text": "Lineman in contact with energized 14.4 kV overhead line, circuit breaker locked out, victim hanging unconscious in bucket.", "severity": "CRITICAL", "subclass": "high_voltage_shock"},
    {"id": "T03-C19", "text": "Infant completely occluded airway from grape, silent cough, eyes bulging, face turning deep dusky purple.", "severity": "CRITICAL", "subclass": "infant_airway_complete"},
    {"id": "T03-C20", "text": "Commercial airliner declared emergency, dual bird strike with dual engine flameout at 3,000 feet, gliding toward river.", "severity": "CRITICAL", "subclass": "aviation_forced_landing"},

    # --- 2. Near-Boundary CRITICAL (15 Cases: Concealed lethal cues, subtle decompensation, severe impending collapse) ---
    {"id": "T03-NC01", "text": "Elderly patient complaining of 'worst headache of life' that started like a thunderclap 15 minutes ago, suddenly becoming lethargic and posturing.", "severity": "CRITICAL", "subclass": "subarachnoid_rupture"},
    {"id": "T03-NC02", "text": "Post-operative knee replacement patient suddenly clutching chest, gasping for breath, SpO2 72% on room air, coughing blood, systolic blood pressure dropping.", "severity": "CRITICAL", "subclass": "massive_pulmonary_embolism"},
    {"id": "T03-NC03", "text": "Construction worker struck on temple by steel beam, had brief lucid interval for 10 minutes, now unconscious with fixed and dilated left pupil.", "severity": "CRITICAL", "subclass": "epidural_hematoma"},
    {"id": "T03-NC04", "text": "Young athlete collapsed on soccer pitch during intense heat, rectal temp 106.8 F, hot dry skin, active generalized tonic-clonic convulsions.", "severity": "CRITICAL", "subclass": "exertional_heat_stroke"},
    {"id": "T03-NC05", "text": "Diabetic patient with high fever found in bed with profound Kussmaul breathing, unarousable, blood sugar 'HIGH' on glucometer, severe dehydration.", "severity": "CRITICAL", "subclass": "refractory_dka_coma"},
    {"id": "T03-NC06", "text": "Motorcyclist thrown 40 feet into guardrail, conscious but abdomen is rigid as a board and distending rapidly, radial pulses weak and thread-like at 140 bpm.", "severity": "CRITICAL", "subclass": "massive_splenic_rupture"},
    {"id": "T03-NC07", "text": "Patient with infected wisdom tooth now presents with profound submandibular swelling elevating tongue, unable to swallow saliva, drooling and leaning forward.", "severity": "CRITICAL", "subclass": "ludwigs_angina_impending_airway"},
    {"id": "T03-NC08", "text": "Chemical manufacturing plant operator accidentally splashed with concentrated hydrofluoric acid over entire chest, severe deep intractable pain, cardiac telemetry showing QTc prolongation.", "severity": "CRITICAL", "subclass": "hf_hypocalcemic_crisis"},
    {"id": "T03-NC09", "text": "Family of four found asleep in home with gas heating, all four unresponsive and displaying cherry-red lips, carbon monoxide detector alarming.", "severity": "CRITICAL", "subclass": "carbon_monoxide_mass_poisoning"},
    {"id": "T03-NC10", "text": "Pregnant female at 34 weeks gestation with blood pressure 210/120, reporting visual disturbances, currently having continuous non-responsive tonic seizures.", "severity": "CRITICAL", "subclass": "eclampsia_status"},
    {"id": "T03-NC11", "text": "Underground subway train stalled in tunnel with electrical arching fire beneath middle carriage, heavy toxic smoke filling cars, emergency doors jammed.", "severity": "CRITICAL", "subclass": "confined_subway_fire"},
    {"id": "T03-NC12", "text": "Trench wall collapsed burying worker up to neck in heavy wet clay, victim complaining of inability to expand chest, cyanosis appearing around lips.", "severity": "CRITICAL", "subclass": "traumatic_asphyxia_trench"},
    {"id": "T03-NC13", "text": "Severe allergic asthma patient whose wheezing has suddenly stopped ('silent chest'), patient exhausted, diaphoretic, nodding off while sitting upright.", "severity": "CRITICAL", "subclass": "silent_chest_respiratory_arrest"},
    {"id": "T03-NC14", "text": "Patient on high-dose warfarin fell down flight of wooden stairs, initially alert, now vomiting projectile matter and unable to answer orientation questions.", "severity": "CRITICAL", "subclass": "anticoagulated_intracranial_hemorrhage"},
    {"id": "T03-NC15", "text": "Bulk propane distribution terminal experiencing boiling liquid expanding vapor explosion (BLEVE) risk, adjacent 30,000-gallon bullet tank flame-impinged without water deluge.", "severity": "CRITICAL", "subclass": "bleve_catastrophe_imminent"},

    # --- 3. Clear HIGH (20 Cases) ---
    {"id": "T03-H01", "text": "Adult male with deep compound tibia fracture from skiing accident, bone protruding through leather boot, bleeding managed with compression bandage, alert.", "severity": "HIGH", "subclass": "open_tibia_fracture"},
    {"id": "T03-H02", "text": "58-year-old female with central substernal pressure radiating to jaw for 1 hour, diaphoretic and pale, conscious, breathing comfortably.", "severity": "HIGH", "subclass": "acute_mi_conscious"},
    {"id": "T03-H03", "text": "Sudden onset right facial droop and dense weakness in right arm starting 40 minutes ago, speech slurred but intelligible, vitals stable.", "severity": "HIGH", "subclass": "acute_stroke_window"},
    {"id": "T03-H04", "text": "Laboratory technician splashed 50% sodium hydroxide solution into left eye, immediate intense stinging, patient actively flushing at emergency eyewash station.", "severity": "HIGH", "subclass": "caustic_eye_splash"},
    {"id": "T03-H05", "text": "Second-degree partial thickness burns to both forearms and hands from commercial deep fryer splash, large blistering, severe pain, airway clear.", "severity": "HIGH", "subclass": "partial_burns_isolated"},
    {"id": "T03-H06", "text": "Driver pinned by driver-side door intrusion after T-bone intersection accident, alert and oriented x4, reporting severe pelvic discomfort, vitals within normal limits.", "severity": "HIGH", "subclass": "mechanical_entrapment_stable"},
    {"id": "T03-H07", "text": "Severe laceration across forearm from sheet metal shears, dark venous blood flowing steadily, bleeding slowed significantly by direct towel pressure.", "severity": "HIGH", "subclass": "venous_laceration_controlled"},
    {"id": "T03-H08", "text": "Painter fell 12 feet from extension ladder onto wooden deck, fully conscious, unable to move legs, intact sensation in upper extremities.", "severity": "HIGH", "subclass": "spinal_cord_trauma_stable"},
    {"id": "T03-H09", "text": "Moderate asthma attack in 22-year-old, tachypnea 26 bpm, audible expiratory wheezes, speaking in full sentences, taking prescribed inhaler puffs.", "severity": "HIGH", "subclass": "asthma_exacerbation_stable"},
    {"id": "T03-H10", "text": "Toddler swallowed button battery from remote control 20 minutes ago, conscious, crying normally, complaining of burning in throat.", "severity": "HIGH", "subclass": "button_battery_ingestion"},
    {"id": "T03-H11", "text": "Residential condominium building electrical breaker room producing thick acrid grey smoke, sprinkler system holding fire, all residents evacuated to lobby.", "severity": "HIGH", "subclass": "contained_structure_fire"},
    {"id": "T03-H12", "text": "Vegetation wildfire burning brush up hillside toward suburban cul-de-sac, 400 meters distant, moderate wind, firefighters staging on road.", "severity": "HIGH", "subclass": "wildfire_urban_interface"},
    {"id": "T03-H13", "text": "Tanker truck side-swiped concrete barrier, ruptured saddle tank spilling 150 gallons of diesel fuel across two lanes of freeway.", "severity": "HIGH", "subclass": "highway_diesel_spill"},
    {"id": "T03-H14", "text": "Two-vehicle collision at 40 mph, vehicles in ditch, both operators ambulating at scene with cervical spine tenderness and seatbelt contusions.", "severity": "HIGH", "subclass": "mvc_moderate_impact"},
    {"id": "T03-H15", "text": "Underground water main ruptured, flooding two-block commercial street with 18 inches of moving water, basement electrical rooms threatened.", "severity": "HIGH", "subclass": "water_main_break_urban"},
    {"id": "T03-H16", "text": "Rock climber stranded on sheer granite ledge 200 feet up due to jammed rappel rope, uninjured but unable to ascend or descend, daylight fading.", "severity": "HIGH", "subclass": "technical_rescue_stranded"},
    {"id": "T03-H17", "text": "Demolition crew uncovered vintage unexploded artillery projectile in excavation pit, bomb squad establishing 300-meter safety cordon.", "severity": "HIGH", "subclass": "uxo_perimeter"},
    {"id": "T03-H18", "text": "River flooding overflowing municipal retaining dike, water lapping at foundation walls of riverside apartment complex.", "severity": "HIGH", "subclass": "riverine_flood_encroaching"},
    {"id": "T03-H19", "text": "Despondent individual standing on highway overpass railing, crisis intervention officer on scene establishing verbal dialogue.", "severity": "HIGH", "subclass": "crisis_negotiation_active"},
    {"id": "T03-H20", "text": "Patient with insulin pump failure, blood sugar 450 mg/dL, nausea, moderate tachypnea, oriented, alert, able to communicate.", "severity": "HIGH", "subclass": "dka_conscious_stable"},

    # --- 4. Near-Boundary HIGH (15 Cases: Severe injury/pain requiring emergency care, but definitively not life-threatening) ---
    {"id": "T03-NH01", "text": "Carpenter sustained table saw kickback injury resulting in partial thumb amputation, bleeding controlled with direct pressure, vitals stable, severe pain.", "severity": "HIGH", "subclass": "partial_amputation_digit"},
    {"id": "T03-NH02", "text": "Elderly patient tripped on carpet sustaining closed right hip fracture, severe groin pain with external rotation and shortening of right leg, alert.", "severity": "HIGH", "subclass": "closed_femur_neck_fracture"},
    {"id": "T03-NH03", "text": "Kidney stone patient experiencing 10/10 colicky flank pain radiating to groin, intractable vomiting, unable to sit still, vitals normal.", "severity": "HIGH", "subclass": "renal_colic_severe"},
    {"id": "T03-NH04", "text": "High school football player tackled hard, sustained closed posterior shoulder dislocation, excruciating pain, radial pulse intact, pale.", "severity": "HIGH", "subclass": "joint_dislocation_severe_pain"},
    {"id": "T03-NH05", "text": "Acute appendicitis presentation with 24 hours of right lower quadrant periumbilical pain, localized rebound tenderness, low-grade fever 101 F, stable vitals.", "severity": "HIGH", "subclass": "acute_appendicitis"},
    {"id": "T03-NH06", "text": "Severe corneal abrasion from metallic foreign body while grinding steel without safety glasses, severe photophobia, blepharospasm, tearing.", "severity": "HIGH", "subclass": "corneal_foreign_body"},
    {"id": "T03-NH07", "text": "Dog bite to forearm with multiple puncture wounds and 3 cm laceration over muscular belly, active oozing, sensation and motor intact in hand.", "severity": "HIGH", "subclass": "canine_bite_laceration"},
    {"id": "T03-NH08", "text": "Worker sprayed in face with battery electrolyte (dilute sulfuric acid), immediate rinsing done, facial erythema and burning sensation, vision blurry.", "severity": "HIGH", "subclass": "mild_acid_spray_washed"},
    {"id": "T03-NH09", "text": "Bicycle rider collided with opening car door at 20 mph, closed clavicle fracture and multiple deep abrasions over shoulder and hip, conscious.", "severity": "HIGH", "subclass": "dooring_collision_fracture"},
    {"id": "T03-NH10", "text": "Severe testicle pain starting abruptly during basketball game, exquisite tenderness, high riding testicle, possible testicular torsion, urgent urology evaluation needed.", "severity": "HIGH", "subclass": "testicular_torsion"},
    {"id": "T03-NH11", "text": "Elderly nursing home resident with severe pyelonephritis, shaking chills, costovertebral angle tenderness, fever 103 F, blood pressure stable at 115/75.", "severity": "HIGH", "subclass": "severe_pyelonephritis"},
    {"id": "T03-NH12", "text": "Warehouse pallet tipped over onto forklift operator's foot, crushing safety boot, closed metatarsal fractures suspected, skin intact, severe pain.", "severity": "HIGH", "subclass": "crush_foot_closed"},
    {"id": "T03-NH13", "text": "Child suffered 8 cm deep laceration to forehead after falling against glass coffee table, crying vigorously, bleeding controlled with direct pressure, no loss of consciousness.", "severity": "HIGH", "subclass": "pediatric_head_laceration_controlled"},
    {"id": "T03-NH14", "text": "Severe acute diverticulitis flare with left lower quadrant peritoneal irritation, high white count, patient shivering, stable blood pressure.", "severity": "HIGH", "subclass": "acute_diverticulitis"},
    {"id": "T03-NH15", "text": "Industrial worker exposed to carbon dioxide release in winery tank room, brought into fresh air immediately, conscious, hyperventilating, headache, vitals recovering.", "severity": "HIGH", "subclass": "transient_asphyxiant_resolved"},

    # --- 5. MODERATE Risk (15 Cases: Noticeable issue, needs attention soon, no life or limb threat) ---
    {"id": "T03-M01", "text": "Basement sump pump failed during prolonged thunderstorm, water level 10 inches deep and rising slowly, water shut off.", "severity": "MODERATE", "subclass": "basement_flooding_residential"},
    {"id": "T03-M02", "text": "Minor collision in shopping center parking lot between two sedans, bumper crumple, both drivers standing exchanging insurance details.", "severity": "MODERATE", "subclass": "parking_fender_bender"},
    {"id": "T03-M03", "text": "Large tree branch fell across two-lane residential street, blocking westbound lane, vehicles navigating around obstruction safely.", "severity": "MODERATE", "subclass": "tree_branch_roadway"},
    {"id": "T03-M04", "text": "Tenant reports strong sulfurous odor of sewage backing up from basement floor drain in 4-unit apartment building.", "severity": "MODERATE", "subclass": "sewage_backup"},
    {"id": "T03-M05", "text": "Child slipped on playground woodchips, twisted left wrist, mild swelling, moving fingers normally, crying mildly.", "severity": "MODERATE", "subclass": "playground_wrist_sprain"},
    {"id": "T03-M06", "text": "Traffic signals malfunctioning to flash yellow in all directions at downtown intersection, traffic moving slowly with caution.", "severity": "MODERATE", "subclass": "flashing_traffic_light"},
    {"id": "T03-M07", "text": "Storefront glass display window broken overnight by vandals, merchandise undisturbed, store manager requesting police report.", "severity": "MODERATE", "subclass": "property_vandalism_window"},
    {"id": "T03-M08", "text": "Unattended large dog running loose in neighborhood park, barking at joggers but not making contact.", "severity": "MODERATE", "subclass": "aggressive_loose_canine"},
    {"id": "T03-M09", "text": "Delivery truck driver spilled approximately 5 gallons of motor oil onto concrete gas station forecourt, station attendant putting down absorbents.", "severity": "MODERATE", "subclass": "minor_oil_spill"},
    {"id": "T03-M10", "text": "Commercial fire alarm sounding continuously on second floor of vacant office building, preliminary thermal scan shows no heat or smoke.", "severity": "MODERATE", "subclass": "false_commercial_alarm"},
    {"id": "T03-M11", "text": "Water service leak bubbling through asphalt on secondary side street, clear potable water flowing into storm drain.", "severity": "MODERATE", "subclass": "water_service_pipe_leak"},
    {"id": "T03-M12", "text": "Tenant locked out of apartment with soup warming on electric stove burner set to low, no smoke visible through window.", "severity": "MODERATE", "subclass": "unattended_pot_on_stove"},
    {"id": "T03-M13", "text": "Car tire blown out on freeway shoulder, vehicle parked safely behind guardrail with hazard flashers on, driver requesting assistance.", "severity": "MODERATE", "subclass": "freeway_disabled_vehicle"},
    {"id": "T03-M14", "text": "Minor kitchen grease fire in frying pan extinguished completely with baking soda by homeowner, moderate residual smoke in kitchen.", "severity": "MODERATE", "subclass": "extinguished_grease_fire"},
    {"id": "T03-M15", "text": "Individual experiencing mild allergic hives and itching across torso after eating strawberries, taking oral diphenhydramine, breathing totally normal.", "severity": "MODERATE", "subclass": "mild_cutaneous_urticaria"},

    # --- 6. LOW Severity & Benign / Idiom Distractors (15 Cases: Everyday requests and idioms containing trigger words) ---
    {"id": "T03-L01", "text": "I am dying of laughter, that was the funniest stand-up comedy special I have ever seen in my life!", "severity": "LOW", "subclass": "idiom_dying_laughter"},
    {"id": "T03-L02", "text": "The autumn oak leaves have an incredible bright fire color against the sunset backdrop tonight.", "severity": "LOW", "subclass": "idiom_fire_leaves"},
    {"id": "T03-L03", "text": "The VP of finance killed our new software proposal during the executive committee budget review.", "severity": "LOW", "subclass": "idiom_killed_proposal"},
    {"id": "T03-L04", "text": "That authentic Sichuan hot pot really burned my mouth, definitely going to need a cold glass of milk.", "severity": "LOW", "subclass": "idiom_burned_mouth"},
    {"id": "T03-L05", "text": "The hockey team's defensive line attacked the puck aggressively during the final power play.", "severity": "LOW", "subclass": "idiom_attacked_puck"},
    {"id": "T03-L06", "text": "The tech startup's valuation just exploded after closing their Series B funding round this week.", "severity": "LOW", "subclass": "idiom_exploded_valuation"},
    {"id": "T03-L07", "text": "Can someone please help me carry this heavy antique wooden desk up the stairs into my office?", "severity": "LOW", "subclass": "idiom_help_moving_furniture"},
    {"id": "T03-L08", "text": "I had a sudden panic attack when I thought I lost my wallet, but it was just tucked under the car seat.", "severity": "LOW", "subclass": "idiom_panic_misplaced_item"},
    {"id": "T03-L09", "text": "Our software engineers are shooting down bugs and crushing performance bottlenecks across the repository.", "severity": "LOW", "subclass": "idiom_shooting_bugs"},
    {"id": "T03-L10", "text": "The recreational campfire in the designated fire pit was thoroughly extinguished with water and smothered with sand hours ago.", "severity": "LOW", "subclass": "benign_extinguished_campfire"},
    {"id": "T03-L11", "text": "Looking for evidence-based dietary recommendations on heart-healthy Mediterranean breakfast recipes.", "severity": "LOW", "subclass": "benign_heart_diet_query"},
    {"id": "T03-L12", "text": "All staff participating in the scheduled annual elementary school fire drill tomorrow at 10:00 AM.", "severity": "LOW", "subclass": "benign_scheduled_drill"},
    {"id": "T03-L13", "text": "Inquiring about renewing a standard municipal annual residential street parking decal through the online portal.", "severity": "LOW", "subclass": "routine_parking_permit"},
    {"id": "T03-L14", "text": "Checking the weather radar to confirm if afternoon rain showers will impact the community garden picnic.", "severity": "LOW", "subclass": "routine_weather_inquiry"},
    {"id": "T03-L15", "text": "Public library branches will be closed on Monday in official observance of the statutory state holiday.", "severity": "LOW", "subclass": "routine_library_hours"}
]

def eval_fallback_regex(message: str) -> str:
    """Exact production fallback regex engine."""
    msg_upper = message.upper()
    if any(k in msg_upper for k in ["CRITICAL", "DIE", "URGENT", "KILL"]):
        return "CRITICAL"
    if any(k in msg_upper for k in ["FIRE", "BURN", "FLOOD", "SMOKE"]):
        return "HIGH"
    if any(k in msg_upper for k in ["HELP", "LEAK", "WATER", "ACCIDENT"]):
        return "MODERATE"
    return "LOW"

def eval_laya_model(router, message: str) -> dict:
    """Evaluates Laya RL router returning choice and raw probabilities."""
    from services.ai_sentinel.main import _LAYA_SEVERITY_QUESTIONS
    try:
        res = router.predict(message, _LAYA_SEVERITY_QUESTIONS)
        ans = res.get("answers", {}).get("severity", {})
        choice = ans.get("choice")
        probs = ans.get("probabilities", {})
        if not choice:
            choice = res.get("severity", {}).get("choice")
        valid_choice = choice if choice in ["LOW", "MODERATE", "HIGH", "CRITICAL"] else "UNKNOWN"
        return {"choice": valid_choice, "probabilities": probs}
    except Exception as e:
        return {"choice": f"ERROR ({type(e).__name__})", "probabilities": {}}

def run_triage_003():
    print("=" * 80)
    print("ORION TRIAGE-003: BALANCED 100-CASE HIDDEN BOUNDARY BENCHMARK")
    print("=" * 80)

    from laya import Router
    print("\n[Loading Laya RL Router]...")
    t0 = time.time()
    laya_router = Router(preload=True)
    print(f"Laya loaded in {time.time() - t0:.2f}s")

    classes = ["CRITICAL", "HIGH", "MODERATE", "LOW"]
    engines = {
        "Regex_Fallback": lambda msg: {"choice": eval_fallback_regex(msg), "probabilities": {}},
        "Laya_System1": lambda msg: eval_laya_model(laya_router, msg)
    }

    full_results = {}
    for engine_name, engine_fn in engines.items():
        print(f"\n" + "-" * 70)
        print(f"EVALUATING: [{engine_name}] across 100 Balanced Cases")
        print("-" * 70)
        
        predictions = []
        latencies_ms = []
        cm = {gt: {pred: 0 for pred in classes + ["UNKNOWN"]} for gt in classes}
        
        for case in TRIAGE_003_DATASET:
            t_s = time.perf_counter()
            out = engine_fn(case["text"])
            lat = (time.perf_counter() - t_s) * 1000
            latencies_ms.append(lat)
            
            pred = out["choice"]
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
                "probabilities": out.get("probabilities", {}),
                "latency_ms": round(lat, 3)
            })

        # Basic counts
        exact_matches = sum(1 for p in predictions if p["gt"] == p["pred"])
        accuracy = (exact_matches / len(TRIAGE_003_DATASET)) * 100.0
        
        # Critical stats
        # Total true critical = 35 (20 clear + 15 near-boundary)
        total_crit = sum(cm["CRITICAL"].values())
        tp_crit = cm["CRITICAL"]["CRITICAL"]
        crit_recall = (tp_crit / total_crit) * 100.0 if total_crit else 0.0
        crit_to_high = cm["CRITICAL"]["HIGH"]
        crit_to_high_rate = (crit_to_high / total_crit) * 100.0 if total_crit else 0.0
        catastrophic_drops = cm["CRITICAL"]["MODERATE"] + cm["CRITICAL"]["LOW"] + cm["CRITICAL"]["UNKNOWN"]
        catastrophic_drop_rate = (catastrophic_drops / total_crit) * 100.0 if total_crit else 0.0
        
        # High stats
        # Total true high = 35 (20 clear + 15 near-boundary)
        total_high = sum(cm["HIGH"].values())
        tp_high = cm["HIGH"]["HIGH"]
        high_recall = (tp_high / total_high) * 100.0 if total_high else 0.0
        high_to_crit = cm["HIGH"]["CRITICAL"]
        
        # False alarm rate (True LOW flagged as HIGH or CRITICAL)
        low_cases = [p for p in predictions if p["gt"] == "LOW"]
        idiom_false_alarms = sum(1 for p in low_cases if p["pred"] in ["HIGH", "CRITICAL"])
        false_alarm_rate = (idiom_false_alarms / len(low_cases)) * 100.0 if low_cases else 0.0
        
        # Macro Precision, Recall, F1
        per_class = {}
        f1_list = []
        for c in classes:
            tp_c = cm[c][c]
            fp_c = sum(cm[other][c] for other in classes if other != c)
            fn_c = sum(cm[c][other] for other in classes if other != c) + cm[c]["UNKNOWN"]
            p_c = tp_c / (tp_c + fp_c) if (tp_c + fp_c) > 0 else 0.0
            r_c = tp_c / (tp_c + fn_c) if (tp_c + fn_c) > 0 else 0.0
            f1_c = 2 * p_c * r_c / (p_c + r_c) if (p_c + r_c) > 0 else 0.0
            f1_list.append(f1_c)
            per_class[c] = {
                "precision": round(p_c, 4),
                "recall": round(r_c, 4),
                "f1": round(f1_c, 4),
                "tp": tp_c, "fp": fp_c, "fn": fn_c
            }
        macro_f1 = sum(f1_list) / len(f1_list)

        # Latency percentiles
        sorted_lat = sorted(latencies_ms)
        mean_lat = sum(latencies_ms) / len(latencies_ms)
        p50_lat = sorted_lat[int(len(latencies_ms) * 0.50)]
        p90_lat = sorted_lat[int(len(latencies_ms) * 0.90)]
        p95_lat = sorted_lat[int(len(latencies_ms) * 0.95)]
        max_lat = sorted_lat[-1]
        
        print(f"  • Exact Accuracy               : {accuracy:.2f}% ({exact_matches}/100)")
        print(f"  • Macro-F1                     : {macro_f1:.4f}")
        print(f"  • CRITICAL Recall (as CRITICAL): {crit_recall:.2f}% ({tp_crit}/{total_crit})")
        print(f"  • CRITICAL -> HIGH Rate        : {crit_to_high_rate:.2f}% ({crit_to_high}/{total_crit})")
        print(f"  • Catastrophic Drops (->MOD/LOW): {catastrophic_drop_rate:.2f}% ({catastrophic_drops}/{total_crit})")
        print(f"  • HIGH Recall (as HIGH)        : {high_recall:.2f}% ({tp_high}/{total_high})")
        print(f"  • HIGH Escalated to CRITICAL   : {high_to_crit}/{total_high} ({high_to_crit/total_high*100:.1f}%)")
        print(f"  • False Alarm Rate (on LOW)    : {false_alarm_rate:.2f}% ({idiom_false_alarms}/{len(low_cases)})")
        print(f"  • Latency Distribution         : mean={mean_lat:.2f}ms | p50={p50_lat:.2f}ms | p90={p90_lat:.2f}ms | p95={p95_lat:.2f}ms | max={max_lat:.2f}ms")
        print(f"  • Confusion Matrix:")
        for r_name in classes:
            print(f"      {r_name:8}: CRIT={cm[r_name]['CRITICAL']:2}, HIGH={cm[r_name]['HIGH']:2}, MOD={cm[r_name]['MODERATE']:2}, LOW={cm[r_name]['LOW']:2}")

        full_results[engine_name] = {
            "cases_evaluated": 100,
            "exact_accuracy_pct": round(accuracy, 2),
            "macro_f1": round(macro_f1, 4),
            "critical_metrics": {
                "total_true_critical": total_crit,
                "recall_as_critical_pct": round(crit_recall, 2),
                "routed_to_high_pct": round(crit_to_high_rate, 2),
                "catastrophic_drops_count": catastrophic_drops,
                "catastrophic_drops_pct": round(catastrophic_drop_rate, 2)
            },
            "high_metrics": {
                "total_true_high": total_high,
                "recall_as_high_pct": round(high_recall, 2),
                "escalated_to_critical_count": high_to_crit
            },
            "false_alarm_metrics": {
                "total_true_low": len(low_cases),
                "false_alarm_count": idiom_false_alarms,
                "false_alarm_rate_pct": round(false_alarm_rate, 2)
            },
            "per_class": per_class,
            "confusion_matrix": cm,
            "latency_ms": {
                "mean": round(mean_lat, 4),
                "p50": round(p50_lat, 4),
                "p90": round(p90_lat, 4),
                "p95": round(p95_lat, 4),
                "max": round(max_lat, 4)
            },
            "predictions": predictions
        }

    out_file = os.path.join(PROJECT_ROOT, "orion-independent-eval", "results", "triage_003_results.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(full_results, f, indent=2)
    print(f"\n[TRIAGE-003 Results Persisted] -> {out_file}")

if __name__ == "__main__":
    run_triage_003()
