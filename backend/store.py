"""Store: JSON file today, Postgres tomorrow.

WHY a file: zero setup for teammates — clone + run, no database to install.
Every request calls load_db() fresh, so no in-memory sync bugs.
Swap path: set DATABASE_URL + replace these two functions; haversine math in
scoring.py already mirrors ST_Distance, so rankings won't change.
"""
import json
import random
import uuid
from datetime import datetime
from pathlib import Path

from catalog import MATERIAL_META

BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "data.json"
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


def load_db():
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except Exception:
            pass
    return {"listings": [], "requests": []}


def save_db(db):
    DATA_FILE.write_text(json.dumps(db, indent=2))


def seed_if_empty():
    """First run: 6 Bengaluru listings so search/match/impact work immediately."""
    db = load_db()
    if db["listings"]:
        return db
    seed = [
        {"material": "Wood", "quantity": 500, "condition": "Good", "price_per_unit": 150,
         "lat": 12.9716, "lng": 77.5946, "address": "Koramangala, Bengaluru", "contractor": "Sharma Demolition Co.",
         "title": "Reclaimed Teak Wood — 500 sq ft", "description": "Teak beams from 1980s residential demolition. De-nailed, clean."},
        {"material": "Bricks", "quantity": 4000, "condition": "Fair", "price_per_unit": 12,
         "lat": 12.9352, "lng": 77.6245, "address": "HSR Layout, Bengaluru", "contractor": "Nandi Wreckers",
         "title": "Red Clay Bricks — 4000 pcs", "description": "Hand-cleaned red clay bricks, minor mortar residue."},
        {"material": "Metal", "quantity": 850, "condition": "Good", "price_per_unit": 85,
         "lat": 12.9784, "lng": 77.6408, "address": "Indiranagar, Bengaluru", "contractor": "Sharma Demolition Co.",
         "title": "Structural Steel — 850 kg", "description": "MS angles + pipes, rust-free, cut to 6ft lengths."},
        {"material": "Doors", "quantity": 14, "condition": "Excellent", "price_per_unit": 2500,
         "lat": 12.9539, "lng": 77.5805, "address": "Jayanagar, Bengaluru", "contractor": "Kaveri Dismantlers",
         "title": "Rosewood Doors — 14 pcs", "description": "Solid rosewood doors with brass fittings intact."},
        {"material": "Windows", "quantity": 22, "condition": "Good", "price_per_unit": 3200,
         "lat": 13.0035, "lng": 77.5891, "address": "Hebbal, Bengaluru", "contractor": "Nandi Dismantlers",
         "title": "Aluminium Windows — 22 pcs", "description": "Sliding aluminium windows, glass intact."},
        {"material": "Concrete", "quantity": 300, "condition": "Fair", "price_per_unit": 95,
         "lat": 12.9141, "lng": 77.6101, "address": "BTM Layout, Bengaluru", "contractor": "Kaveri Dismantlers",
         "title": "Concrete Slabs — 300 cu ft", "description": "Crushed concrete aggregate-ready slabs."},
    ]
    for s in seed:
        meta = MATERIAL_META[s["material"]]
        s.update({
            "id": str(uuid.uuid4())[:8],
            "unit": meta["unit"],
            "confidence": round(random.uniform(0.82, 0.97), 2),
            "status": "active",
            "created_at": datetime.utcnow().isoformat(),
            "image_url": None,
        })
    db["listings"] = seed
    save_db(db)
    return db
