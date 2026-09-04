import uuid
import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from apps.api.database import NexusAgent, NexusTask

class NexusFabric:
    \"\"\"
    NEXUS: The Multi-Agent Intelligence Fabric.
    Coordinates heterogeneous agents, handles capability discovery, 
    and manages task decomposition and dispute resolution.
    \"\"\"
    
    def __init__(self, db_session: Session):
        self.db = db_session

    def register_agent(self, name: str, capabilities: list[str]) -> str:
        \"\"\"Register a new specialized agent into the civilization fabric.\"\"\"
        existing = self.db.query(NexusAgent).filter_by(name=name).first()
        if existing:
            existing.capabilities = json.dumps(capabilities)
            existing.status = "IDLE"
            agent_id = existing.id
        else:
            agent_id = str(uuid.uuid4())
            new_agent = NexusAgent(
                id=agent_id,
                name=name,
                capabilities=json.dumps(capabilities),
                status="IDLE"
            )
            self.db.add(new_agent)
        
        self.db.commit()
        return agent_id

    def delegate_task(self, description: str, parent_task_id: str = None, required_capability: str = None) -> str:
        \"\"\"
        Decompose and delegate a task to an available agent with the required capability.
        \"\"\"
        task_id = str(uuid.uuid4())
        
        # 1. Capability Discovery
        assigned_agent = None
        if required_capability:
            # In a real distributed system, we would query active agents and load balance.
            agents = self.db.query(NexusAgent).filter_by(status="IDLE").all()
            for agent in agents:
                caps = json.loads(agent.capabilities)
                if required_capability in caps:
                    assigned_agent = agent
                    break
        
        # 2. Task Assignment
        new_task = NexusTask(
            id=task_id,
            parent_task_id=parent_task_id,
            description=description,
            assigned_agent_id=assigned_agent.id if assigned_agent else None,
            status="PENDING" if assigned_agent else "UNASSIGNABLE"
        )
        
        if assigned_agent:
            assigned_agent.status = "WORKING"
            
        self.db.add(new_task)
        self.db.commit()
        
        return task_id

    def resolve_dispute(self, task_id: str, final_result: str):
        \"\"\"
        When agents conflict, the Nexus fabric acts as the ultimate arbiter,
        recording the final aggregated consensus.
        \"\"\"
        task = self.db.query(NexusTask).filter_by(id=task_id).first()
        if not task:
            raise ValueError(f"Task {task_id} not found.")
            
        task.status = "RESOLVED"
        task.result = final_result
        task.resolved_at = datetime.now(timezone.utc)
        
        if task.assigned_agent_id:
            agent = self.db.query(NexusAgent).filter_by(id=task.assigned_agent_id).first()
            if agent:
                agent.status = "IDLE"
                
        self.db.commit()
