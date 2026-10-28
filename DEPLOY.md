# Host UrbanMine

| Piece | Host | Cost |
|---|---|---|
| Frontend | Vercel | free |
| Backend | Vercel Container Runtime | free on Hobby, Active CPU limits |
| Database | Neon Postgres | free tier |
| Photos | `/tmp/uploads` | ephemeral |

The backend loads torch, ultralytics, transformers, and about 150MB of model
weights. That does not fit in a normal JavaScript serverless function. Vercel
now has a Container Runtime (beta, all plans) that runs the Dockerfile with
2GB RAM and 300s per request on Hobby, so the same image that runs locally
runs there.

## 1. Database

The Neon project `urbanmine` is in Singapore. Its pooled connection string is
in `backend/.env`, which is gitignored. The host contains `-pooler`, so
concurrent API requests go through PgBouncer instead of opening direct
Postgres connections.

To use it locally:

```bash
cd backend
set -a; . ./.env; set +a
python3 -m uvicorn main:app --port 8000
```

`GET /api/health` should show `"store": "postgres"`.

The table is created on the first call:

```sql
CREATE TABLE IF NOT EXISTS urbanmine_state (
  id INTEGER PRIMARY KEY,
  data JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

One JSONB row holds the whole app state. That is fine for a demo. If two
workers write at the same moment, the last write wins. Split listings and
requests into real tables before that matters.

This is plain Postgres 17, not PostGIS. UrbanMine does distance math in
`scoring.py` with haversine, so no spatial extension is needed. Enable PostGIS
later only if you move radius filtering into SQL.

## 2. Backend on Vercel containers

The backend folder has a `Dockerfile` and `vercel.json` with
`"framework": "container"`. Vercel builds the image, pushes it to its
container registry, and routes traffic to the port in `PORT`.

First time:

```bash
cd backend
vercel link --yes
vercel env add PORT production --value 7860 --no-sensitive
# paste the Neon pooled URL when prompted
vercel env add DATABASE_URL production --sensitive
vercel deploy --prod --yes
```

After that, one command redeploys:

```bash
cd backend
vercel deploy --prod --yes
```

The first build takes about 4 minutes. The Dockerfile downloads the YOLO
weights and the CLIP model at build time, so cold starts do not fetch them.
It also runs `set_classes()` once as a build check. YOLO-World imports the
OpenAI `clip` package for that call, and `ultralytics` does not install it,
so `clip-anytorch` is in `requirements.txt`. If that import breaks, the image
build fails instead of quietly serving without YOLO-World.

The production alias looks like:

```
https://backend-one-chi-21.vercel.app
```

The deployment URL (`backend-<hash>-...vercel.app`) is protected by Vercel
Authentication. Use the alias for public API calls.

Check it:

```bash
curl https://backend-one-chi-21.vercel.app/api/health
# {"status":"ok","yolo":true,"world":true,"store":"postgres","listings":6}
```

`yolo` and `world` describe the instance that answered. Vercel can scale to
zero and start a fresh container for the next request, so a health check on a
cold instance can show `false` even though the previous analyze used both
models. The `model` field on an analyze response is the reliable answer for
that request.

Vercel Hobby caps the request body at 4.5MB. The frontend already shrinks
photos to 1600px JPEG before upload, which stays well under that. A very
large or unusual file can still get a 413; resize it or raise the limit on a
paid plan.

## 3. Frontend on Vercel

This is React + Vite, not Next.js. The variable is `VITE_API_BASE`, not
`NEXT_PUBLIC_API_URL`. The analyze call is already wired in `App.jsx` as
`POST /api/analyze` with multipart `file`.

The frontend is the only public URL. `frontend/vercel.json` rewrites
`/api/*` to the backend alias, so the browser calls the same origin and CORS
never enters the picture:

```json
"rewrites": [
  {
    "source": "/api/(.*)",
    "destination": "https://backend-one-chi-21.vercel.app/api/$1"
  }
]
```

Build without `VITE_API_BASE`. It defaults to an empty string, which makes
every fetch relative:

```bash
cd frontend
vercel deploy --prod --yes --project fullstackproject
```

The Vercel project is `fullstackproject`. Its production deployment gets an
auto-generated URL, and the public URL is the alias:

```
https://fullstackproject-app.vercel.app
```

`fullstackproject.vercel.app` was already taken, so the public alias has the
`-app` suffix. The project's default URL
(`frontend-beta-eight-0lk6qa024w.vercel.app`) keeps changing with deploys and
is not the link to share. After every production deploy, point the alias at
the new deployment:

```bash
vercel alias set <deployment-url> fullstackproject-app.vercel.app
```

The alias does not follow new deployments by itself. Use the deployment URL
printed by `vercel deploy` (or `--json` and read `.deployment.url`). Skipping
this step leaves the old build live at the public URL.

The project has Vercel Authentication turned off (`ssoProtection: null`).
Without that, the alias answers with a 302 to the Vercel login page even
though the deployment is fine. Check it with:

```bash
vercel project protection fullstackproject
```

If the backend alias changes, update the rewrite and redeploy. The frontend
URL stays the same.

## 4. Check the live app

```bash
curl https://fullstackproject-app.vercel.app/api/health
# {"status":"ok","yolo":true,"world":true,"store":"postgres","listings":6}
```

Open that same frontend URL and upload a photo. A real demolition photo
should return detections and a listing draft. A bedsheet, person, or food
photo should come back with `is_construction_site: false` and no listings.
Add `?debug=1` to the analyze request to see the raw boxes and the CLIP
scores.

The backend alias still works directly for debugging, but users only need
the frontend URL.

The first analyze request on a cold container loads the weights and can take
30-60s. Later requests on the same warm instance are much faster.

## 5. Photos

`UPLOAD_DIR` defaults to `backend/uploads`. The Dockerfile sets it to
`/tmp/uploads` because Vercel, Spaces, Render, and Fly disks are ephemeral.
Old `image_url` values can 404 after a restart. For files that must survive,
upload to S3, Cloudflare R2, or Neon Object Storage and store the public URL.
That is a `store.py` change, not a UI change.

## 6. Other hosts

Hugging Face Docker Spaces now require PRO ($9/month). `backend/README.md` is
still a valid Space card and `scripts/deploy-space.sh` still uploads a clean
copy, but do not plan around a free Space.

The options that do not charge monthly:

- Oracle Cloud Always Free: an ARM VM with enough RAM to run the Dockerfile.
  Truly free if your account has the allowance, but you manage the VM, TLS,
  and restarts.
- Modal: new accounts get monthly free credits. It runs the same container
  serverless. Cold starts are slower because the weights load on first use.
- Local machine plus a Cloudflare tunnel: free, but the laptop must stay awake
  and the tunnel dies when it closes.
- Render free web service: 512MB, which is too small for YOLO-World and CLIP.
  The Starter plan with 2GB is about $7/month.

## 7. Local JSON mode

With no `DATABASE_URL`, the app uses `backend/data.json`, same as before.
Nothing else changes. The test suite uses this mode.
