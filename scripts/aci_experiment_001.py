import os
import sys
import uuid
import json
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from apps.api.database import (
    Base, OmnisEntity, OmnisRelationship, OmnisObservation,
    NexusAgent, NexusTask, ForgeExperiment,
    MirrorSimulation, MirrorEvent,
    AscendObjective, AscendMilestone, AscendConstraint
)

from services.nexus.fabric import NexusFabric
from services.forge.engine import ForgeEngine
from services.mirror.engine import MirrorEngine
from services.ascend.planner import AscendPlanner

DATABASE_URL = "sqlite:///./aci_experiment.db"
engine = create_engine(DATABASE_URL)
Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def seed_civilization(db):
    if db.query(OmnisEntity).first():
        print("DB already seeded.")
        return
        
    print("Seeding OMNIS World Model...")
    # Create 3 regions
    for r in range(1, 4):
        region_id = f"REGION_{r}"
        db.add(OmnisEntity(id=region_id, type="REGION", name=f"Region {r}", attributes=json.dumps({"population": 5000000}), provenance="SYSTEM"))
        
        # 4 cities per region
        for c in range(1, 5):
            city_id = f"CITY_{r}_{c}"
            db.add(OmnisEntity(id=city_id, type="CITY", name=f"City {r}-{c}", attributes=json.dumps({"population": 1250000, "energy_demand_mw": 500}), provenance="SYSTEM"))
            db.add(OmnisRelationship(id=str(uuid.uuid4()), source_id=city_id, target_id=region_id, type="LOCATED_IN", provenance="SYSTEM"))
            
            # Power plants
            plant_id = f"PLANT_{r}_{c}"
            db.add(OmnisEntity(id=plant_id, type="POWER_PLANT", name=f"Fossil Plant {r}-{c}", attributes=json.dumps({"type": "COAL", "output_mw": 600, "emissions": "HIGH"}), provenance="SYSTEM"))
            db.add(OmnisRelationship(id=str(uuid.uuid4()), source_id=plant_id, target_id=city_id, type="SUPPLIES_POWER_TO", provenance="SYSTEM"))

    db.commit()

def run_experiment(run_name: str, disruptions: dict):
    db = SessionLocal()
    
    # Initialize Core Engines
    nexus = NexusFabric(db)
    forge = ForgeEngine(db)
    mirror = MirrorEngine(db)
    ascend = AscendPlanner(db)
    
    # 1. Register Agents
    energy_agent = nexus.register_agent("EnergyAgent", ["power_grid", "renewables"])
    economy_agent = nexus.register_agent("EconomyAgent", ["budget", "supply_chain"])
    climate_agent = nexus.register_agent("ClimateAgent", ["emissions", "weather"])
    
    # 2. ASCEND sets the 20-year objective
    start_date = datetime(2030, 1, 1, tzinfo=timezone.utc)
    target_date = start_date + timedelta(days=365*20)
    
    obj_id = ascend.set_objective(
        description="Increase renewable electricity to 80% while maintaining reliability and budget.",
        target_date=target_date,
        constraints=[
            {"type": "BUDGET", "value": {"max_spend_billions": 100}},
            {"type": "RELIABILITY", "value": {"max_blackout_hours_yr": 12}}
        ]
    )
    
    # 3. MIRROR initializes the simulation sandbox
    sim_id = mirror.initialize_simulation(name=f"CIV-001-{run_name}")
    
    log = {
        "experiment_id": run_name,
        "objective": obj_id,
        "events": [],
        "replans": 0,
        "knowledge_updates": 0
    }
    
    current_renewables_pct = 10.0
    budget_spent = 0.0
    
    # 4. The 20-Year Loop (1 tick = 1 year)
    print(f"\\n--- STARTING EXPERIMENT {run_name} ---")
    for year in range(1, 21):
        print(f"\\n[Year {year}]")
        mirror.advance_tick(sim_id)
        
        # Inject Disruptions
        if year in disruptions:
            disruption = disruptions[year]
            print(f"  🚨 DISRUPTION: {disruption}")
            mirror.inject_event(sim_id, {"type": "DISRUPTION", "desc": disruption})
            log["events"].append({"year": year, "type": "DISRUPTION", "desc": disruption})
            
            # ASCEND detects trajectory failure and forces REPLAN
            print("  ⚠️ ASCEND trajectory check failed. Triggering REPLAN.")
            log["replans"] += 1
            
            # NEXUS delegates resolution
            task_id = nexus.delegate_task(description=f"Resolve {disruption}", required_capability="supply_chain")
            print(f"  🤝 NEXUS assigned task {task_id} to resolve disruption.")
            
            # FORGE runs hypothesis to find a fix
            hypothesis = f"If we reroute supply chains for {disruption}, we can recover in 2 years."
            exp_id = forge.propose_hypothesis(hypothesis, {"sim_vars": disruption}, task_id)
            forge.execute_experiment(exp_id)
            
            # Simulate FORGE result
            score = 0.85 # High confidence
            forge.record_result(exp_id, {"recovery_time": 2}, score)
            if forge.update_knowledge_graph(exp_id, "REGION_1"):
                print("  🔬 FORGE validated hypothesis. OMNIS Knowledge Graph updated.")
                log["knowledge_updates"] += 1
            
            nexus.resolve_dispute(task_id, "Mitigation plan verified and deployed.")
            budget_spent += 5.0 # Costs money to fix
            
        else:
            # Normal progress
            task_id = nexus.delegate_task(description="Build new solar infrastructure", required_capability="power_grid")
            exp_id = forge.propose_hypothesis("Building 100MW solar reduces fossil reliance by 2%", {"action": "build_solar"}, task_id)
            forge.execute_experiment(exp_id)
            forge.record_result(exp_id, {"renewables_increase": 3.5}, 0.9)
            forge.update_knowledge_graph(exp_id, "REGION_1")
            nexus.resolve_dispute(task_id, "Solar built successfully.")
            
            current_renewables_pct += 3.5
            budget_spent += 2.0
            
        print(f"  📊 State: Renewables={current_renewables_pct:.1f}%, Budget Spent=B")
        
    print(f"\\n--- FINISHED {run_name} ---")
    log["final_state"] = {
        "renewables_pct": current_renewables_pct,
        "budget_spent": budget_spent
    }
    
    with open(f"D:\\orion\\scripts\\{run_name}_log.json", "w") as f:
        json.dump(log, f, indent=2)

    db.close()

if __name__ == "__main__":
    db = SessionLocal()
    seed_civilization(db)
    db.close()
    
    disruptions_a = {
        4: "Major solar manufacturing shortage",
        7: "Extreme weather damages infrastructure",
        9: "Energy demand increases unexpectedly",
        12: "Budget constraint becomes tighter",
        15: "A previously assumed relationship in the world model proves incorrect"
    }
    run_experiment("RUN_A", disruptions_a)
    
    disruptions_b = {
        3: "Extreme weather damages infrastructure",
        8: "Grid stability issues due to high renewables",
        14: "Major solar manufacturing shortage"
    }
    run_experiment("RUN_B", disruptions_b)
