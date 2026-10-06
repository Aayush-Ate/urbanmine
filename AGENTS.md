# AGENTS.md — working in UrbanMine

## Commands

```bash
# backend (conda python — plain python3 lacks torch/ultralytics)
cd backend && /opt/homebrew/anaconda3/bin/python -m uvicorn main:app --port 8000
# frontend
cd frontend && npm run dev   # → http://localhost:5173
# tests (stdlib only, no models, runs in seconds — run from backend/)
cd backend && /opt/homebrew/anaconda3/bin/python -m unittest discover -s tests -v
```

Full runbook: `README.md`. Full module reference: `PROJECT-FULLSTACK.md`. Terms: `GLOSSARY.md`.

## Module map (one question per file)

| Module | Interface | What stays inside |
|--------|-----------|-------------------|
| `backend/catalog.py` | material names, units, prices, prompts, gates | Nothing computed — data only. Change a price or prompt here. |
| `backend/vision.py` | `detect_materials(bytes)`, `downscale_for_ai(bytes)` | All model loading (lazy: fast import, slow first photo). Never import models at module top level. |
| `backend/store.py` | `load_db()`, `save_db(db)`, `seed_if_empty()` | JSON file shape. Reads fresh every call — no in-memory cache. |
| `backend/scoring.py` | `haversine_km`, `qty_for`, `match_score` | Pure math, no I/O. This is the seam tests pin. |
| `backend/schemas.py` | request shapes | Pydantic only, no logic. |
| `backend/main.py` | HTTP routes | Thin mapping only — no AI, no math, no file I/O beyond saving the upload. |

Seams: `scoring.py` and `catalog.py` are safe to test and change freely. `vision.py` needs downloaded weights (~150MB, first run) — don't gate tests on it. `store.py` touches `data.json` — tests use temp dirs, never the real file.

## Conventions

- Every tricky block gets a WHY comment (reason, not narration). One-line comments; no long chain-of-thought in code.
- `main.py` stays thin: a route parses input, calls one module function, returns. Logic leaking into routes is the smell to watch for.
- Quantities derive from measured coverage (`qty_for`) — never `random`, never hardcoded, except seed confidences.
- Household-looking frames must never produce listings: any new detection path goes through the CLIP gate or documents why it doesn't.
- New domain words go in `GLOSSARY.md` first, code second.
- No new backend dependency without a note in the PR/commit message saying what breaks without it.
