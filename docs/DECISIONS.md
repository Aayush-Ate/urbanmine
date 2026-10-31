# Why UrbanMine is built this way

Every choice here had an alternative that would also have worked. This file keeps
the reason and the cost, so the next person does not re-argue it from zero.

| Question | Short answer |
|---|---|
| Why Docker? | The backend is ~2GB of Python plus ~150MB of weights. Nothing but a container carries that. |
| Why Neon? | Serverless Postgres with a pooled connection string, so short-lived containers do not exhaust connections. |
| Why not SQLite? | SQLite is a file on one disk. Our hosts throw the disk away, and there is more than one instance. |
| Why one JSONB row? | The shape changes weekly and there is one writer at a time. Tables when that stops being true. |
| Why a JSON file fallback? | So the tests and a fresh clone run with no database at all. |
| Why FastAPI? | The AI is Python. |
| Why Vite + React, not Next? | A dashboard with no SEO and a WebGL globe. Static build plus two rewrites. |
| Why Cesium, not Leaflet? | Satellite first, with a terrain and 3D tiles path. |
| Why YOLO-World + CLIP, not a trained model? | No labelled demolition dataset exists. |

## Why Docker

What we ship is `backend/Dockerfile` on `python:3.11-slim`.

The backend imports torch, ultralytics, transformers and PIL, and the image
carries roughly 150MB of YOLO and CLIP weights. That lands near 2GB. A normal
serverless function — a JS lambda, a Vercel edge function — has a bundle limit
far below that and a short request budget. There is no version of "just deploy
the Python file somewhere" that runs this. The container is not decoration, it is
the only deployment shape that fits.

Three lines in the Dockerfile do real work:

1. CPU torch is installed first from the pytorch CPU index. Without it, pip pulls
   the CUDA build and the image grows by gigabytes for a GPU nobody has.
2. `libgl1` and `libglib2.0-0` are installed, because ultralytics pulls OpenCV and
   OpenCV will not import without them.
3. The weights are downloaded, and one `set_classes()` call is exercised, at build
   time. That call imports the OpenAI `clip` package, which ultralytics does not
   install for you. Baking it means a broken YOLO-World fails the build instead
   of quietly serving without it — and cold starts do not spend 30-60s
   downloading.

What it costs: builds around four minutes, a ~2GB image, a 30-60s cold start when
the host scales to zero, and a host that must give the container 2GB of RAM.
Render's free 512MB tier cannot run it. That is not a preference, it is
arithmetic.

## Why Neon

Neon is serverless Postgres. What we needed was a Postgres URL that outlives the
laptop and does not fall over when several short-lived containers connect at once.

Four things decided it:

- **A pooled connection string.** The URL contains `-pooler`, so connections go
  through PgBouncer. `store.py` opens one short connection per call and closes it.
  Without pooling, a container that scales out would run the database out of
  connection slots.
- **Free tier that scales to zero.** This is an MVP with demo traffic.
- **Region.** The project is in Singapore and the backend runs in `sin1`, so a
  query is not crossing an ocean.
- **Branching.** A copy-on-write branch is a throwaway database with the same
  schema, for testing a migration without touching production rows.

What it costs: pooled connections are not session connections, so no
session-scoped state and no `LISTEN/NOTIFY`. Scale-to-zero means the first query
after idle is slower.

`docker-compose.yml` still exists for a local Postgres when you want to test the
Postgres path without pointing at the cloud database. It is optional. The app does
not need PostGIS, because distance is haversine in `scoring.py`; the postgis image
is kept only because it is a superset and costs nothing.

## Why Postgres and not SQLite

This is the question worth answering properly, because SQLite is the obvious
choice for an MVP and would have been simpler.

SQLite is a file on one disk. That is why it is fast, and it is why it cannot work
here:

1. **The disk is not ours.** The backend runs as a container. The filesystem is
   per-instance and is discarded. A SQLite file written by one request is gone, or
   invisible to the next instance.
2. **"One instance" is not a guarantee.** Hosts scale to zero and back up, and can
   run several instances at once. Two instances with two SQLite files are two
   different marketplaces: a listing created in one is invisible in the other, and
   a buyer refreshing the page sees inventory appear and disappear.
3. **Photos have the same problem.** Uploaded bytes are stored next to the listing
   in `urbanmine_images`. On a local disk that is the same disappearing file. In
   Postgres it is a row, and `/uploads/{fid}` reads disk first, then the database.
4. **Concurrent writes.** SQLite locks the whole file for a write. At this scale
   that is not the bottleneck, but it is a second reason not to start there.
5. **The exit path.** `data` is JSONB, so the app keeps a document shape it can
   change weekly, and a GIN index or a real column is a migration away when the
   shape settles. SQLite has JSON1 but no JSONB and no equivalent. And if radius
   filtering ever moves into SQL, PostGIS is an extension install, not a rewrite.

One address that every instance sees is the requirement. SQLite cannot meet it,
however well it does everything else.

**Where SQLite would have been right:** a single always-on box with a real disk —
a VPS, or the Oracle Always Free VM listed in `DEPLOY.md`. If UrbanMine is ever
deployed that way, SQLite comes back on the table and would be a good choice.

## Why one JSONB row

`urbanmine_state` is:

```sql
id INTEGER PRIMARY KEY,
data JSONB NOT NULL,
updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
```

One row, id 1, the whole `{"listings": [...], "requests": [...]}` document inside
it. `load_db()` returns a dict, `save_db()` upserts it. That is why the Postgres
path and the JSON-file path are the same two functions, and why the rest of the
app never learns which one is live.

What it costs, stated plainly in the code: last write wins. Two workers saving at
the same moment overwrite each other, and every save rewrites the whole document.
Fine for a demo, not fine for a launch. The fix is known: separate `listings` and
`requests` tables and update rows by id.

## Why keep the JSON file at all

Because 50 tests and a fresh clone should not need a database. `DATA_FILE` points
the store somewhere else, the tests use temp directories, and nothing touches the
real file. It is a development convenience, not a production mode.

## Why FastAPI and not Express

The hard part of this product is vision. torch, ultralytics, transformers and PIL
are all Python. In Node we would shell out to a Python process for every photo: an
extra hop, an extra failure mode, and two runtimes to keep in one deploy. Pydantic
also gives request validation for free, which is most of `schemas.py`.

## Why React + Vite and not Next.js

It is a dashboard with five tabs, no router, no SEO requirement, and heavy client
media — photos and a WebGL globe. A static build plus two rewrites in
`frontend/vercel.json` is the whole deployment story. Next would add a server we
do not use.

The rewrite is also why CORS never comes up in production: the browser calls
`/api/...` on the same origin as the page, and Vercel forwards it to the backend
alias.

## Why Cesium and not Leaflet

Satellite-first is the product. Cesium gives imagery, terrain and a 3D tiles path
with one viewer, and works keyless on Esri satellite until an ion token exists.
Leaflet is a 2D tile map with no terrain.

What it cost: Cesium 1.119 ignores imagery passed to the viewer constructor, and
`removeAll()` strands tiles. Both are handled by attaching layers through async
factories in `frontend/src/lib/cesium.js`.

## Why YOLO-World + YOLOv8n + CLIP and not a trained model

There is no labelled demolition-materials dataset to train on. Four passes stand
in for one trained model:

1. YOLO-World-m with descriptive prompts, so "stack of red bricks" can match
   without a single training epoch.
2. YOLOv8n on COCO, so everyday objects still register — a bus becomes Metal, plus
   people.
3. A numpy colour and texture pass for bulk coverage and condition, no network.
4. CLIP as a gate at 0.60 on each crop and on the full frame. This is what killed
   the household false positives: the bedsheet that used to be listed as fabric.

The Concrete fallback only fires on frames that already look like a construction
site, and the response labels it a guess rather than presenting it as a detection.

Training is the right next step and `uploads/` is the seed dataset. It is not the
right step before there are a few hundred labelled site photos.

## Where the hard problems actually got solved

| Problem | Solved in |
|---|---|
| Quantities were random or guessed | `qty_for` in `app/core/scoring.py` — coverage × base quantity; `MeasureModal` for a real measured size |
| A bedsheet got listed as material | CLIP gate at 0.60 plus the hard-negative prompt list — `app/ai/vision.py` and `app/core/catalog.py` |
| Photos 404'd after a restart | `save_image` / `load_image` in `app/storage/store.py`; `/uploads/{fid}` tries disk, then the database |
| Screenshots and downloads had no GPS | `LocationPicker` — search, presets, device GPS, map tap, all reverse-geocoded |
| Phone camera and geolocation were blocked | `HTTPS=1` in `frontend/vite.config.js` through `@vitejs/plugin-basic-ssl` |
| The globe rendered black on Cesium 1.119 | Async layer factories in `frontend/src/lib/cesium.js` |
| Prices read like a shop, not a salvage yard | Salvage prices in `MATERIAL_META`, `app/core/catalog.py` |
| A share link died with the laptop | The localhost-first rule in `README.md`, and `scripts/publish-here.py` for the frozen build |
| The docs and the tree disagreed | This restructure: `docs/DEPLOY.md`, `docs/PROJECT-FULLSTACK.md`, and one README |

## What is still open

- Auth, payments and buyer/contractor chat. Requests are a handshake only.
- Real LCA factors. The CO2 numbers in `catalog.py` are estimates, and the impact
  panel says so.
- Splitting the JSONB row into real tables, before concurrent writes matter.
- PostGIS, only if radius filtering moves out of `scoring.py` and into SQL.
- Object storage for photos instead of database rows, if volume grows.
- A trained segmentation model, once there are labelled photos.
