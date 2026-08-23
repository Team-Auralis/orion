import os
from sqlalchemy.orm import Session
from database import engine, Asset

def seed():
    if os.environ.get("SEED_DB") != "1":
        print("SEED_DB not set. Skipping planetary seeding.")
        return
        
    print("Seeding ATLAS GEO Planetary Mesh...")
    
    with Session(engine) as db:
        if db.query(Asset).first():
            print("Assets already exist. Skipping seeding to preserve live data.")
            return

        # Generate a planetary grid of Global Sentinel Outposts
        assets = []
        station_count = 1
        
        for lat in range(-90, 91, 10):
            for lon in range(-180, 181, 10):
                type_str = "GLOBAL_SENTINEL_DRONE" if (lat + lon) % 20 == 0 else "ORBITAL_DROP_POD"
                assets.append({
                    "asset_id": f"NODE-{lat}-{lon}",
                    "type": type_str,
                    "latitude": float(lat),
                    "longitude": float(lon),
                    "status": "IDLE"
                })
                station_count += 1
                
        print(f"Generated {len(assets)} planetary defense nodes.")
        
        db.bulk_insert_mappings(Asset, assets)
        db.commit()
    print("Planetary Seeding complete. Earth is fully covered.")

if __name__ == "__main__":
    seed()
