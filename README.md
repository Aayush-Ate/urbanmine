# UrbanMine — B2B demolition-reuse marketplace (MVP)

TL;DR:
- Contractors photograph a demolition site, AI lists salvageable materials with quantities, one click publishes a listing, buyers search and match by material, quantity, distance, and condition.
- Stack: React 18 + Vite 5, FastAPI on conda python, YOLO-World-m + YOLOv8n + color pass + CLIP gate, JSON file store (PostGIS path tested), Cesium satellite globes.
- Run it: backend `:8000`, frontend `:5173`. Everything works keyless; keys only upgrade maps and geocoding.

## 1. Run

Terminal 1 — backend (`http://localhost:8000`, docs at `/docs`):

```bash
cd urbanmine/backend
/opt/homebrew/anaconda3/bin/python -m pip install -r requirements.txt
/opt/homebrew/anaconda3/bin/python -m uvicorn main:app --port 8000
```

Terminal 2 — frontend (`http://localhost:5173`):

```bash
cd urbanmine/frontend
npm install
npm run dev
```

Notes: use the conda python — plain `python3` lacks torch/ultralytics. First photo takes ~1 min (model download + load), then seconds. Check both:

```bash
curl -s http://localhost:8000/api/health && curl -s -o /dev/null -w "frontend: %{http_code}\n" http://localhost:5173
```

## 2. How it fits together

```
photo → Upload tab → POST /api/analyze → edit → POST /api/listings
buyer → Marketplace (GET /api/listings) / Smart Match (POST /api/match)
      → POST /api/requests → contractor accepts → Impact (GET /api/impact)
```

Match score: material 40, quantity 25, distance 20 (zero past 50 km), condition 15.

## 3. Backend — 5 small files, not one big one

`backend/main.py` holds only routes. Logic lives next to it:

| File | Answers | Key names |
|------|---------|-----------|
| `catalog.py` | What is a material, what is it worth | `MATERIAL_META` (16 mats, unit/price/CO2/icon), `WORLD_PROMPTS` (~60 descriptive phrases), `WORLD_IGNORE` (walls/ceilings to discard), `WORLD_NONCON` (people/pets/clothes, never listed), `COCO_TO_MATERIAL`, `FULL_QTY`, `CLIP_GATE` 0.60 |
| `vision.py` | What is in this photo | `yolo_infer` ( everyday objects → Wood/Metal), `world_infer` (prompts → 16 mats), `visual_estimate` (pixel colors, no net), `clip_check` (construction-or-household per crop), `detect_materials` (merges all four, shares to 100%), `downscale_for_ai` |
| `store.py` | Where listings live | `load_db`, `save_db`, `seed_if_empty` (6 Bengaluru listings first run) |
| `scoring.py` | How good a match, how much there is | `haversine_km` (same math as PostGIS), `qty_for` (coverage × base, never random), `match_score` |
| `schemas.py` | What JSON is valid | `ListingConfirm`, `ListingPatch`, `MatchRequest`, `BuyerRequest`, `RequestPatch` |

Pipeline per photo: downscale to 1280px (original kept) → World-m (91 prompts, conf 0.12) + YOLOv8n in parallel → color pass (suppressed on fabric frames) → CLIP verifies weak boxes, strong COCO ≥0.50 trusted → fallback Concrete only on construction-looking frames with nothing found, labeled as a guess. Response: `detections[]` (material, qty, unit, condition, confidence, share, price, source), `non_construction[]`, `is_construction_site`.

Proven controls: bedsheet rejected, bus → Metal + people, brick stack → Bricks with 6 verified boxes. Stuck on a result: `POST /api/analyze?debug=1` with `debug=true` returns `world_raw`, `coco_raw`, `clip_frame_p`, `rejected`, `fallback_used`.

## 4. Frontend — one file per concern

- `src/App.jsx` — shell (sidebar ≥900px, bottom tabs below) + 5 panels: Upload (EXIF GPS via exifr, canvas shrink to 1600px JPEG, auto-analyze, editable detections, confirm), Marketplace (filters + request buttons + globe pins), Smart Match (ranked rows, score dials), Requests (accept/decline), Impact (4 cards + math note).
- `src/LocationPicker.jsx` — nobody types coordinates: search (HERE first, Nominatim fallback), 12 presets, device GPS, map tap, draggable pin. Every move reverse-geocodes.
- `src/cesium.js` — `createViewer` (ion imagery if token, else keyless Esri satellite), `flyTo`, `setPins`.
- `src/main.jsx`, `src/styles.css` — root + The1 tokens (concrete `#d9d9d9`, iron `#1f1f1f`, flat, no shadows).
- `API = VITE_API_BASE || ''` (`App.jsx:7`): dev uses the Vite proxy to `:8000`; share builds bake the tunnel URL.

## 5. API

Base `http://localhost:8000`. 404s are `{"detail": "..."}`.

| Method + path | In | Out |
|---------------|----|-----|
| `GET /api/health` | — | status, yolo/world flags, counts |
| `POST /api/analyze` | multipart `file`, `lat`, `lng`, `address`, `debug?` | `image_url`, `detections[]`, `non_construction[]`, `is_construction_site`, `model` |
| `POST /api/listings` | material, quantity, unit?, condition?, price?, lat/lng/address/contractor… | created listing, 8-char id |
| `GET /api/listings` | material?, condition?, q?, lat?, lng?, max_distance_km=100 | active listings, nearest-first with `distance_km` |
| `GET / PATCH /api/listings/{id}` | patch: quantity?, condition?, price?, status? | one listing |
| `POST /api/match` | material, quantity=100, lat, lng, condition?, max_distance_km=50 | top 20 with `match_score`, `distance_km` |
| `POST /api/requests`, `GET /api/requests`, `PATCH /api/requests/{id}` | listing_id, buyer_name, … / status | pending → accepted/declined |
| `GET /api/impact` | — | tonnes (qty×CO2/1000), value (lakh/Cr), matches (43 seed + live) |
| `GET /api/materials` | — | 16 materials, drives the dropdowns |
| `GET /uploads/{file}` | — | stored photo |

## 6. Keys (all optional)

| Var | Where | Without it |
|-----|-------|------------|
| `VITE_CESIUM_TOKEN` | `frontend/.env` | keyless Esri globe instead of ion terrain/3D tiles |
| `VITE_GOOGLE_TILES_ASSET_ID` | `frontend/.env` | satellite globe instead of photorealistic 3D |
| `VITE_HERE_API_KEY` | `frontend/.env` | Nominatim geocoding (rate-limited) instead of HERE |
| `DATABASE_URL` | backend env | JSON file instead of PostGIS (§7) |
| `VITE_API_BASE` | build-time only | localhost proxy instead of tunnel (share builds only) |

## 7. Data: file today, PostGIS tomorrow

`backend/data.json`, seeded on first run. Distance uses haversine — identical to `ST_Distance(geography)/1000`, so rankings survive migration. Neon `database_q` tested with PostGIS 3.6.4; cutover DDL is in `PROJECT-FULLSTACK.md` §8.

## 8. Sharing (localhost first)

The backend runs on a laptop, so any share link is a frozen frontend copy wired through a tunnel — it dies on sleep or tunnel restart, and anonymous slugs can't be revived. Demo on localhost; publish only on explicit approval.

- Same Wi-Fi phone: `HTTPS=1 npm run dev -- --host`, open `https://<mac-lan-ip>:5173` (accept cert). Gets camera snap + bottom-tab shell.
- Public link: `cloudflared tunnel --url http://localhost:8000`, then `VITE_API_BASE=<url> npm run build` in `frontend/`, then `scripts/publish-here.py` (reads this clone's `dist/`).

Standing rule: no new link without explicit approval; record the slug here when published.

## 9. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `connection refused :8000` | backend not running — §1 terminal 1, conda python |
| `Analysis failed` | backend down or file >25MB — check terminal 1 log |
| First photo slow | normal — models loading |
| `No GPS tag` | screenshots have none — use search/preset/GPS/map |
| Dark globe | Cesium CDN unreachable — pickers still work |
| Port busy | `lsof -ti:5173 \| xargs kill` (same for 8000) |
| Old UI | `⌘⇧R`; dev hot-reloads, `dist/` only matters for preview |

## 10. Layout

```
urbanmine/
├── README.md, PROJECT-FULLSTACK.md, PRD.md/TRD.md (local only), LICENSE (MIT)
├── docker-compose.yml (optional PostGIS), docs/*.excalidraw.json
├── backend/ main.py (routes) · catalog.py · vision.py · store.py · scoring.py · schemas.py
└── frontend/ index.html · vite.config.js · src/ · scripts/publish-here.py
```

Not in git: `node_modules`, `dist`, `*.pt` (auto-download), `uploads/`, logs, `.env`.
