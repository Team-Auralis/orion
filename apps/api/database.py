import os
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, DateTime, Text, Boolean, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL", 
    "postgresql://orion_admin:orion_password@localhost:5433/keycloak"
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
    status = Column(String, nullable=False, default="IDLE") # IDLE, DISPATCHED, ON_SCENE

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

# Production: We now use Alembic for migrations instead of auto-creating.
# Base.metadata.create_all(bind=engine) is removed to prevent schema collision.

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
