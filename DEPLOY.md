# Host UrbanMine

| Piece | Host | Cost |
|---|---|---|
| Frontend | Vercel | free |
| Backend | Hugging Face Docker Space | needs HF PRO, $9/month |
| Database | Neon Postgres | free tier |
| Photos | `/tmp/uploads` | ephemeral |

The backend is the expensive part. It loads torch, ultralytics, transformers,
and about 150MB of model weights. That does not fit in a free JavaScript
serverless function.

## Why Vercel cannot run the backend

Vercel does run Python functions, but the Hobby plan caps the bundle at 250MB
and the request at 10s. torch, ultralytics, transformers, and the weights pass
both limits before the app starts. Vercel serves the React build only.

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

## 2. Backend on Hugging Face Spaces

Docker Spaces require a PRO account as of 2026. Check first:

```bash
hf auth whoami
```

If that says not logged in:

```bash
hf auth login
```

Then deploy from the repo root:

```bash
./scripts/deploy-space.sh <your-hf-username>/urbanmine-backend
```

The script creates a public Docker Space, sets `DATABASE_URL` as a Space
secret from `backend/.env`, and uploads a clean copy. It excludes `.env`,
model weights, uploads, `data.json`, tests, and logs. Those must never go to a
public Space.

Manual version if you prefer the web UI:

1. Create a Space, SDK Docker, public.
2. Set the secret `DATABASE_URL` to the Neon pooled URL.
3. Upload `backend/` without `.env`, `*.pt`, `uploads/`, and `data.json`.
4. The Space uses `backend/README.md` for its card and port.

Hugging Face routes traffic to `7860`. The Dockerfile reads `PORT` when it
exists and falls back to `7860`, so the same image works on Render too.

The Space URL looks like:

```
https://huggingface.co/spaces/<user>/urbanmine-backend
https://<user>-urbanmine-backend.hf.space
```

The second one is the API base the frontend needs. Check it:

```bash
curl https://<user>-urbanmine-backend.hf.space/api/health
```

The first analyze request downloads and loads the weights, so it can take a
minute. On free CPU hardware the Space sleeps when idle and wakes on the next
request. The database stays awake independently.

## 3. Frontend on Vercel

This is React + Vite, not Next.js. The variable is `VITE_API_BASE`, not
`NEXT_PUBLIC_API_URL`. The analyze call is already wired in `App.jsx` as
`POST /api/analyze` with multipart `file`.

```bash
cd frontend
vercel --prod --build-env VITE_API_BASE=https://<user>-urbanmine-backend.hf.space
```

Or set it once and redeploy:

```bash
vercel env add VITE_API_BASE production
# paste the Space URL
vercel --prod
```

Vite bakes the value into the build, so changing the env var needs a rebuild.
The backend allows all origins, so the Vercel domain can call the Space
directly.

## 4. Check the live app

```bash
curl https://<user>-urbanmine-backend.hf.space/api/health
# {"status":"ok","yolo":true,"world":true,"store":"postgres",...}
```

Open the Vercel URL and upload a photo. If `yolo` or `world` is false, check
the Space logs. The usual cause is memory or a missing model download. The
visual pass still runs, and the analyze response's `model` field says what
actually ran.

## 5. Photos

`UPLOAD_DIR` defaults to `backend/uploads`. The Dockerfile sets it to
`/tmp/uploads` because Space, Render, and Fly disks are ephemeral. Old
`image_url` values can 404 after a restart. For files that must survive, upload
to S3, Cloudflare R2, or Neon Object Storage and store the public URL. That is
a `store.py` change, not a UI change.

## 6. If you do not have HF PRO

Docker Spaces are no longer free for personal accounts. The options that do
not charge monthly:

- Oracle Cloud Always Free: an ARM VM with enough RAM to run the Dockerfile.
  Truly free if your account has the allowance, but you manage the VM, TLS,
  and restarts.
- Modal: new accounts get monthly free credits. It runs the same container
  serverless. Cold starts are slower because the weights load on first use.
- Local machine plus a Cloudflare tunnel: free, but the laptop must stay awake
  and the tunnel dies when it closes.
- Render free web service: 512MB, which is likely too small for YOLO-World and
  CLIP. The Starter plan with 2GB is about $7/month.

Do not plan around a free Hugging Face Docker Space. That changed.

## 7. Local JSON mode

With no `DATABASE_URL`, the app uses `backend/data.json`, same as before.
Nothing else changes. The test suite uses this mode.
