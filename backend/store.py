"""Listings and requests live in Postgres when DATABASE_URL is set.

Without DATABASE_URL they live in data.json, so local dev needs no database.
The rest of the app only calls load_db() and save_db(), so it does not care
which one is active.

The Postgres shape is one JSONB row. That keeps the MVP simple and means the
same dict goes in and comes out. It is not built for heavy write traffic:
two workers saving at the same moment can overwrite each other. For a real
launch, split listings and requests into proper tables and update rows by id.
"""
import json
import os
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path

from catalog import MATERIAL_META

BASE_DIR = Path(__file__).parent
DATA_FILE = Path(os.getenv("DATA_FILE") or (BASE_DIR / "data.json"))
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR") or (BASE_DIR / "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS urbanmine_state (
    id INTEGER PRIMARY KEY,
    data JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def _pg_connect():
    # one short connection per call. Neon likes this and there is no pool to leak.
    try:
        import psycopg
    except ImportError:
        raise RuntimeError(
            "DATABASE_URL is set but psycopg is missing. "
            "Run: pip install 'psycopg[binary]'"
        )
    return psycopg.connect(DATABASE_URL, autocommit=True)


def load_db():
    if DATABASE_URL:
        with _pg_connect() as conn:
            conn.execute(CREATE_TABLE)
            row = conn.execute("SELECT data FROM urbanmine_state WHERE id = 1").fetchone()
        if row:
            return row[0] if isinstance(row[0], dict) else json.loads(row[0])
        return {"listings": [], "requests": []}

    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except Exception:
            pass
    return {"listings": [], "requests": []}


def save_db(db):
    if DATABASE_URL:
        from psycopg.types.json import Jsonb
        with _pg_connect() as conn:
            conn.execute(CREATE_TABLE)
            conn.execute(
                "INSERT INTO urbanmine_state (id, data) VALUES (1, %s) "
                "ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, updated_at = now()",
                (Jsonb(db),),
            )
        return

    DATA_FILE.write_text(json.dumps(db, indent=2))


def seed_if_empty():
    """First run only: six Bengaluru listings, so search and matching work
    before anyone uploads a photo."""
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
            "created_at": datetime.now(timezone.utc).isoformat(),
            "image_url": None,
        })
    db["listings"] = seed
    save_db(db)
    return db
