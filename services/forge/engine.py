import uuid
import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from apps.api.database import ForgeExperiment, OmnisObservation

class ForgeEngine:
    \"\"\"
    FORGE: The Scientific Discovery Engine.
    Executes the loop: Hypothesis -> Experiment -> Result -> Evaluation -> Knowledge Update.
    \"\"\"
    
    def __init__(self, db_session: Session):
        self.db = db_session

    def propose_hypothesis(self, hypothesis: str, experiment_design: dict, nexus_task_id: str = None) -> str:
        \"\"\"Step 1: Agent proposes a hypothesis and the required simulation parameters.\"\"\"
        experiment_id = str(uuid.uuid4())
        experiment = ForgeExperiment(
            id=experiment_id,
            hypothesis=hypothesis,
            experiment_design=json.dumps(experiment_design),
            status="PROPOSED",
            nexus_task_id=nexus_task_id
        )
        self.db.add(experiment)
        self.db.commit()
        return experiment_id

    def execute_experiment(self, experiment_id: str):
        \"\"\"Step 2: Send the design to the MIRROR simulation layer (mocked).\"\"\"
        experiment = self.db.query(ForgeExperiment).filter_by(id=experiment_id).first()
        if not experiment:
            raise ValueError(f"Experiment {experiment_id} not found.")
            
        experiment.status = "RUNNING"
        self.db.commit()
        
        # In the future, this calls MIRROR. For now, we simulate an async dispatch.
        return True

    def record_result(self, experiment_id: str, result_data: dict, evaluation_score: float):
        \"\"\"Step 3 & 4: Record the result and the evaluation of the hypothesis.\"\"\"
        experiment = self.db.query(ForgeExperiment).filter_by(id=experiment_id).first()
        experiment.result_data = json.dumps(result_data)
        experiment.evaluation_score = evaluation_score
        experiment.status = "EVALUATED"
        experiment.completed_at = datetime.now(timezone.utc)
        self.db.commit()

    def update_knowledge_graph(self, experiment_id: str, target_entity_id: str):
        \"\"\"Step 5: If the hypothesis is validated, update OMNIS with the new knowledge.\"\"\"
        experiment = self.db.query(ForgeExperiment).filter_by(id=experiment_id).first()
        if experiment.evaluation_score < 0.8:
            return False # Not enough confidence to update the world model
            
        # Write the empirical finding into the OMNIS world model
        new_observation = OmnisObservation(
            id=str(uuid.uuid4()),
            entity_id=target_entity_id,
            state_data=json.dumps({
                "scientific_finding": experiment.hypothesis,
                "evidence_id": experiment.id,
                "score": experiment.evaluation_score
            }),
            provenance="FORGE_ENGINE"
        )
        
        self.db.add(new_observation)
        self.db.commit()
        return True
