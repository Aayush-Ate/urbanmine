# UrbanMine — B2B demolition-reuse marketplace (MVP)

> **Review copy.** Read top to bottom, edit anything, hand it back — the site gets
> rebuilt to match this document. Lines you're most likely to want to change are
> marked **[YOUR CALL]**.

## 1. What this is

UrbanMine helps demolition contractors recover and resell usable construction
materials before they become waste. A contractor photographs a site, AI identifies
reusable materials (Wood, Bricks, Metal, Doors, Windows, Concrete) with quantity /
condition / confidence, one click turns each detection into a marketplace listing,
and buyers (architects, builders, interior designers) search, get match-scored
results, and request materials. An impact dashboard totals tonnes diverted and
rupees recovered.

**Core MVP flow (7 steps):**

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
Distance decays linearly to zero at 50 km
(`score_dist = max(0, 1 − km/50)`). **[YOUR CALL]** — tune weights / decay here
and the match endpoint follows.

## 2. Tech stack

| Layer | Choice | Notes |
|-------|--------|-------|
| Frontend | React 18 + Vite 5 | `frontend/`, dev on `:5173`, proxies `/api` + `/uploads` → `:8000` |
| Backend | Python + FastAPI | `backend/main.py`, serves on `:8000`, docs at `/docs` |
| AI vision | 16 materials via YOLO-World-m (descriptive prompts + hard negatives, conf 0.12) + YOLOv8n + visual pass + CLIP domain gate | Living things (people, clothes, fabric, plastic, dogs/cats/cows…) classified as non-construction; detections ranked as shares of 100%; dropdowns load live from `/api/materials`; `POST /api/analyze?debug=1` + `debug=true` returns per-stage raw outputs |
| Photo location | EXIF GPS via `exifr` (client-side) | No GPS tag → search / preset / device GPS / map tap |
| Database | JSON file today, PostgreSQL + PostGIS-ready | `backend/data.json`; `DATABASE_URL` + `docker compose up -d db` for real PostGIS (schema in §9) |
| Maps / 3D | **CesiumJS globe** (CDN) | Keyless Esri satellite imagery + place-labels overlay; ion token unlocks world terrain + 3D tiles (see §8) |
| Geocoding | HERE Geocoding & Search (key) → Nominatim fallback (keyless) | `VITE_HERE_API_KEY` in `frontend/.env` (free tier: developer.here.com); absent → OSM Nominatim, rate-limited |
| Animation | GSAP (scoped, reduced-motion-safe) | Sidebar entrance + card stagger only; `prefers-reduced-motion` disables all motion |
| Fonts | SF Pro (UI) + Barlow Condensed (display) + Nerd Font mono (data) | `brew install --cask font-jetbrains-mono-nerd-font`; web fallbacks ship via Google Fonts |

## 3. Repo layout

```
urbanmine/
├── README.md                  ← this document (review → edit → rebuild)
├── docker-compose.yml         ← optional PostGIS 16-3.4 (user/pass/db: urbanmine)
├── docs/
│   └── urbanmine-flow.excalidraw.json  ← 10-node MVP flow diagram (open at excalidraw.com → Open)
├── backend/
│   ├── main.py                ← all API routes + YOLO/mock + match scoring + impact
│   ├── requirements.txt       ← fastapi, uvicorn, python-multipart, pydantic (+ optional ultralytics/psycopg2)
│   ├── data.json              ← auto-created store (6 seed listings on first run)
│   └── uploads/               ← auto-created analyzed-photo storage (served at /uploads)
└── frontend/
    ├── index.html             ← Cesium CDN (JS + Widgets CSS) + font links
    ├── .env.example           ← VITE_CESIUM_TOKEN template (copy to .env to use)
    ├── vite.config.js         ← dev port 5173 + /api + /uploads proxy
    ├── package.json           ← react, react-dom, gsap, exifr (+ vite, @vitejs/plugin-react)
    └── src/
        ├── main.jsx           ← React root
        ├── App.jsx            ← dashboard shell + 5 workspace panels
        ├── LocationPicker.jsx ← no-coordinate location picker (search/preset/GPS/map)
        ├── cesium.js          ← token handling, createViewer, flyTo, setPins
        └── styles.css         ← SaaS theme (palette, cards, dropzone, a11y helpers)
```

## 4. Run localhost

Two terminals:

```bash
# 1 · backend  →  http://localhost:8000  (docs: /docs)
cd urbanmine/backend
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000

# 2 · frontend  →  http://localhost:5173
cd urbanmine/frontend
npm install
npm run dev
```

Production preview: `npm run build && npm run preview -- --port 5173`.
Verify in one line:

```bash
curl -s http://localhost:8000/api/health && curl -s -o /dev/null -w "frontend: %{http_code}\n" http://localhost:5173
```

## 5. Environment variables

| Var | Where | Required? | Effect |
|-----|-------|-----------|--------|
| `VITE_CESIUM_TOKEN` | `frontend/.env` | No | Cesium ion token → world imagery + terrain + 3D tiles. Absent → keyless OSM globe. Free token: `https://ion.cesium.com/tokens` |
| `DATABASE_URL` | backend env | No | Set + `docker compose up -d db` → real PostGIS. Absent → JSON file store. Format: `postgresql://urbanmine:urbanmine@localhost:5432/urbanmine` |

**[YOUR CALL]** — paste your Cesium ion token into `frontend/.env` (from `.env.example`)
if you have one; otherwise the globe already works keyless.

## 6. API reference

Base `http://localhost:8000`. Error shape on 404: `{"detail": "..."}`.

| Method + path | Body / params | Returns |
|---------------|---------------|---------|
| `GET /api/health` | — | `{status, yolo, listings, requests, db, postgis}` |
| `POST /api/analyze` | multipart: `file` (image, required), `lat`, `lng`, `address` | `{image_url, detections[], model}` — each detection: `material, icon, quantity, unit, condition, confidence, suggested_price_per_unit` |
| `POST /api/listings` | `material, quantity, unit?, condition?, price_per_unit?, lat, lng, address, contractor, title?, description?, confidence?` | created listing (`id` = 8-char uid, `status: active`) |
| `GET /api/listings` | `material?, condition?, q?, lat?, lng?, max_distance_km=100` | active listings; with `lat+lng` adds `distance_km` and sorts nearest-first |
| `GET /api/listings/{id}` | — | listing or **404** |
| `PATCH /api/listings/{id}` | `quantity?, condition?, price_per_unit?, status?` | updated listing or **404** |
| `POST /api/match` | `material, quantity=100, lat, lng, condition?, max_distance_km=50` | `{query, weights, results[≤20]}` each with `match_score` + `distance_km`, sorted best-first |
| `POST /api/requests` | `listing_id, buyer_name, buyer_type?, quantity?, message?` | created request (`status: pending`) or **404** |
| `GET /api/requests` | — | all requests, newest first |
| `PATCH /api/requests/{id}` | `status` (`accepted` / `declined` / `pending`) | updated request or **404** |
| `GET /api/impact` | — | `{tonnes_diverted, value_recovered_inr, value_recovered_fmt, buyer_matches, active_listings, total_requests}` |
| `GET /api/materials` | — | 6 materials with `unit, price, co2_per_unit_kg, icon` |
| `GET /uploads/{file}` | — | stored analyzed photo |

**Impact math (MVP):** tonnes = Σ qty × material CO₂ factor ÷ 1000 ·
value = Σ qty × price (formatted `₹x.x lakh` / `₹x.xx Cr`) ·
matches = 43 (seed) + live requests. **[YOUR CALL]** — replace CO₂ factors with
LCA data and the seed-43 with real analytics when ready.

**Try it:**

```bash
curl -s "http://localhost:8000/api/listings?material=Wood" | head -c 300; echo
curl -s -X POST http://localhost:8000/api/match -H 'Content-Type: application/json' \
  -d '{"material":"Wood","quantity":500,"lat":12.9716,"lng":77.5946}'
```

## 7. Frontend guide

**Dashboard shell** (`App.jsx`): dark forest sidebar (brand → numbered workspace nav →
match-formula card → backend status) + mission topbar + workspace canvas. Mobile:
sidebar collapses to a horizontal nav strip; formula hides; topbar keeps the mission.

**The five panels:**

1. **Upload + AI** — 3-step flow (`Photo → AI review → Published`). Photo drop
   auto-runs EXIF-GPS extraction then material analysis with a visible "AI thinking"
   checklist. Detections are fully editable (qty/unit/condition/price) before
   Confirm → listing. `Re-analyse photo` re-runs with current location.
2. **Marketplace** — buyer-location picker (compact) + search/material/condition/
   distance filters + buyer identity + request buttons + Cesium globe with clickable
   pins. Results reload when the point moves.
3. **Smart Match** — same picker + material/qty/condition/`Within km` → ranked rows
   with score dials.
4. **Requests** — pending rows carry working **Accept / Decline**; decided rows show
   their id. (No payments — handshake only.)
5. **Impact** — four stat cards + a "how it's computed" note.

**`LocationPicker.jsx`** — nobody types coordinates, anywhere. Five ways to set a
point: address search (Nominatim, Bengaluru-biased, debounced), 12 area presets,
device GPS (with blocked-permission guidance), click-to-set on the mini-globe,
drag-the-SITE-pin. Reverse-geocodes every move into a human address; shows
`address + lat,lng + source tag` (`photo EXIF / search / preset / device GPS /
map tap / map pin`). `compact` prop hides the globe (Marketplace, Smart Match).

**`cesium.js`** — `CESIUM_TOKEN` (env) → `createViewer` (ion world imagery+terrain
with token, else keyless Esri satellite + place-labels overlay, chrome stripped to
just infoBox) → `flyTo` → `setPins` (amber pins, material labels, HTML descriptions).

**Motion (GSAP):** sidebar sequence on load + card stagger on tab switch only;
`gsap.context` scoped with `revert()` cleanup; `prefers-reduced-motion` skips all
JS motion (CSS kill-switch covers the rest). No scroll listeners, transform/opacity
only.

**Accessibility:** skip link, `tablist/tab` + `aria-selected`, keyboard-focusable
dropzone, `role="alert/status"` messaging (no `alert()` popups anywhere), labelled
globes, visible focus rings, AA-contrast palette.

## 8. Maps: Cesium + geocoding (key story)

- **Today (no keys):** Cesium globe on Esri satellite imagery (built via the
  1.119-native `fromBasemapType(SATELLITE)` factory — plain `new
  ArcGisMapServerImageryProvider({url})` is an unbuilt shell on this version)
  + ellipsoid terrain. A small ArcGIS default-token credit notice shows until
  you set `Cesium.ArcGisMapService.defaultAccessToken` with a free ArcGIS
  Developer key. Everything works; attribution rendered by the globe.
- **With your ion token:** world imagery, true terrain, 3D-tiles ready — set
  `VITE_CESIUM_TOKEN` in `frontend/.env`, restart dev. No code change.
- **Google-Maps style (Photorealistic 3D Tiles):** ion dashboard → Asset Depot →
  add *Google Maps Platform Photorealistic 3D Tiles* → set
  `VITE_GOOGLE_TILES_ASSET_ID` to its asset ID (plus the ion token). The app then
  loads the tileset and hides the plain globe automatically — naked viewer
  (all widgets already off), ground atmosphere + sun lighting are always on.
  Google 2D tiles / Google geocoder need a Google Maps Platform key wired in the
  ion dashboard — say the word when you have one. **[YOUR CALL]**
- **Geocoder:** HERE with `VITE_HERE_API_KEY` (India-biased `in=countryCode:IND`,
  `at` = Bengaluru), Nominatim fallback when the key is absent or HERE errors.
  Helpers `geoSearch` / `geoReverse` in `LocationPicker.jsx` own the chain.
  **[YOUR CALL]** — paste your HERE key into `frontend/.env`.
- **Offline failure mode:** if the Cesium CDN is unreachable the globes render an
  empty dark panel; pickers (search/preset/GPS) keep working. **[YOUR CALL]** — is
  an offline fallback map worth it, or is CDN dependence acceptable?

## 9. Database: file today, PostGIS tomorrow

MVP persists to `backend/data.json` (auto-seeded with 6 Bengaluru listings:
Koramangala teak, HSR bricks, Indiranagar steel, Jayanagar doors, Hebbal windows,
BTM concrete) and computes distance with haversine — the same math as
`ST_Distance(geography)/1000`, so rankings don't change on migration.

**Migrate:**

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

## 10. Design system — The1 voice on a SaaS body (so a rebuild stays consistent)

- Palette (concrete canvas, iron ink, paint identity): bg concrete `#d9d9d9` ·
  ink iron `#1f1f1f` · muted `#4a4a4a` · hairline borders iron · card `#e2e2e2`,
  inputs `#e6e6e6` · functional accent green `#027b49` (scores, focus, success) ·
  paints as identity only: yellow `#fbb833` (Wood, logo mark, formula bars) ·
  red `#fa4d43` (Bricks) · pink `#f19ec8` (Doors) · iron/black (Windows/Concrete).
- Paints are full-bleed identity blocks (the 4 Impact cards) + 10px wayfinding
  dots — never body text, never status semantics. Ruthlessly flat: no shadows,
  no gradients.
- Type: `--font-ui` (SF Pro stack) for UI/body; `--font-display`
  (Barlow Condensed 600, uppercase) for brand, topbar titles, card headings,
  impact figures; `--font-mono` (JetBrainsMono Nerd Font → SF Mono) for
  numbers/code/ids.
- Shape: 14px cards / 10px buttons / 12px inputs / 100px pills for tags, steps,
  status only.
- Motion: `cubic-bezier(.32,.72,0,1)`; entrance-only; reduced-motion kills all.

## 11. How it was built (working agreements, keep or drop)

- **Think before coding, surgical edits, verify every fix** (karpathy-style).
- **Ask before guessing** requirements (grill-style) — open questions live in §12.
- **React discipline:** no dead fetches, effect cleanups (object URLs, maps, viewers,
  timers), `alert()` banned in favor of inline status regions.
- **A11y + reduced-motion** are ship-blockers, not polish.
- **Diagrams over prose** for flows (`docs/*.excalidraw.json`).

## 12. Open decisions — edit these, then say "redo"

1. **Maps/geocoder keys:** whose Cesium ion token? Which geocoder at launch (Google / HERE / Mapbox)? **[YOUR CALL]**
2. **Real YOLO:** DONE 2026-09-28 — `ultralytics` + torch CPU installed,
   YOLOv8n runs on every upload (expanded COCO→material map, box-area quantities)
   fused with a color/texture visual pass. DONE 2026-09-29 — YOLO-World
   open-vocabulary prompts + CLIP crop-verification gate (0.60) kill bedsheet
   false positives; fabric auto-reroutes to non-construction. Next step only if
   you want it: a trained construction-materials segmentation model. **[YOUR CALL]**
3. **Money + identity:** payments (Razorpay/Stripe?), contractor/buyer auth, and request chat — in or out of the next MVP slice? **[YOUR CALL]**
4. **Impact factors:** keep CO₂-per-unit estimates or plug real LCA data? Drop the seed-43 matches baseline? **[YOUR CALL]**
5. **Match weights:** keep 40/25/20/15 + 50 km decay, or retune? **[YOUR CALL]**
6. **Brand:** DONE 2026-09-28 — The1 system (concrete `#d9d9d9`, iron `#1f1f1f`,
   4 paint identity colors, Barlow Condensed display, flat, §10). Say the word
   to revisit. **[YOUR CALL]**
7. **"here.now":** RESOLVED both ways — here.now = static hosting (live demo §14);
   HERE = geocoder (`VITE_HERE_API_KEY`, Nominatim fallback). Paste the HERE key
   when you have it. **[YOUR CALL]**

## 13. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `connection refused :8000` in panels | backend isn't running — §4, terminal 1 |
| `Analysis failed` on upload | backend down, or file > a few MB on slow disk — check terminal 1 log |
| `No GPS tag in this photo` | normal for screenshots/downloads — use search/preset/GPS/map |
| `Location blocked` | browser permission — allow location in the address bar, or tap the globe |
| Address stays `resolving…` | Nominatim rate-limit/offline — coordinates still work; retry shortly |
| Globe is a dark empty panel | Cesium CDN unreachable — pickers still work; check network |
| Port busy (`:5173`/`:8000`) | `lsof -ti:5173 \| xargs kill` (same for 8000), restart |
| `404` on listing/request | id typo or deleted seed — `GET /api/listings` for live ids |
| Frontend shows old UI | hard refresh (`⌘⇧R`); dev hot-reloads, `dist/` only matters for `preview` |

## 14. Share demo (here.now link)

- **Live link:** https://dreamy-lichen-rqgk.here.now/ (anonymous, expires ~24h —
  STANDING RULE: this slug is THE demo link. Never mint a new slug unprompted;
  anonymous slugs are immutable, so frontend fixes queue until the user
  explicitly says to publish a new link. Backend-only changes flow in live.)
  republish for a fresh one; use an API key for permanent).
- Works on phone + laptop: responsive layout, `capture="environment"` camera
  snap on mobile, Cesium satellite globes, real YOLO backend.
- The link is frontend-only hosting — it calls the backend through a tunnel:
  `cloudflared tunnel --url http://localhost:8000` must be running on this Mac
  and `dist/` built with that tunnel URL as `VITE_API_BASE`.
- Republish: `VITE_API_BASE=<tunnel-url> npm run build` in `frontend/`, then
  `python3 /tmp/publish-here.py` (script in the task transcript; re-create from
  README §share if lost: POST `/api/v1/publish` file manifest → PUT bytes →
  POST `finalize`).
- Mobile LAN testing instead: `HTTPS=1 npm run dev -- --host`, open
  `https://<mac-lan-ip>:5173` on the phone (accept the self-signed cert).
