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
from pathlib import Path

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
