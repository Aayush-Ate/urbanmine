# UrbanMine

A demolition site is a mine. Everything in a building that comes down was already
paid for once, and most of it goes straight to a landfill. UrbanMine photographs
the site, names what is still worth money with a quantity and a salvage price,
and turns it into a listing a buyer can search and match against.

The loop is:

```
photo → Upload tab → POST /api/analyze → contractor edits → POST /api/listings
buyer → Marketplace / Smart Match → POST /api/requests → contractor accepts
```

Stack: React 18 + Vite 5 · FastAPI · YOLO-World-m + YOLOv8n + a colour pass + a
CLIP gate · Neon Postgres (or a JSON file) · Cesium satellite globes.

It runs with zero keys. Keys only upgrade the map and the geocoder.

## Run it

Two terminals. Backend first, because the frontend proxies `/api` and `/uploads`
to it.

```bash
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000        # http://localhost:8000/docs
```

```bash
cd frontend
npm install
npm run dev                                       # http://localhost:5173
```

That `python` needs torch, ultralytics and transformers installed. A bare system
python does not have them, so point at whichever interpreter has the
requirements. The first photo takes about a minute while the weights load; every
photo after that is seconds.

Check both in one line:

```bash
curl -s http://localhost:8000/api/health
curl -s -o /dev/null -w "frontend: %{http_code}\n" http://localhost:5173
```

`/api/health` also tells you where the data is going: `"store": "postgres"` or
`"store": "json"`. Load `backend/.env` first if you want Postgres locally:

```bash
cd backend
set -a; . ./.env; set +a
python -m uvicorn app.main:app --port 8000
```

### Tests

```bash
cd backend
python -m unittest discover -s tests -v
```

Stdlib `unittest`, no model downloads, a few seconds. The AI is stubbed, so a
green run means the routes, the scoring, the sizing maths and the store are
fine. It does not mean the models behaved on your photo.

### Docker

If you have Docker and do not want to install torch on your laptop:

```bash
docker build -t urbanmine-api backend
docker run --rm -p 8000:8000 urbanmine-api
```

The image bakes the YOLO and CLIP weights at build time, so cold starts do not
download them. It takes a few minutes the first time. `docs/DECISIONS.md` has
why it is a container at all.

## The tree

```
urbanmine/
├── README.md              this file: run it, find it
├── AGENTS.md              rules for whoever (or whatever) edits this next
├── LICENSE                MIT
├── render.yaml            Render blueprint, docker runtime
├── docker-compose.yml     optional local Postgres for testing the pg path
├── docs/
│   ├── DECISIONS.md           why docker, why Neon, why Postgres and not SQLite,
│   │                          and where each hard problem was actually solved
│   ├── DEPLOY.md              live URLs and every deploy command
│   └── PROJECT-FULLSTACK.md   module-by-module code reference
├── scripts/
│   ├── publish-here.py    publish frontend/dist to here.now
│   ├── publish-pick.py    publish a few times, keep the nicest slug
│   └── deploy-space.sh    clean copy of backend/ to a Hugging Face Space
├── backend/
│   ├── app/
│   │   ├── main.py            routes only
│   │   ├── schemas.py         what JSON is valid
│   │   ├── core/
│   │   │   ├── catalog.py     16 materials: units, salvage prices, CO2, prompts, gates
│   │   │   └── scoring.py     distance + match score + quantity
│   │   ├── ai/
│   │   │   └── vision.py      YOLO-World + YOLOv8n + colour pass + CLIP
│   │   └── storage/
│   │       ├── store.py       Postgres or data.json, plus the photo bytes
│   │       └── images.py      resize to 1600px, thumbnail to 480px
│   ├── tests/                 stdlib unittest, models stubbed
│   ├── data.json              the fallback store, used only in json mode
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── .env.example
│   └── vercel.json            framework: container
└── frontend/
    ├── index.html
    ├── vite.config.js         port 5173, proxy to 8000, HTTPS for phone camera
    ├── vercel.json            /api and /uploads rewrites to the backend
    ├── package.json
    └── src/
        ├── main.jsx
        ├── App.jsx            shell + Upload / Market / Match / Requests / Impact
        ├── components/
        │   ├── LocationPicker.jsx
        │   └── MeasureModal.jsx   a ruler on the photo, so quantity is measured
        ├── lib/
        │   ├── cesium.js
        │   └── measureMath.js
        ├── styles/styles.css
        └── assets/
```

Not in git: `node_modules`, `frontend/dist`, `*.pt` (auto-downloaded), `uploads/`,
logs, `.env`. `data.json` is tracked on purpose — it is the fallback store, and it
stays empty until someone publishes while running in json mode.

## One file, one question

The backend used to be one big `main.py`. It is now seven small modules, and the
rule is that each one answers exactly one question. If you cannot answer "what
question does this file answer" in one sentence, the file is doing too much.

| File | Answers |
|---|---|
| `app/main.py` | What does the HTTP surface look like? Routes only: parse, call one function, return. No AI, no maths. |
| `app/schemas.py` | What JSON is legal? Pydantic shapes, no logic. |
| `app/core/catalog.py` | What is a material, what is it worth? 16 materials, units, salvage prices, CO2 factors, ~60 detection prompts, the hard negatives, the CLIP threshold. |
| `app/core/scoring.py` | How near, how much, how good a match? `haversine_km`, `qty_for`, `match_score`. Pure maths, no I/O, which is why the tests pin it. |
| `app/ai/vision.py` | What is in this photo? Four passes merged into one ranked list. Models load lazily, never at import. |
| `app/storage/store.py` | Where do listings live? Postgres when `DATABASE_URL` is set, `data.json` when it is not. Same two functions either way. |
| `app/storage/images.py` | How big is a stored photo? One bounded 1600px copy and one 480px thumbnail. |

Frontend is the same idea: `App.jsx` for the shell and the five panels,
`LocationPicker` for "where is this", `MeasureModal` + `measureMath` for "how
big is this", `cesium.js` for the globe, `styles.css` for the look.

Match score is material 40, quantity 25, distance 20 (zero past 50 km), condition
15. Quantities come from measured coverage, never from a random number.

## Data: Postgres if you set it, JSON if you don't

`store.py` checks `DATABASE_URL`. Set it and the state is one JSONB row in Neon,
and photos are `BYTEA` rows next to it. Leave it empty and everything lives in
`backend/data.json` plus `backend/uploads/`.

Nothing else in the app changes, because nothing else calls the database
directly. `/api/health` tells you which mode is live.

The one-row shape is a demo decision with a known cost: two workers saving at the
same moment can overwrite each other. Split listings and requests into real
tables before that starts to matter.

## Why the stack looks like this

Short version, because these questions get asked every time someone new opens
the repo:

- **Docker** — the backend is ~2GB of Python and ~150MB of weights. A normal
  serverless function cannot carry that, so it ships as a container.
- **Neon** — serverless Postgres with a pooled connection string, because the
  container opens a short connection per request and instances come and go.
- **Postgres, not SQLite** — SQLite is a file on one disk. The backend runs on
  hosts that throw the disk away between requests and run more than one
  instance, so a file is not a database here. Postgres is one address everyone
  can see.
- **FastAPI, not Express** — the AI is Python. Calling python from Node per
  photo would add a hop and a failure mode for nothing.
- **Cesium, not Leaflet** — satellite-first presentation with a terrain and 3D
  tiles path, and one helper that covers both globes.
- **YOLO-World + CLIP, not a trained model** — there is no labelled demolition
  dataset. Prompts work on day one; training is the move once `uploads/` has
  enough real, labelled site photos.

Full reasoning, including what each choice cost us, is in
[`docs/DECISIONS.md`](docs/DECISIONS.md). The "where did we actually fix that"
table is at the bottom of the same file.

## Deploying

Frontend on Vercel, backend on Vercel container runtime, database on Neon. The
frontend is the only public URL; its `vercel.json` rewrites `/api` and
`/uploads` to the backend alias, so the browser never makes a cross-origin call.

Every command, the aliases, and the traps (the alias does not follow new
deployments, Hobby caps the body at 4.5MB, the container cold-start loads
weights) are in [`docs/DEPLOY.md`](docs/DEPLOY.md).

## Sharing while the backend is local

Any share link is a frozen frontend build wired through a tunnel to a laptop. It
dies when the laptop sleeps or the tunnel restarts, and an anonymous slug cannot
be revived. So: demo on localhost, publish only when explicitly asked.

- Same Wi-Fi phone: `HTTPS=1 npm run dev -- --host`, open
  `https://<mac-lan-ip>:5173`, accept the self-signed cert. HTTPS is what
  unlocks camera and geolocation on mobile browsers.
- Public link: `cloudflared tunnel --url http://localhost:8000`, then
  `VITE_API_BASE=<url> npm run build` in `frontend/`, then
  `python scripts/publish-here.py`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `connection refused :8000` | Backend is not running. Check terminal 1, and that the interpreter has the requirements. |
| `Analysis failed` | Backend down, or the file is over 25MB. Read the backend log. |
| First photo is slow | Normal. The weights are loading. Later photos are seconds. |
| `No GPS tag` | Screenshots and downloads have no EXIF. Use search, a preset, device GPS, or tap the map. |
| Globe is dark | The Cesium CDN did not load. The pickers still work. |
| Port busy | `lsof -ti:5173 \| xargs kill`, same for 8000. |
| Old UI | `⌘⇧R`. Dev hot-reloads; `dist/` only matters for `npm run preview`. |
| Photos 404 after a while | The host wiped its disk. `save_image` keeps a copy in Postgres; in json mode the file is gone. |

## Where to read next

- [`docs/DECISIONS.md`](docs/DECISIONS.md) — why each piece is what it is, what
  it cost, and where the hard bugs were solved.
- [`docs/PROJECT-FULLSTACK.md`](docs/PROJECT-FULLSTACK.md) — the codebase
  module by module.
- [`docs/DEPLOY.md`](docs/DEPLOY.md) — hosts, aliases, deploy commands.
- [`AGENTS.md`](AGENTS.md) — the rules for editing this repo.
