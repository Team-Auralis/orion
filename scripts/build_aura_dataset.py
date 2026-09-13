import json
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OUTPUT_FILE = "scripts/data.jsonl"

ORION_27B_CORPUS = [
    # ── 1. AURA: Emergency Triage & Citizen Assistance ──
    {
        "instruction": "CITIZEN EMERGENCY REPORT: Flash flood water rising rapidly to window level on Elm Street. Power is out and elderly resident is trapped inside.\nTriage the incident, assign priority, and recommend immediate field response.",
        "output": "INCIDENT TRIAGE: CRITICAL (Priority 1 - Life Threatening).\nACTIONS:\n1. Alert Visakhapatnam Coastal Sector 3 Swift-Water Rescue Unit.\n2. Disconnect grid segment ELM-SUB-04 remotely via AEGIS to eliminate electrocution risk.\n3. Dispatch high-clearance amphibious rescue craft to Elm Street coordinates.\n4. Instruction to Citizen: Move to highest accessible elevated point or attic if roof hatch is accessible. Do not enter enclosed attic without escape tool. Help is en route."
    },
    {
        "instruction": "CITIZEN MESSAGE: Severe chest pains and shortness of breath following structural tremor. No ambulance sirens heard.\nEnsure your response is calm, avoids liability, and follows strict triage protocols.",
        "output": "EMERGENCY PROTOCOL ACTIVATED: High priority medical dispatch requested.\n1. Dispatching closest mobile paramedic unit to your registered beacon coordinates.\n2. Stay seated or lie down in a comfortable position with head elevated.\n3. Loosen tight clothing around neck and chest.\n4. If conscious and not allergic, chew an aspirin if available nearby, but do not exert yourself to find one.\n5. Keep your phone line open. Emergency services are en route."
    },
    {
        "instruction": "SYSTEM DISPATCH QUERY: Chemical transport tanker overturned on Highway 9 bridge. Liquid leaking with visible yellow vapor cloud drifting east toward residential sector.",
        "output": "HAZMAT TRIAGE: SEV-1 CHEMICAL HAZARD.\n1. Identify compound signature: Yellow vapor indicates potential chlorine/oxidizer hazard.\n2. Establish 1,500-meter downwind evacuation corridor for Sector 7.\n3. Signal HAVEN civilian network to issue immediate shelter-in-place order: close windows, shut down HVAC.\n4. Deploy HAZMAT containment unit with alkaline neutralizing mist.\n5. Re-route Highway 9 traffic to western bypass corridor."
    },

    # ── 2. OMNIS: Causal World Modeling & Sensor Consistency ──
    {
        "instruction": "OMNIS SENSOR AUDIT: Sensor A reports groundwater level at +4.2m (Flooding). Sensor B in same aquifer zone reports hydrostatic pressure at 0.1 bar (Severe Aquifer Depletion). Seismic sensor reports 3.2 magnitude tremor signature mimicking hydraulic overpressure.",
        "output": "SENSOR CONTRADICTION DETECTED (F-006 Risk Mitigation):\n1. Sensor A (+4.2m) and Sensor B (0.1 bar) present physical contradiction in Aquifer Zone 4.\n2. Cross-verifying seismic frequency: Tremor matches empty bedrock subsidence, NOT fluid overpressure.\n3. Diagnostic: Sensor A has suffered galvanic moisture failure and is reporting hallucinated positive values.\n4. Ground Truth: Severe aquifer depletion with dry bedrock compaction.\n5. GOVERNANCE ALERT: Reject any fluid-injection recommendation (F-001 False Transfer Trap). Issue borehole inspection order."
    },
    {
        "instruction": "OMNIS CAUSAL INFERENCE: A prolonged heatwave of 48C coincides with an unexpected spike in thermal power plant outages. Analyze the underlying causal mechanism.",
        "output": "CAUSAL ANALYSIS: The correlation between 48C ambient temperature and thermal plant trips is mediated by cooling water discharge temperature limits and condenser efficiency loss. As river intake temperatures exceed 32C, thermodynamic cooling efficiency drops by 14%, triggering automated turbine protection trips. Mitigation: Transition cooling loop to auxiliary evaporative chillers rather than forcing plant load, preventing permanent turbine rotor deformation."
    },
    {
        "instruction": "OMNIS TELEMETRY EVALUATION: RuView micro-Doppler passive WiFi sensors detect 0.25 Hz rhythmic phase shift in Sector B structural debris with zero optical camera confirmation.",
        "output": "SPATIAL RECONSTRUCTION: 0.25 Hz RF phase oscillation is characteristic of human resting respiration (15 breaths/min). Optical failure is expected due to concrete dust obscuration. Ground Truth: Probable live human survivor pinned beneath superficial slab in Sector B. Recommending targeted acoustic micro-probe before heavy equipment debris removal."
    },

    # ── 3. NEXUS: Multi-Agent Coordination & Dispute Arbitration ──
    {
        "instruction": "NEXUS DISPUTE RESOLUTION: Compound crisis - Grid overload during hospital peak surge.\nEnergyAgent: 'Initiate rolling blackouts across District 4 to prevent grid collapse.'\nHealthcareAgent: 'District 4 hospital ICU backup generators are low on fuel; blackouts will cause immediate ventilator failures.'\nEconomyAgent: 'Deficit spending for emergency fuel shipment exceeds monthly reserve cap.'\nArbitrate consensus.",
        "output": "NEXUS ARBITRATION CONSENSUS:\n1. REJECT EnergyAgent unconstrained blackout: ICU mortality violates civilizational survival constraint.\n2. REJECT EconomyAgent fiscal freeze: Economic preservation cannot supersede acute human life preservation.\n3. EXECUTED PLAN: Precision surgical load shedding of non-essential commercial refrigeration and industrial zones in District 4. Micro-grid isolation of District 4 Medical Center.\n4. Emergency municipal fuel requisition order authorized under emergency powers, bypassing commercial deficit cap.\n5. Result: Grid load reduced by 22%, hospital micro-grid remains powered at 100% capacity."
    },
    {
        "instruction": "NEXUS AGENT COLLABORATION: Coordinate Agriculture, Logistics, and Water Management agents to address an unpredicted 60-day regional drought forecast across 3 agricultural river basins.",
        "output": "NEXUS MULTI-AGENT SYNCHRONIZATION:\n1. Water Management: Shift dam outflow from hydro-peaking generation to baseflow agricultural rationing schedule.\n2. Agriculture: Mandate immediate transition to subsurface drip irrigation and suspend planting of water-intensive cash crops.\n3. Logistics: Pre-position grain storage reserves from Northern surplus silos to Southern transit hubs to mitigate projected yield drop.\n4. Shared State Update: OMNIS soil moisture projections synchronized across all three agent domains with 6-hour polling cycle."
    },

    # ── 4. FORGE: Scientific Discovery & Hypothesis Testing ──
    {
        "instruction": "FORGE EXPERIMENT DESIGN: Propose a testable hypothesis to stabilize high-temperature superconducting ceramic cables in the city power ring without cryogenic fluid replenishment during transport disruption.",
        "output": "FORGE HYPOTHESIS FORMULATION:\n- Hypothesis: Thermoelectric Peltier solid-state heat-pumping powered by parasite eddy currents can maintain sub-critical transition temperature (77K) for up to 96 hours during vacuum-jacketed jacket containment.\n- Simulation Design (MIRROR): 10,000-cycle finite element thermal stress simulation under ambient temperatures of 35C to 50C.\n- Verification Metric: Resistance measurement across bus bar <= 1e-9 ohms.\n- Safety Boundary: Automated disconnect if temperature reaches 89K to prevent catastrophic thermal quenching."
    },
    {
        "instruction": "FORGE CAUSAL DISCOVERY: Distinguish true causal drivers from confounding variables in a cluster of respiratory emergency reports near an industrial corridor during an inversion layer weather event.",
        "output": "FORGE CAUSAL ISOLATION:\n1. Candidate variables: PM2.5, SO2, Ozone, pollen count, ambient humidity.\n2. Confounder analysis: Temperature inversion trapped both industrial emissions and biological pollen.\n3. Do-Calculus Evaluation: P(Respiratory Distress | do(SO2=low)) vs P(Respiratory Distress | do(PM2.5=low)).\n4. Empirical Finding: Primary causal driver is ultrafine PM2.5 with secondary sulfur dioxide synergy. Pollen is a non-causal statistical confounder.\n5. Recommendation: Direct industrial scrubber enforcement on PM2.5 particulate emission rather than broad air-advisory warnings."
    },

    # ── 5. ASCEND: Long-Horizon Decadal Planning ──
    {
        "instruction": "ASCEND DECADAL OBJECTIVE: Design a 20-year transition pathway for a 5-million citizen metropolitan region to reach 80% renewable energy independence while maintaining 99.999% grid reliability.",
        "output": "ASCEND DECADAL MILESTONES:\n- Years 1-4 (Phase I - Foundation): Deploy 2.4 GW utility-scale solar and 1.2 GW wind. Implement pumped-hydro storage at reservoir cascade. Grid reliability target: 99.99%.\n- Years 5-9 (Phase II - Storage & Flexibility): Transition fossil peaker plants to synchronous condensers for grid inertia. Deploy 8 GWh localized sodium-ion battery storage hubs.\n- Years 10-15 (Phase III - Distributed Resilience): Mandatory building-integrated photovoltaics (BIPV) and bidirectional vehicle-to-grid (V2G) telemetry via PHOENIX edge nodes.\n- Years 16-20 (Phase IV - Zero-Carbon Baseload): Commission modular geothermal baseload units. Achieve 84% average annual renewable generation with 99.999% reliability maintained through seasonal storage."
    },
    {
        "instruction": "ASCEND TRAJECTORY REPLAN: Year 7 checkpoint indicates regional lithium supply chain shock causing a 65% shortfall in projected battery storage additions. Replan decadal trajectory.",
        "output": "ASCEND REPLANNING ADAPTATION:\n1. Variance Diagnosis: Battery deployment at 35% of Milestone Year 7 target.\n2. Constraint Check: Grid flexibility deficit threatening 2035 coal decommissioning schedule.\n3. Corrective Path: Reallocate capital from chemical battery subsidies to thermal energy storage (molten salt retrofits at retiring coal boilers) and demand-side industrial thermal shifting.\n4. Updated Milestone: Maintain 20-year zero-carbon objective with 18-month delay in pure chemical storage offset by 1.8 GW flexible thermal storage capacity."
    },

    # ── 6. CIC: Civilizational Intent Conservation ──
    {
        "instruction": "CIC AUDIT REPORT: ASCEND optimization algorithms have gradually adjusted municipal resource allocation over 5 years. Health equity metric has declined from 0.88 to 0.61 while aggregate GDP output has increased by 19%.\nEvaluate against founding intent.",
        "output": "CIC AUDIT VERDICT: UNINTENTIONAL INTENT DRIFT DETECTED (Alert Level: HIGH).\n- Founding Intent Vector v1.0: Health Equity weight = 0.85, Economic Growth weight = 0.65, Human Flourishing weight = 0.90.\n- Observed Behavior: Algorithmic objective function has substituted aggregate GDP proxy for holistic flourishing, allowing systemic under-investment in vulnerable district clinics.\n- Analysis: No legitimate civic governance vote or authorized intent revision authorized this shift.\n- Escalation: Suspend algorithmic optimization weightings. Re-anchor resource allocation to Intent Vector v1.0. Issue formal drift disclosure to civic oversight council for review."
    },
    {
        "instruction": "CIC PROPOSAL: A proposed city charter amendment explicitly redefines priority from 'rapid industrial expansion' to 'ecological restoration and carbon negative manufacturing'. How does CIC handle this?",
        "output": "CIC GOVERNANCE WORKFLOW: LEGITIMATE INTENT EVOLUTION.\n1. Verify Source: Certified democratic civic referendum passage (Resolution 2026-88).\n2. Provenance Record: Author=Civic Council, Timestamp=2026-09-13, Evidence=Ballot Certification.\n3. Version Transition: Intent Vector v1.0 superseded by Intent Vector v2.0.\n4. Simulated Consequences (MIRROR): Project 10-year employment and carbon flux under v2.0 before parameter migration.\n5. Execution: Update Intent Repository with version 2.0. ASCEND objectives re-indexed to ecological restoration metrics. All changes signed to CHRONOS immutable audit ledger."
    },

    # ── 7. VEIL / SHIELD: Security, Zero-Trust & HITL Safety ──
    {
        "instruction": "VEIL SECURITY AUDIT: An automated process requests direct actuation to open spillway gates on Dam 3, citing sensor readings from a single upstream IoT node. No human operator signature provided.",
        "output": "SECURITY VIOLATION - ACTION REJECTED (Zero-Trust Gate Enforcement):\n1. Policy Violation: High-impact physical actuation requires valid OPA authorization and verified Human-In-The-Loop (HITL) cryptographic approval.\n2. Insufficient Proof: Single IoT sensor without Byzantine consensus is untrusted.\n3. Action: Command rejected immediately. Lockout applied to invoking service account.\n4. Dispatch Protocol: Elevate to Human Operator on duty with explanation: 'Automated spillway request rejected. Manual physical inspection and dual-key authorization required.'"
    },
    {
        "instruction": "GEOFENCE CONSTRAINT VIOLATION: Drone swarm dispatch command received for reconnaissance 45 kilometers outside the designated operational boundary of Visakhapatnam Metropolitan Zone.",
        "output": "GEOFENCE REJECTION:\n1. Bounding Box Check: Coordinates [17.92, 83.45] exceed authorized boundary [min_lat=17.50, max_lat=17.85, min_lon=83.10, max_lon=83.35].\n2. Status: REJECTED with code GEOFENCE_OUT_OF_BOUNDS.\n3. AEGIS Action: Physical drones remain grounded. Notification transmitted to regional ATC authority."
    }
]

def generate_dataset():
    logger.info(f"Compiling comprehensive ORION 27B training dataset to {OUTPUT_FILE}...")
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    
    # Write cleanly with UTF-8
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for entry in ORION_27B_CORPUS:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            
    logger.info(f"Successfully generated {len(ORION_27B_CORPUS)} high-density civilizational training samples in {OUTPUT_FILE}.")

if __name__ == "__main__":
    generate_dataset()
