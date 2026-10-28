# Host UrbanMine

Four pieces:

| Piece | Where | Why |
|---|---|---|
| Frontend | Vercel | static Vite build, free |
| Backend | Render, Fly.io, or Hugging Face Spaces | needs 2GB RAM and a long timeout for YOLO |
| Database | Neon Postgres | project `urbanmine`, URL in `backend/.env` |
| Photos | local disk for now | move to S3 or R2 when they need to survive restarts |

## Why the backend is not on Vercel

Vercel functions cap the bundle at 250MB and the request at 10s on Hobby.
torch, ultralytics, and transformers pass that limit before the model weights.
The backend also writes photos to disk, and Vercel only allows writes to
`/tmp`.

So Vercel serves the React app. A container host runs FastAPI.

## 1. Database

The Neon project `urbanmine` is created in Singapore. The pooled connection
string is in `backend/.env`, which is gitignored. To use it locally:

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

## 2. Backend

### Render

`render.yaml` is in the repo root. In Render:

1. New > Blueprint > connect `Aayush-Ate/urbanmine`.
2. Set `DATABASE_URL` to the Neon pooled URL.
3. Deploy on the Standard plan (2GB). Starter has 512MB and will run out of
   memory when YOLO-World loads.

The Dockerfile installs CPU torch first, so pip does not pull the CUDA build.
The first analyze request downloads about 150MB of weights. After that it is
fast.

### Hugging Face Spaces

Spaces give 16GB RAM on the free CPU tier, which is enough for YOLO.

1. Create a Docker Space.
2. Copy `backend/` into it, including `Dockerfile`.
3. Add `DATABASE_URL` as a Space secret.
4. Set the app port to 8000.

Spaces sleep when idle, so the first request after a sleep is slow.

### Fly.io

```bash
cd backend
fly launch --dockerfile Dockerfile
fly secrets set DATABASE_URL='postgresql://...'
fly scale memory 2048
fly deploy
```

## 3. Frontend on Vercel

```bash
cd frontend
vercel --prod
```

Accept the defaults. Then point the build at the backend:

```bash
vercel env add VITE_API_BASE production
# paste https://your-backend-url
vercel --prod
```

Vite bakes `VITE_API_BASE` at build time, so redeploy after changing it.

One-shot version:

```bash
cd frontend
vercel --prod --build-env VITE_API_BASE=https://your-backend-url
```

## 4. Check

```bash
curl https://your-backend-url/api/health
# {"status":"ok","yolo":true,"world":true,"store":"postgres",...}
```

Open the Vercel URL and upload a photo. If `yolo` or `world` is false, the
container is missing ultralytics or ran out of memory. The visual pass still
works, and the `model` field in the analyze response says what actually ran.

## 5. Photos

`UPLOAD_DIR` defaults to `backend/uploads`. On Render and Fly, set
`UPLOAD_DIR=/tmp/uploads`. Files there disappear on restart, so an old
`image_url` can 404.

For real use, upload to S3, Cloudflare R2, or Neon Object Storage and store
the public URL. That is a `store.py` change, not a UI change.

## 6. Local JSON mode

With no `DATABASE_URL`, the app uses `backend/data.json`, same as before.
Nothing else changes. The test suite uses this mode.
