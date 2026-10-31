# AGENTS.md — working in UrbanMine

## Commands

```bash
# backend → http://localhost:8000  (docs at /docs)
cd backend && python -m uvicorn app.main:app --port 8000

# frontend → http://localhost:5173
cd frontend && npm run dev

# tests: stdlib unittest, models stubbed, a few seconds
cd backend && python -m unittest discover -s tests -v

# container, if you would rather not install torch locally
docker build -t urbanmine-api backend && docker run --rm -p 8000:8000 urbanmine-api
```

The backend needs an interpreter with torch, ultralytics and transformers. A bare
system python does not have them.

Docs: `README.md` to run it, `docs/DECISIONS.md` for why anything is the way it
is, `docs/PROJECT-FULLSTACK.md` for the module-by-module reference,
`docs/DEPLOY.md` for hosts and deploy commands.

## Where things live

One question per file. If you cannot say in one sentence what question a file
answers, it is doing too much.

| Module | Interface | What stays inside |
|---|---|---|
| `backend/app/main.py` | HTTP routes | Thin mapping only. No AI, no maths, no file I/O beyond saving the upload. |
| `backend/app/schemas.py` | request shapes | Pydantic only, no logic. |
| `backend/app/core/catalog.py` | material names, units, prices, prompts, gates | Data only. Change a price or a prompt here. |
| `backend/app/core/scoring.py` | `haversine_km`, `qty_for`, `match_score` | Pure maths, no I/O. This is the seam the tests pin. |
| `backend/app/ai/vision.py` | `detect_materials(bytes)`, `downscale_for_ai(bytes)` | All model loading, lazily. Never import a model at module top level. |
| `backend/app/storage/store.py` | `load_db()`, `save_db(db)`, `save_image`, `load_image`, `delete_image` | The Postgres/JSON seam. Reads fresh every call, no cache. |
| `backend/app/storage/images.py` | `photo_jpeg(raw, max_side, quality)` | One bounded copy, one thumbnail. Pillow only. |
| `frontend/src/App.jsx` | shell and five panels | Layout and API calls. Sizing maths belongs in `lib/measureMath.js`. |
| `frontend/src/lib/cesium.js` | `createViewer`, `flyTo`, `setPins` | Every Cesium quirk, in one place. |

Safe to change freely: `scoring.py` and `catalog.py`. `vision.py` needs about
150MB of weights on first run, so never gate the test suite on it. Tests that
touch storage use temp directories and must never write the real `data.json`.

## Conventions

- Every tricky block gets a WHY comment — the reason, not narration. One or two
  lines. No long chain-of-thought in code.
- `main.py` stays thin: a route parses input, calls one function, returns. Logic
  leaking into a route is the smell to watch for.
- Quantities derive from measured coverage (`qty_for`) or a measurement. Never
  `random`, never hardcoded.
- A household-looking frame must never produce a listing. Any new detection path
  goes through the CLIP gate, or the comment says why it does not.
- No new backend dependency without a note saying what breaks without it.
- Keep the docs honest. If a path, command, or alias changes, change it in
  `README.md` and the matching file under `docs/` in the same commit. A stale
  path in a runbook costs more than the change did.
