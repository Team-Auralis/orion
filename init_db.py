from apps.api.database import Base, engine
Base.metadata.create_all(bind=engine)
print("Database initialized.")
