# UrbanMine: the system design, written out

The other docs say *why* each choice was made. This one says *what the system
is* — the boxes, the arrows, the data, and what happens when one of them dies.
It is meant to be readable without opening the code.

## The product in three sentences

A demolition contractor photographs a site. The AI names what is still worth
money, with a quantity, a condition and a salvage price. One tap publishes it,
and a buyer searches, gets ranked by distance and fit, and sends a request.

The whole constraint is this: **cataloguing has to cost one photo, not an
afternoon.** Every design choice below is downstream of that.

## The boxes

Four things, one public URL:

```
  phone / laptop
        │
        ▼
┌─────────────────────────────┐
│ Browser                     │  React 18 + Vite 5, one page, four tabs
│ Upload · Marketplace ·      │  Photos shrink to 1600px here, before upload
│ Smart Match · Requests      │
└──────────────┬──────────────┘
               │  fetch /api/*  and  /uploads/*
               │  same origin → no CORS in production
               ▼
┌─────────────────────────────┐
│ Vercel (frontend project)   │  static build + two rewrites
│ /api/*      → backend alias │
│ /uploads/*  → backend alias │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ FastAPI                     │  app/main.py: parse → call one function → return
└───┬──────────────┬──────────┴────────────┬─────────────────┐
    │              │                       │                 │
    ▼              ▼                       ▼                 ▼
┌─────────┐  ┌─────────────┐        ┌──────────────┐  ┌───────────────┐
│ AI      │  │ Pure maths  │        │ Storage      │  │ Photos        │
│ app/ai  │  │ core/       │        │ storage/     │  │ /uploads/{id} │
│ hosted  │  │ scoring.py  │        │ Postgres or  │  │ disk cache,   │
│ VLM or  │  │ catalog.py  │        │ data.json    │  │ then Postgres │
│ 4 local │  │ (weights,   │        │              │  │ BYTEA         │
│ passes  │  │  prices)    │        │              │  │               │
└─────────┘  └─────────────┘        └──────────────┘  └───────────────┘
```

Nothing calls the database or a model directly except the module that owns it.
That is the rule that keeps the backend changeable: `main.py` has no maths, no
SQL, and no model loading in it.

## What happens on an upload

```
1  tap / drop a photo            browser
2  shrink to 1600px JPEG         browser (canvas) — a 12MB phone photo becomes ~300KB
3  read EXIF GPS                 browser (exifr) — adopted only within 25km of the device
4  POST /api/analyze             multipart: file, lat, lng, address
5  size + type check             25MB cap, JPG/PNG/WebP, image verified with Pillow
6  store the photo               disk (cache) + Postgres BYTEA (survives a restart)
7  run the AI                    hosted model, or YOLO-World + YOLOv8n + colour + CLIP
8  return detections             material, quantity, unit, condition, price, bbox, share
9  contractor edits              quantity, condition, rate, or measures on the photo
10 POST /api/listings            one listing per confirmed detection
11 buyer sees it                 GET /api/listings, ranked by distance if a point is set
```

Steps 1–3 exist because the expensive things (mobile data, model time) should see
a small photo. Step 5 exists because the client is not trusted. Step 9 exists
because a photo cannot tell a sound plank from a rotten one, so a human has to
confirm before anything is priced.

## The five flows, and the routes behind them

| User flow | Route | What it actually does |
|---|---|---|
| Photograph a site | `POST /api/analyze` | Validates, stores, detects, returns a draft |
| Publish a lot | `POST /api/listings` | One row: material, quantity, unit, rate, point, photo |
| Browse nearby | `GET /api/listings` | Filter by material / condition / text / radius, sort by distance |
| Rank by fit | `POST /api/match` | Score = material 40 · quantity 25 · distance 20 · condition 15 |
| Ask for it | `POST /api/requests` | Pending request against a listing |
| Accept / decline | `PATCH /api/requests/{id}` | `pending → accepted \| declined` |
| Correct a listing | `PATCH /api/listings/{id}` | Quantity, condition, rate, status |
| Take it down | `DELETE /api/listings/{id}` | Removes the listing, then its photo if nothing else uses it |
| Serve a photo | `GET /uploads/{fid}` | Disk first (warm), then Postgres BYTEA (cold) |

Distance is haversine in Python, not SQL, and it goes to zero past 50 km in the
score. That is a product decision: a bargain 200 km away is not a bargain.

## What is stored

Two tables, plus the four panels' worth of state as one document:

```sql
urbanmine_state (id=1, data JSONB, updated_at)
urbanmine_images (id TEXT, bytes BYTEA, content_type TEXT, created_at)
```

`data` is the whole app state:

```json
{
  "listings": [
    {
      "id": "9f3c1a2b",
      "material": "Bricks",
      "title": "Reclaimed Bricks — 1200 pcs",
      "quantity": 1200, "unit": "pcs",
      "condition": "Good", "price_per_unit": 5,
      "lat": 12.9116, "lng": 77.6474,
      "address": "HSR Layout, Bengaluru",
      "contractor": "Sharma Demolition",
      "confidence": 0.82,
      "image_url": "/uploads/a1b2c3d4e5.jpg",
      "thumb_url": "/uploads/ta1b2c3d4e5.jpg",
      "bbox": [0.1, 0.2, 0.6, 0.7],
      "dimensions": { "length_mm": 3000, "width_mm": 2000 },
      "dimensions_label": "3.0 × 2.0 m",
      "status": "active",
      "created_at": "2026-11-02T09:14:00+00:00"
    }
  ],
  "requests": [
    {
      "id": "7d21ac90",
      "listing_id": "9f3c1a2b",
      "listing_title": "Reclaimed Bricks — 1200 pcs",
      "contractor": "Sharma Demolition",
      "buyer_name": "Priya", "buyer_type": "Architect",
      "quantity": 1200, "message": "Can collect Saturday",
      "status": "pending",
      "created_at": "2026-11-02T10:02:11+00:00"
    }
  ]
}
```

One JSONB row is a demo decision with a known cost: two writers at the same
moment, last write wins. The fix is known and written down in `DECISIONS.md`:
separate tables, update by id. Photos are separate rows precisely because they
are big and immutable; only the listing document changes.

Without `DATABASE_URL` the same document lives in `backend/data.json` and photos
in `backend/uploads/`, so a fresh clone and the test suite need no database.
`GET /api/health` says which mode is live (`"store": "postgres" | "json"`).

## The AI, in one page

Two providers, one interface. `detect_materials(bytes)` returns the same five
things either way, so no route and no pixel of UI knows which is running.

**Hosted (default when a key is set).** One multimodal call answers the whole
question: which materials, how much, what condition, is this even a site. The
JSON is validated against the 16-material catalog before anything reaches the UI:
unknown material dropped, absurd quantity clamped, out-of-frame box discarded.

**Local (zero keys, always available).** Four passes, merged:

```
photo ─► one 1280px copy ──┬─► YOLO-World-m      prompts like "stack of red clay bricks"
                           ├─► YOLOv8n           everyday objects → Wood / Metal
                           ├─► colour pass       numpy only, bulk coverage + condition
                           └─► CLIP gate         0.60: is this crop even construction?
                                       │
                                       ▼
                         merge → drop household hits → normalise shares → 4 detections
```

The gate is why a bedsheet does not become a fabric listing. The local path is
the fallback, not the default: it is 2GB of Python and it still cannot count a
pile. `docs/AI.md` compares the candidates and shows how to switch.

## Why the boundaries are where they are

| Boundary | What crosses it | The rule that keeps it clean |
|---|---|---|
| Browser → API | multipart photo, JSON | The API validates type, size, ranges and URLs; it never trusts a field because the UI sends it |
| API → AI | bytes in, 5-tuple out | Models load lazily inside `app/ai`, never at import, so a broken model cannot stop the app booting |
| API → storage | one dict | `load_db()` / `save_db()` are the only database calls in the codebase; swapping store means editing one file |
| API → disk | one filename | Photo names are generated here, never taken from a request; a name is re-checked before unlink |
| Frontend → backend | `/api/*`, `/uploads/*` | Same origin via rewrite → no CORS in production, and no `VITE_API_BASE` to keep in sync |

## What breaks, and what the user sees

| If this dies | What happens | What the user sees |
|---|---|---|
| Hosted VLM times out or has no key | Falls back to the local passes automatically | Slower analysis, same shape of result |
| Local models fail to load | Colour pass + empty detections | "AI found no objects to check", upload still accepted |
| Postgres is unreachable | `load_db()` raises | 500 on the data routes; health keeps answering |
| The container restarts | Disk uploads are gone; Postgres copy serves instead | Photos still load |
| The buyer sets no location | No distance filter, no distance shown | Listings listed without "km away" |
| Cesium CDN fails | Globe card shows an error line | Search, presets, GPS and the listing grid still work |
| The browser blocks geolocation | No point is invented | "No location set", user picks a preset or taps the map |

The pattern: a missing input is shown as missing. Nothing quietly substitutes a
city, a price, or a quantity.

## Size, cost, and why this deploy shape

The first build shipped as a container because of arithmetic, not preference:

| Piece | Local model stack | Hosted VLM path |
|---|---|---|
| Python + torch + transformers | ~2 GB image | ~120 MB image |
| Model weights baked in | ~150 MB | none |
| RAM needed | 2 GB (Render free tier is 512 MB) | 512 MB is plenty |
| Where it can run | container runtime only | any normal serverless function |
| Cold start | 30–60 s (weights load) | < 1 s |
| Cost per photo | free | fractions of a cent, free tier covers a demo |

A normal serverless function cannot carry torch. That single fact is the whole
reason for the Dockerfile, the 2GB image and the 2GB RAM requirement. Moving the
detection to a hosted model removes the constraint — the backend becomes a
small FastAPI app again, small enough for a 500MB ceiling.

The frontend is a static build: **424 KB total** (`dist/`), so it deploys in
seconds and is not the heavy half of this project.

## What is deliberately not built

- **No accounts.** A request carries a typed name. Anyone can delete a listing.
- **No payments or chat.** A request is a handshake; the phone call is outside.
- **No real-time.** Refresh to see new inventory.
- **No normalised tables.** One document, accepted single-writer cost.
- **No LCA data.** The CO₂ factors are estimates and the UI says so.
- **No perspective correction on the ruler.** A line drawn across an oblique
  surface reads short, and the label admits it.

## Where to read the code

| Question | File |
|---|---|
| What does the HTTP surface look like? | `backend/app/main.py` |
| What JSON is legal? | `backend/app/schemas.py` |
| What is a material, and what is it worth? | `backend/app/core/catalog.py` |
| How near, how much, how good a match? | `backend/app/core/scoring.py` |
| What is in this photo? | `backend/app/ai/vision.py`, `backend/app/ai/vlm.py` |
| Where do listings live? | `backend/app/storage/store.py` |
| How big is a stored photo? | `backend/app/storage/images.py` |
| What does the shell look like? | `frontend/src/App.jsx`, `frontend/src/styles/styles.css` |
| Where is this site? | `frontend/src/components/LocationPicker.jsx` |
| How big is this thing? | `frontend/src/components/MeasureModal.jsx` |

Also: `docs/AI.md` (the model choice), `docs/SECURITY.md` (what was audited),
`docs/DECISIONS.md` (why anything is the way it is), `docs/DEPLOY.md` (hosts and
commands).
