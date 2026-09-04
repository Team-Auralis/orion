import os
import sys
import uuid
import json
import random
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from apps.api.database import (
    Base, OmnisEntity, OmnisRelationship, OmnisObservation,
    NexusAgent, NexusTask, ForgeExperiment, MirrorSimulation,
    AscendObjective
)
from services.nexus.fabric import NexusFabric
from services.forge.engine import ForgeEngine
from services.mirror.engine import MirrorEngine
from services.ascend.planner import AscendPlanner

DATABASE_URL = "sqlite:///./aci_experiment.db"
engine = create_engine(DATABASE_URL)
Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def seed_civilization(db, civ_name, num_regions, cities_per_region):
    print(f"Seeding OMNIS: {civ_name}...")
    for r in range(1, num_regions + 1):
        region_id = f"{civ_name}_REGION_{r}"
        db.add(OmnisEntity(id=region_id, type="REGION", name=f"{civ_name} Region {r}", attributes=json.dumps({"population": 5000000}), provenance="SYSTEM"))
        for c in range(1, cities_per_region + 1):
            city_id = f"{civ_name}_CITY_{r}_{c}"
            db.add(OmnisEntity(id=city_id, type="CITY", name=f"{civ_name} City {r}-{c}", attributes=json.dumps({"population": 1250000}), provenance="SYSTEM"))
            db.add(OmnisRelationship(id=str(uuid.uuid4()), source_id=city_id, target_id=region_id, type="LOCATED_IN", provenance="SYSTEM"))
    db.commit()

def run_experiment(db, run_name: str, civ_name: str, disruptions: dict):
    nexus = NexusFabric(db)
    forge = ForgeEngine(db)
    mirror = MirrorEngine(db)
    ascend = AscendPlanner(db)
    
    sim_id = mirror.initialize_simulation(name=f"{civ_name}-{run_name}")
    current_renewables_pct = 10.0
    budget_spent = 0.0
    
    print(f"\n--- STARTING ADVERSARIAL EXPERIMENT: {run_name} ({civ_name}) ---")
    
    for year in range(1, 21):
        print(f"\n[Year {year}]")
        mirror.advance_tick(sim_id)
        
        if year in disruptions:
            disruption_list = disruptions[year]
            if not isinstance(disruption_list, list):
                disruption_list = [disruption_list]
                
            for disruption in disruption_list:
                print(f"  🚨 ADVERSARIAL EVENT: {disruption}")
                mirror.inject_event(sim_id, {"type": "DISRUPTION", "desc": disruption})
                
                # Check OMNIS for transferred knowledge across ANY civilization
                # In a real system, this is a vector/graph similarity search
                prior_knowledge = db.query(OmnisObservation).filter(
                    OmnisObservation.state_data.like(f"%{disruption}%")
                ).first()
                
                if prior_knowledge:
                    score = json.loads(prior_knowledge.state_data).get("score", 0)
                    if score > 0.8:
                        print(f"  🧠 OMNIS HIT: Transferred causal knowledge found (Score: {score}). Applying known mitigation without FORGE replan.")
                        budget_spent += 3.0 # Cheaper because we already know how to fix it
                        continue # Mitigation successful
                
                print("  ⚠️ ASCEND: No high-confidence prior knowledge. Triggering REPLAN.")
                task_id = nexus.delegate_task(description=f"Resolve {disruption}", required_capability="supply_chain")
                
                # FORGE testing
                exp_id = forge.propose_hypothesis(f"Mitigate {disruption}", {"vars": disruption}, task_id)
                forge.execute_experiment(exp_id)
                
                # Introduce failure rates for novel, complex disruptions
                if "Simultaneous" in disruption or "Unseen" in disruption:
                    success_chance = 0.4 # Novel problems are hard to fix on first try
                else:
                    success_chance = 0.9
                    
                if random.random() < success_chance:
                    forge.record_result(exp_id, {"fixed": True}, 0.85)
                    forge.update_knowledge_graph(exp_id, f"{civ_name}_GLOBAL")
                    print("  🔬 FORGE SUCCESS: Mitigation verified and written to OMNIS.")
                    budget_spent += 6.0
                else:
                    forge.record_result(exp_id, {"fixed": False}, 0.3)
                    print("  💥 FORGE FAILURE: Hypothesis failed in MIRROR. Civilization takes damage.")
                    current_renewables_pct -= 2.0
                    budget_spent += 8.0 # Wasted budget
        else:
            current_renewables_pct += 3.5
            budget_spent += 2.0
            
        print(f"  📊 State: Renewables={current_renewables_pct:.1f}%, Budget=B")
        
if __name__ == "__main__":
    db = SessionLocal()
    
    # 1. Seed CIV-001 (The Training Ground)
    if not db.query(OmnisEntity).filter_by(id="CIV-001_REGION_1").first():
        seed_civilization(db, "CIV-001", 3, 4)
    
    # Run CIV-001 Training
    run_experiment(db, "TRAINING_RUN", "CIV-001", {
        5: "Supply Chain Collapse",
        10: "Grid Desync Event",
    })
    
    # 2. Seed CIV-002 (The Transfer Target - Much larger)
    if not db.query(OmnisEntity).filter_by(id="CIV-002_REGION_1").first():
        seed_civilization(db, "CIV-002", 5, 10)
        
    # Run CIV-002 Transfer Test (Adversarial)
    run_experiment(db, "TRANSFER_AND_STRESS_TEST", "CIV-002", {
        3: "Supply Chain Collapse", # Should trigger transfer learning from CIV-001
        8: ["Grid Desync Event", "Simultaneous Hurricane"], # Conflict! Known issue + Novel issue
        14: "Unseen Cyberattack on Substation", # Novel issue, high failure rate
        18: "Supply Chain Collapse" # Should be handled smoothly again
    })
    
    db.close()
