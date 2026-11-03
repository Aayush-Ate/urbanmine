# UrbanMine — Demo runbook

Live URLs
- App: `https://fullstackproject-app.vercel.app`
- Backend health: `https://backend-delta-green-77.vercel.app/api/health`
- Backend listings: `https://backend-delta-green-77.vercel.app/api/listings`

Repo on disk: `/Users/aayush/urbanmine`

## What the demo does

1. **Upload tab** — drop a demolition photo. AI names the salvage materials, draws a box around each one, and the counter shows `checked / rejected / kept`.
2. **Marketplace tab** — real listings with photos, distance, price, condition. Click a listing to open its photo full-screen.
3. **Smart Match tab** — buyer filters material / qty / condition / radius, backend ranks listings `material 40 + quantity 25 + distance 20 + condition 15`.
4. **Requests tab** — buyer clicks "Request Material" → contractor sees it → Accept / Decline.
5. **Household guard** — a bedsheet, a pen, a person, or a bedroom photo returns **no listing**. This is the thing to show first.

## Local run (demo on your laptop)

Two terminals. Backend first.

Terminal 1 — backend:
```bash
cd /Users/aayush/urbanmine/backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000
```
→ `http://localhost:8000` (docs at `/docs`)
→ health check: `curl -s http://localhost:8000/api/health`

Terminal 2 — frontend:
```bash
cd /Users/aayush/urbanmine/frontend
npm install
npm run dev
```
→ `http://localhost:5173`

The frontend proxies `/api` and `/uploads` to port 8000, so no CORS and no cross-origin calls.

**First photo is slow** (~60 s) because torch, ultralytics, and transformers download the YOLO and CLIP weights. Every photo after that is seconds.

Phone on same Wi-Fi: `HTTPS=1 npm run dev -- --host`, then open `https://<mac-lan-ip>:5173` and accept the self-signed cert. HTTPS unlocks camera + geolocation on mobile.

## Production

Frontend: Vercel, project `fullstackproject`, aliased to `fullstackproject-app.vercel.app`.
Backend: Vercel container runtime, project `backend`, aliased at `backend-delta-green-77.vercel.app`.
Database: Neon Postgres (no PostGIS needed — distance is haversine in `backend/app/core/scoring.py`).

`frontend/vercel.json` rewrites `/api` and `/uploads` to the backend alias, so the browser talks to one URL only.

Deploy commands (run from the repo root):
```bash
cd backend
vercel deploy --prod --yes --project backend

cd ../frontend
vercel deploy --prod --yes --project fullstackproject
vercel alias set <frontend-deployment-url> fullstackproject-app.vercel.app
```

The alias does **not** follow new deployments — always run `vercel alias set` after a frontend deploy.

## Where the data lives

`backend/app/storage/store.py` checks `DATABASE_URL`.
- Set it → Postgres (Neon), photos stored as `BYTEA` rows next to listings. Survives a cold start.
- Empty → `backend/data.json` + `backend/uploads/` folder. Fast locally, but uploads vanish when the host wipes its disk.

`/api/health` reports `"store": "postgres"` or `"store": "json"`.

## Demo checklist

Before you go on:

- [ ] Pen photo → zero detections, `is_construction_site: false`, counter `1 rejected / 0 kept`
- [ ] Bedsheet / bedroom / person photo → no listing
- [ ] Real bricks / wood / door photo → detections with boxes, counter shows `kept`
- [ ] Confirm a detection → it appears in Marketplace with its photo
- [ ] Marketplace photo loads (not 404) after a page reload — proves Postgres image storage
- [ ] Smart Match: pick Wood, 500 qty, Good condition, 50 km → ranked results with score %
- [ ] Request Material on a listing → appears in Requests tab as `pending`
- [ ] Accept / Decline → status flips
- [ ] DELETE `/api/listings/{id}` removes a listing and its photos

If photos 404 on the live site after a while, that's the json-mode disk wipe. Production is Postgres-backed, so it shouldn't happen there.

## What not to demo

- **Impact tab** — removed end to end (`/api/impact` is 404, no CO₂ fields, no Impact panel).
- **"Work in progress" on tabs 3 and 4** — Smart Match and Requests currently show only the yellow sticky note ("This website is a work in progress…"). The forms and accept buttons are not rendered there yet. If you need to show requests end-to-end, say so and I'll swap the WIP panels back in.

## Tests (green before demo)

```bash
cd /Users/aayush/urbanmine/backend
python -m unittest discover -s tests -v
```
40 tests, stdlib `unittest`, models stubbed, a few seconds. AI is stubbed so a green run means routes, scoring, sizing, and the store are fine — not that the models behave on your photo.

## Files that matter for demo day

| File | What it answers |
|---|---|
| `backend/app/main.py` | All HTTP routes (`/api/analyze`, `/api/listings`, `/api/match`, `/api/requests`, `/api/materials`, `/api/health`, `/uploads/{id}`) |
| `backend/app/ai/vision.py` | The four AI passes (YOLOv8n, YOLO-World, colour, CLIP) + household gate |
| `backend/app/core/scoring.py` | `haversine_km`, `qty_for`, `match_score` |
| `backend/app/core/catalog.py` | 16 materials, units, salvage prices, CO2 factors, prompts |
| `backend/app/storage/store.py` | Postgres / JSON seam + `save_image` / `load_image` / `delete_image` |
| `frontend/src/App.jsx` | Shell + Upload / Market / Match / Requests panels |
| `frontend/src/LocationPicker.jsx` | Address search, area presets, device GPS, map tap |
| `frontend/src/components/MeasureModal.jsx` | Photo ruler — length × width → quantity |

No API keys required for anything to run. Keys only upgrade the map tiles and the geocoder.
