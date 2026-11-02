# UrbanMine — plain-English technical glossary

Use this to remember what the project's technical terms mean.

## AI models

**YOLOv8n** — A small object detector. It sees everyday things in a photo (a chair, a bus, a person) and guesses what material they are. The "n" means nano — the small, fast version.

**YOLO-World** — An object detector you give text prompts to, like "stack of red bricks" or "wooden door." This is the model that actually knows salvage materials.

**CLIP** — Looks at an image and decides: is this a construction site or a household scene? It's the gatekeeper that stops a bedsheet, pen, person, or bedroom from becoming a listing.

**COCO** — A dataset YOLOv8n was trained on. It knows 80 everyday objects (person, chair, car, bed…). Not materials — just everyday things.

**Confidence** — How sure the AI is, from 0 to 1. 0.90 = very sure; 0.15 = guessing.

**Bbox** — Bounding box. The rectangle around a detected object, stored as coordinates (0 to 1). The UI uses it to crop that exact spot from the photo.

**Verification counter** — The `checked / rejected / kept` numbers shown in the Upload UI. How many boxes CLIP looked at, threw away, and kept as real listings.

## Backend (server)

**FastAPI** — Python web framework. Runs all the `/api/…` routes (analyze, listings, match, requests, uploads).

**Uvicorn** — The server that runs FastAPI. You start it with `python -m uvicorn app.main:app`.

**Pydantic** — Checks that incoming JSON has the right fields (material, quantity, price…) before the backend saves it.

**Route / endpoint** — A URL the frontend calls, like `/api/analyze` or `/api/listings`.

**CORS** — Browser security rule that stops a page from calling a different origin. The `frontend/vercel.json` rewrites `/api` and `/uploads` to the backend, so they're the same origin and CORS never blocks calls.

**Static files** — Files served directly, like photos at `/uploads/filename.jpg`.

**Middleware** — Code that runs on every request, like the CORS handler.

**psycopg** — Python library that talks to Postgres. Only used when `DATABASE_URL` is set.

**JSONB** — Postgres column type that stores JSON. The whole database state (listings + requests) lives in one JSONB row.

**BYTEA** — Postgres column type that stores raw file bytes. Photos are saved here so they survive when the server disk is wiped.

**Haversine** — Math formula for distance between two lat/lng points on Earth. Used for "X km away."

**Hot reload** — When you change code and the server restarts automatically. `uvicorn --reload` does this.

## Frontend (what the user sees)

**React** — JavaScript library that builds the page. The UI updates when data changes without reloading.

**Vite** — Tool that starts the dev server (`npm run dev`) and builds for production (`npm run build`). Fast refresh while coding.

**JSX** — Writing HTML-like code inside JavaScript in React components.

**Tailwind CSS** — Styling library. Colors, spacing, and layout are done with classes like `card bezel` instead of separate CSS files.

**Cesium** — 3D globe library (WebGL). Shows the satellite map with pins for listings.

**WebGL** — Browser technology that lets Cesium draw 3D graphics using the graphics card.

**GSAP** — Animation library used for tab switches and sidebar motion.

**exifr** — Reads GPS tags from photo EXIF data so the backend knows where a photo was taken.

**Single-page app (SPA)** — One HTML page; React swaps the tab content without reloading.

## Address & maps

**Nominatim** — Address lookup engine (OpenStreetMap). Turns "HSR Layout, Bengaluru" into lat/lng coordinates. Reverse geocoding does the opposite: lat/lng → address.

**Area preset** — Quick pick of a Bengaluru neighborhood (Koramangala, HSR, Whitefield…).

## Hosting & deploy

**Vercel** — Hosting platform. Runs the frontend and backend.

**Neon** — Serverless Postgres database in the cloud. The production database.

**Alias** — Vercel feature that makes `fullstackproject-app.vercel.app` point to your latest deployment. Must be re-run after every frontend deploy.

**Docker** — Packages the backend into a container image so it runs the same everywhere, including the AI model weights.

**Environment variable** — A setting not hardcoded in code. `DATABASE_URL` tells the backend where Postgres is. `VITE_API_BASE` tells the frontend where the backend is.

**Cold start** — When a serverless function wakes up after being idle. The backend takes a few seconds to load AI weights on the first request.

## Project-specific

**Material meta** — `catalog.py`: all 16 materials, their units (sq ft, pcs, kg), salvage prices, icons, CO₂ factors, and detection prompts.

**Match score** — Ranking formula: material 40% + quantity 25% + distance 20% + condition 15%.

**Impact tab** — Removed. Was the CO₂/value dashboard. `/api/impact` now returns 404.

**Work-in-progress (WIP) panel** — The yellow sticky note shown on tabs 3 and 4 (Smart Match, Requests) because they're half built.

**Measure tool** — The ruler on the photo where you drag length × width to calculate quantity.
