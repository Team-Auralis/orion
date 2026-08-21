import os
from sqlalchemy.orm import Session
from database import engine, Asset

def seed():
    print("Seeding ATLAS GEO Planetary Mesh...")
    
    # Generate a planetary grid of Global Sentinel Outposts
    # Spacing by 10 degrees lat/lon yields 36 * 18 = 648 global outposts covering every inch of the earth.
    assets = []
    station_count = 1
    
    for lat in range(-90, 91, 10):
        for lon in range(-180, 181, 10):
            # Alternate types for variety
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
    
    with Session(engine) as db:
        # Wipe old local dummy assets first to upgrade to planetary scale
        db.query(Asset).delete()
        
        # Batch insert for speed
        db.bulk_insert_mappings(Asset, assets)
        db.commit()
    print("Planetary Seeding complete. Earth is fully covered.")

if __name__ == "__main__":
    seed()
