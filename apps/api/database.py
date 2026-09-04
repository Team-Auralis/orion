import os
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, DateTime, Text, Boolean, Integer, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL", 
    "postgresql://orion_admin:LOCAL_DEV_SECRET@localhost:5433/keycloak"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class Incident(Base):
    __tablename__ = "incidents"

    id = Column(String, primary_key=True, index=True)
    type = Column(String, nullable=False)
    status = Column(String, nullable=False, default="CREATED")
    user_id = Column(String, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    message = Column(Text, nullable=True)
    ai_severity = Column(String, nullable=True)
    ai_tags = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class Asset(Base):
    __tablename__ = "assets"
    
    asset_id = Column(String, primary_key=True, index=True)
    type = Column(String, nullable=False) # FIRE_TRUCK, AMBULANCE, POLICE
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    target_incident_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="OFFLINE") # OFFLINE, IDLE, DISPATCHED, EN_ROUTE, ON_SCENE, RETURNING, MAINTENANCE
    version = Column(Integer, nullable=False, default=1)
    
    __mapper_args__ = {
        "version_id_col": version
    }

class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    key = Column(String, primary_key=True, index=True)
    response_body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class BreakGlassSession(Base):
    __tablename__ = "break_glass_sessions"
    
    token = Column(String, primary_key=True, index=True)
    user_id = Column(String, nullable=False)
    reason = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False)

class OutboxEvent(Base):
    __tablename__ = 'outbox_events'
    id = Column(String, primary_key=True)
    topic = Column(String, nullable=False)
    payload = Column(Text, nullable=False)
    headers = Column(Text, nullable=True)
    published = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class DispatchRecommendation(Base):
    __tablename__ = 'dispatch_recommendations'
    id = Column(String, primary_key=True)
    incident_id = Column(String, nullable=False)
    recommended_asset_id = Column(String, nullable=False)
    reason = Column(String, nullable=True)
    status = Column(String, default='PENDING')
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(String, nullable=True)
    version = Column(Integer, nullable=False, default=1)

    __mapper_args__ = {
        "version_id_col": version
    }

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
class OmnisEntity(Base):
    __tablename__ = 'omnis_entities'
    id = Column(String, primary_key=True)
    type = Column(String, nullable=False) # e.g. INFRASTRUCTURE, CITY, CLIMATE
    name = Column(String, nullable=False)
    attributes = Column(Text, nullable=True) # JSON blob of attributes
    confidence = Column(Float, default=1.0) # Uncertainty measure
    provenance = Column(String, nullable=False) # Which agent/sensor provided this
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class OmnisRelationship(Base):
    __tablename__ = 'omnis_relationships'
    id = Column(String, primary_key=True)
    source_id = Column(String, nullable=False)
    target_id = Column(String, nullable=False)
    type = Column(String, nullable=False) # e.g. CAUSES, SUPPLIES_TO, DEPENDS_ON
    weight = Column(Float, default=1.0) # Strength of the relationship or causal link
    confidence = Column(Float, default=1.0)
    provenance = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class OmnisObservation(Base):
    __tablename__ = 'omnis_observations'
    id = Column(String, primary_key=True)
    entity_id = Column(String, nullable=False)
    state_data = Column(Text, nullable=False) # JSON blob of the observed state
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    provenance = Column(String, nullable=False)

class NexusAgent(Base):
    __tablename__ = 'nexus_agents'
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    capabilities = Column(Text, nullable=False) # JSON list of capabilities
    status = Column(String, nullable=False, default="IDLE") # IDLE, WORKING, OFFLINE
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class NexusTask(Base):
    __tablename__ = 'nexus_tasks'
    id = Column(String, primary_key=True)
    parent_task_id = Column(String, nullable=True) # For hierarchical decomposition
    description = Column(Text, nullable=False)
    assigned_agent_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="PENDING") # PENDING, IN_PROGRESS, CONFLICT, RESOLVED
    result = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime(timezone=True), nullable=True)

class ForgeExperiment(Base):
    __tablename__ = 'forge_experiments'
    id = Column(String, primary_key=True)
    hypothesis = Column(Text, nullable=False)
    experiment_design = Column(Text, nullable=False) # JSON defining the sim parameters
    status = Column(String, nullable=False, default="PROPOSED") # PROPOSED, RUNNING, EVALUATED, FAILED
    result_data = Column(Text, nullable=True) # Output from the MIRROR simulation
    evaluation_score = Column(Float, nullable=True) # How successful was the hypothesis?
    nexus_task_id = Column(String, nullable=True) # The agent task driving this experiment
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)
