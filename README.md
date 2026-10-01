# UrbanMine — B2B demolition-reuse marketplace (MVP)

Contractors photograph demolition sites, AI identifies salvageable materials,
and salvage becomes priced marketplace listings for architects, builders, and
interior designers. An impact dashboard totals waste diverted and value recovered.

**Status:** working MVP, localhost-first. Clone it, run two commands, open
`http://localhost:5173`.

## 1. Quick start

```bash
# 1 · backend → http://localhost:8000 (API docs: /docs)
cd urbanmine/backend
pip install -r requirements.txt
/opt/homebrew/anaconda3/bin/python -m uvicorn main:app --port 8000

# 2 · frontend → http://localhost:5173
cd urbanmine/frontend
npm install
npm run dev
```

> Use the conda python for the backend — plain `python3` is missing the AI
> dependencies. First photo takes ~1 min (models loading); after that, seconds.

Verify in one line:

```bash
curl -s http://localhost:8000/api/health && curl -s -o /dev/null -w "frontend: %{http_code}\n" http://localhost:5173
```

Production preview: `npm run build && npm run preview -- --port 5173`.

## 2. What it does (7 steps)

| # | Step | Where | API |
|---|------|-------|-----|
| 1 | Contractor drops a demolition photo | Upload + AI tab | `POST /api/analyze` |
| 2 | AI reads photo GPS (EXIF) + detects materials | Upload + AI tab (auto-runs) | `POST /api/analyze` |
| 3 | Contractor corrects AI output, confirms → live listing | Upload + AI tab | `POST /api/listings` |
| 4 | Buyers search + filter by material, condition, distance | Marketplace tab | `GET /api/listings` |
| 5 | Smart matching scores every listing | Smart Match tab | `POST /api/match` |
| 6 | Buyer requests material; contractor accepts/declines | Marketplace → Requests tabs | `POST/PATCH /api/requests` |
| 7 | Impact dashboard (tonnes, ₹ value, matches) | Impact tab | `GET /api/impact` |

**Match score** = material 40% + quantity 25% + distance 20% + condition 15%.
Distance decays linearly to zero at 50 km (`score_dist = max(0, 1 − km/50)`).

## 3. The five panels

1. **Upload + AI** — `Photo → AI review → Published`. Drop a photo, EXIF-GPS
   extracts, analysis auto-runs with a visible "AI thinking" checklist.
   Detections are fully editable (qty/unit/condition/price) before Confirm.
   `Re-analyse photo` re-runs with the current location.
2. **Marketplace** — buyer-location picker + search/material/condition/distance
   filters + buyer identity + request buttons + Cesium globe with clickable pins.
3. **Smart Match** — material/qty/condition/`Within km` → ranked rows with
   score dials.
4. **Requests** — pending rows carry working **Accept / Decline**. Handshake
   only — no payments.
5. **Impact** — four stat cards + a "how it's computed" note.

Nobody types coordinates, anywhere: address search (Bengaluru-biased,
debounced), 12 area presets, device GPS, click-to-set on the mini-globe,
drag-the-SITE-pin. Every move reverse-geocodes into a human address.

## 4. AI vision

16 materials (Wood, Bricks, Metal, Doors, Windows, Concrete, Plywood, Rebar,
Copper, Aluminium, PVC Pipes, Tiles, Marble, Glass, Gypsum, Sand) via four
passes: **YOLO-World-m** (descriptive open-vocabulary prompts + hard negatives
for intact-room surfaces, conf 0.12) + **YOLOv8n** COCO (furniture→Wood,
vehicles/appliances→Metal) + **color/texture visual pass** + **CLIP domain
gate** (0.60; strong COCO ≥0.50 trusted outright).

Behavior contract, all proven on real photos:

- Living things, clothes, fabric, plastic, people, pets, food are **never**
  listed — they appear under non-construction as transparency.
- A bedsheet is not a site. A bus is Metal + people. A brick stack is Bricks
  with quantities from measured coverage — never random.
- Low-confidence guesses are labeled `fallback (low-confidence guess)`, not facts.
- Detections rank as shares normalized to 100%; dropdowns load live from
  `/api/materials`.

Tuning aid: `POST /api/analyze?debug=1` with form field `debug=true` returns
per-stage raw outputs (`world_raw`, `coco_raw`, `clip_frame_p`, `rejected`,
`fallback_used`).

## 5. API reference

Base `http://localhost:8000`. Error shape on 404: `{"detail": "..."}`.

| Method + path | Body / params | Returns |
|---------------|---------------|---------|
| `GET /api/health` | — | `{status, yolo, world, listings, requests, db, postgis}` |
| `POST /api/analyze` | multipart: `file` (required), `lat`, `lng`, `address`, `debug?` | `{image_url, detections[], model, non_construction[], is_construction_site}` — each detection: `material, icon, quantity, unit, condition, confidence, suggested_price_per_unit, share, source` |
| `POST /api/listings` | `material, quantity, unit?, condition?, price_per_unit?, lat, lng, address, contractor, title?, description?, confidence?` | created listing (`id` = 8-char uid, `status: active`) |
| `GET /api/listings` | `material?, condition?, q?, lat?, lng?, max_distance_km=100` | active listings; with `lat+lng` adds `distance_km`, nearest-first |
| `GET /api/listings/{id}` | — | listing or **404** |
| `PATCH /api/listings/{id}` | `quantity?, condition?, price_per_unit?, status?` | updated listing or **404** |
| `POST /api/match` | `material, quantity=100, lat, lng, condition?, max_distance_km=50` | `{query, weights, results[≤20]}` with `match_score` + `distance_km`, best-first |
| `POST /api/requests` | `listing_id, buyer_name, buyer_type?, quantity?, message?` | created request (`status: pending`) or **404** |
| `GET /api/requests` | — | all requests, newest first |
| `PATCH /api/requests/{id}` | `status` (`accepted` / `declined` / `pending`) | updated request or **404** |
| `GET /api/impact` | — | `{tonnes_diverted, value_recovered_inr, value_recovered_fmt, buyer_matches, active_listings, total_requests}` |
| `GET /api/materials` | — | 16 materials with `unit, price, co2_per_unit_kg, icon` |
| `GET /uploads/{file}` | — | stored analyzed photo |

**Impact math:** tonnes = Σ qty × material CO₂ factor ÷ 1000 · value = Σ qty ×
price (formatted `₹x.x lakh` / `₹x.xx Cr`) · matches = 43 (seed) + live requests.

```bash
curl -s "http://localhost:8000/api/listings?material=Wood" | head -c 300; echo
curl -s -X POST http://localhost:8000/api/match -H 'Content-Type: application/json' \
  -d '{"material":"Wood","quantity":500,"lat":12.9716,"lng":77.5946}'
```

## 6. Config & keys

Everything works with zero keys. Keys only upgrade visuals and geocoding.

| Var | Where | Effect if set |
|-----|-------|---------------|
| `VITE_CESIUM_TOKEN` | `frontend/.env` (copy `.env.example`) | Cesium ion world imagery + true terrain + 3D tiles. Absent → keyless Esri satellite globe. Free token: `https://ion.cesium.com/tokens` |
| `VITE_GOOGLE_TILES_ASSET_ID` | `frontend/.env` | Photorealistic 3D tiles via ion Asset Depot (needs ion token too) |
| `VITE_HERE_API_KEY` | `frontend/.env` | HERE geocoding (India-biased). Absent → OSM Nominatim fallback (rate-limited). Free tier: developer.here.com |
| `DATABASE_URL` | backend env | Real PostGIS instead of JSON store (§8) |
| `VITE_API_BASE` | build-time only | Tunnel URL for share builds (§9). Never needed for localhost |

## 7. Maps & globes

- Cesium 1.119 via CDN, built with the native `fromBasemapType(SATELLITE)`
  factory; atmosphere + sun lighting always on; amber pins with material labels.
- A small ArcGIS credit notice shows until you set
  `Cesium.ArcGisMapService.defaultAccessToken` (free ArcGIS Developer key).
- If the Cesium CDN is unreachable, globes render a dark panel but all pickers
  (search/preset/GPS) keep working.
- Motion is GSAP entrance-only, `prefers-reduced-motion` kills it all.
- Accessibility is a ship-blocker here: skip link, `tablist` semantics,
  keyboard-focusable dropzone, `role="alert/status"` messaging (no `alert()`
  popups), labelled globes, visible focus rings, AA-contrast palette.

## 8. Data: JSON file today, PostGIS tomorrow

MVP persists to `backend/data.json` (auto-seeded Bengaluru listings) and
computes distance with haversine — the same math as
`ST_Distance(geography)/1000`, so rankings survive migration.

```bash
docker compose up -d db
export DATABASE_URL=postgresql://urbanmine:urbanmine@localhost:5432/urbanmine
```

```sql
CREATE EXTENSION postgis;
CREATE TABLE listings (
  id TEXT PRIMARY KEY, material TEXT, quantity DOUBLE PRECISION,
  unit TEXT, condition TEXT, price_per_unit DOUBLE PRECISION,
  address TEXT, contractor TEXT, title TEXT, description TEXT,
  confidence DOUBLE PRECISION, status TEXT DEFAULT 'active',
  created_at TIMESTAMPTZ DEFAULT now(),
  geom geography(Point, 4326)
);
-- nearest-first:
SELECT *, ST_Distance(geom, ST_MakePoint(77.5946,12.9716)::geography)/1000 AS km
FROM listings WHERE status='active'
ORDER BY geom <-> ST_MakePoint(77.5946,12.9716)::geography;
```

## 9. Sharing a demo (and why localhost comes first)

The app's backend lives on whoever's laptop runs it. A share link is a frozen
frontend copy wired to that laptop through a tunnel — it dies when the laptop
sleeps or the tunnel restarts, and anonymous slugs can't be revived. So:
**demo on localhost; publish a link only when someone off-laptop must open it.**

- Phone on the same Wi-Fi: `HTTPS=1 npm run dev -- --host`, open
  `https://<mac-lan-ip>:5173` (accept the self-signed cert). Mobile gets the
  bottom-tab shell + `capture="environment"` camera snap.
- Public link: `cloudflared tunnel --url http://localhost:8000`, then
  `VITE_API_BASE=<tunnel-url> npm run build` in `frontend/`, then
  `scripts/publish-here.py`.

STANDING RULE: never publish a new link unprompted — only on explicit approval,
then record the new slug here.

## 10. Design tokens (so edits stay consistent)

Concrete canvas `#d9d9d9` · iron ink `#1f1f1f` · muted `#4a4a4a` · card
`#e2e2e2`, inputs `#e6e6e6` · functional green `#027b49` (scores, focus,
success) · paint identity only: yellow `#fbb833` (Wood, logo, formula bars),
red `#fa4d43` (Bricks), pink `#f19ec8` (Doors), iron/black (Windows/Concrete).
Flat always: no shadows, no gradients. Type: SF Pro UI · Barlow Condensed 600
uppercase display · JetBrainsMono Nerd Font data. Shape: 14px cards / 10px
buttons / 12px inputs / 100px pills (tags, steps, status only).

## 11. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `connection refused :8000` in panels | backend isn't running — §1, terminal 1 (conda python, not `python3`) |
| `Analysis failed` on upload | backend down, or file > a few MB on slow disk — check terminal 1 log |
| First photo slow (~1 min) | normal — models loading; fast after that |
| `No GPS tag in this photo` | normal for screenshots/downloads — use search/preset/GPS/map |
| `Location blocked` | allow location in the address bar, or tap the globe |
| Address stays `resolving…` | Nominatim rate-limit/offline — coordinates still work; retry shortly |
| Globe is a dark empty panel | Cesium CDN unreachable — pickers still work; check network |
| Port busy (`:5173`/`:8000`) | `lsof -ti:5173 \| xargs kill` (same for 8000), restart |
| `404` on listing/request | id typo or deleted seed — `GET /api/listings` for live ids |
| Frontend shows old UI | hard refresh (`⌘⇧R`); dev hot-reloads, `dist/` only matters for `preview` |

## 12. Repo layout & companion docs

```
urbanmine/
├── README.md                  ← this file
├── PRD.md / TRD.md            ← product + technical specs (local only, gitignored)
├── PROJECT-FULLSTACK.md       ← full codebase doc (architecture, API, AI, LOC)
├── LICENSE                    ← MIT
├── docker-compose.yml         ← optional PostGIS 16-3.4
├── docs/urbanmine-flow.excalidraw.json
├── backend/  main.py · requirements.txt · data.json · uploads/
├── frontend/ index.html · vite.config.js · package.json · src/
└── scripts/  publish-here.py · publish-pick.py
```

Excluded from git (and the zip): `node_modules`, `dist`, `*.pt` weights
(auto-download), `uploads/`, logs, `.env` files.

## 13. License

MIT — see `LICENSE`.
