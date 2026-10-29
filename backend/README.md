---
title: UrbanMine API
sdk: docker
app_port: 7860
short_description: FastAPI and YOLO material detection for UrbanMine
tags:
  - urbanmine
  - fastapi
  - yolo
---

# UrbanMine API

FastAPI backend for UrbanMine. It takes a demolition photo, runs YOLOv8n,
YOLO-World, a color pass, and a CLIP gate, then returns salvage materials with
quantities and prices. Listings live in Postgres when `DATABASE_URL` is set,
otherwise in `data.json`.

## Space settings

Add this as a secret in the Space settings, never in the repo:

```
DATABASE_URL=postgresql://...-pooler.../neondb?sslmode=require
```

Use the pooled Neon URL. The `-pooler` host keeps concurrent requests from
exhausting direct Postgres connections.

`UPLOAD_DIR` is already set to `/tmp/uploads` in the Dockerfile. That disk is
ephemeral, so uploaded photos disappear when the Space restarts. Move uploads
to object storage for files that must survive.

## Ports

Hugging Face routes to `7860`. The Dockerfile reads `PORT` when it exists and
falls back to `7860`, so the same image also works on Render.

## Endpoints

- `GET /api/health` returns `status`, `yolo`, `world`, `store`, and counts.
- `POST /api/analyze` takes multipart `file`, `lat`, `lng`, `address`, and an
  optional `debug`.
- `GET /api/listings`, `POST /api/listings`, `POST /api/match`,
  `GET /api/requests`, `GET /api/materials`.

The frontend talks to this API through `VITE_API_BASE`. CORS is open, so the
Vercel build can call the Space directly.
