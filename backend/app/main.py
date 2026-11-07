# UrbanMine Backend — routes only. The thinking lives in app/core, app/ai, app/storage.
# Run from backend/ with: python -m uvicorn app.main:app --port 8000

import io
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.ai.vision import _last_debug, YOLO_AVAILABLE, detect_materials, provider_name, world_model
from app.core.catalog import MATERIAL_META
from app.core.ratelimit import SlidingWindow, client_ip
from app.core.scoring import haversine_km, match_score
from app.schemas import BuyerRequest, ListingConfirm, ListingPatch, MatchRequest, RequestPatch
from app.storage.images import THUMB_MAX, photo_jpeg
from app.storage.store import DATABASE_URL, UPLOAD_DIR, delete_image, load_db, load_image, save_db, save_image

# this is the main app object
# all routes are attached to this
app = FastAPI(title="UrbanMine API")

# 25MB is what the UI promises and plenty for a phone photo the browser has
# already shrunk. Nothing larger is read off the socket.
MAX_UPLOAD_BYTES = int(float(os.getenv("MAX_UPLOAD_MB", "25")) * 1024 * 1024)
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}

# One browser must not be able to queue twenty analyses. Per instance and in
# memory: enough for a demo, not a defence against a distributed attack.
ANALYZE_LIMIT = SlidingWindow(limit=int(os.getenv("ANALYZE_PER_MINUTE", "20")), window_s=60)

# In production the browser calls /api on its own origin (Vercel rewrites it to
# this service), so "*" is only needed for a tunnel or a phone on the LAN.
# Credentials are off on purpose: there are no cookies here, and "*" combined
# with credentials is both unsafe and rejected by browsers anyway.
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
    max_age=600,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    # This service returns JSON and image bytes, never HTML. These headers stop
    # a browser from MIME-sniffing an upload, framing the API, or forwarding the
    # referrer, and they cost nothing.
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Permissions-Policy", "geolocation=(self), camera=(self)")
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    if https:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response

# the marketplace starts empty. only real listings created by users are saved.
# if the database is down, the app still starts and the error shows in the log


@app.get("/")
def root():
    # a small landing response, so the Space URL is not a bare 404
    return {"name": "UrbanMine API", "docs": "/docs", "health": "/api/health"}


@app.get("/api/health")
def health():
    # this tells us if the server is alive and how many listings exist
    # yolo and world flags show if the AI models are loaded
    # store says where the data lives: postgres or json
    db = load_db()
    return {
        "status": "ok",
        "yolo": YOLO_AVAILABLE,
        "world": bool(world_model),
        "store": "postgres" if DATABASE_URL else "json",
        # which AI path the next analyze takes: a hosted model or the local stack
        "ai": provider_name(),
        "listings": len(db["listings"]),
        "requests": len(db["requests"]),
    }


@app.post("/api/analyze")
async def analyze(request: Request,
                  file: UploadFile = File(...),
                  # optional on purpose: a photo with no point is honest, and the
                  # server must never invent a city for it
                  lat: Optional[float] = Form(None),
                  lng: Optional[float] = Form(None),
                  address: str = Form(""),
                  debug: bool = Form(False)):
    # This is the one route that can cost money and minutes, so it is limited.
    # Behind Vercel/Cloudflare the socket peer is the proxy, so the key comes
    # from the forwarded address instead — otherwise every user shares a bucket.
    client = client_ip(request)
    if not ANALYZE_LIMIT.allow(client):
        raise HTTPException(status_code=429,
                            detail="Too many photos at once. Wait a minute, then try again.")

    # Type is checked before the body is read, and the read itself is capped, so
    # an enormous upload never lands in memory.
    declared = (file.content_type or "").split(";")[0].strip().lower()
    if declared not in ALLOWED_IMAGE_TYPES:
        return {"detections": [], "model": "rejected", "non_construction": [],
                "is_construction_site": True,
                "verification": {"checked": 0, "rejected": 0, "kept": 0},
                "error": "Use a JPG, PNG or WebP photo."}

    # photo comes in here, we save it, run AI, return what materials we found
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        return {"detections": [], "model": "rejected", "non_construction": [],
                "is_construction_site": True,
                "verification": {"checked": 0, "rejected": 0, "kept": 0},
                "error": f"Photo too large ({MAX_UPLOAD_BYTES // (1024 * 1024)}MB max)."}

    # PIL is Python Imaging Library
    # it opens images and checks if they are real images
    # we use verify to make sure the file is actually JPG or PNG
    # and not some random file renamed to .jpg
    try:
        from PIL import Image as _PIL
        _PIL.open(io.BytesIO(raw)).verify()
    except Exception:
        return {"detections": [], "model": "rejected", "non_construction": [],
                "is_construction_site": True,
                "verification": {"checked": 0, "rejected": 0, "kept": 0},
                "error": "Not a valid image. Use JPG or PNG."}

    # one bounded JPEG, always .jpg. the browser already shrinks, but a direct
    # API call can send a 25MB photo, and that is what would get stored.
    try:
        photo = photo_jpeg(raw)
    except Exception:
        photo = raw

    # fid is a random id so two photos do not overwrite each other
    fid = f"{uuid.uuid4().hex[:10]}.jpg"
    (UPLOAD_DIR / fid).write_bytes(photo)
    # the disk above is just a warm cache. postgres is the real copy,
    # because the host wipes the folder between requests.
    save_image(fid, photo, "image/jpeg")

    # the feed only downloads this small copy. the viewer asks for image_url.
    thumb_url = None
    try:
        thumb = photo_jpeg(photo, THUMB_MAX, 72)
        thumb_fid = f"t{fid}"
        (UPLOAD_DIR / thumb_fid).write_bytes(thumb)
        save_image(thumb_fid, thumb, "image/jpeg")
        thumb_url = f"/uploads/{thumb_fid}"
    except Exception:
        thumb_url = None

    # this runs all the AI passes and returns what it found
    # detect_materials shrinks the photo once inside, then reuses that copy
    # dets is the list of materials found
    # model is which AI engines actually ran
    # others is things that are not construction (bedsheet, person, clothes)
    # is_site tells us if the photo looks like a construction site
    # verification is the "checked / rejected / kept" counter for the UI
    dets, model, others, is_site, verification = detect_materials(raw)

    resp = {
        "image_url": f"/uploads/{fid}",
        "thumb_url": thumb_url,
        "detections": dets,
        "model": model,
        "non_construction": others,
        "is_construction_site": is_site,
        "verification": verification,
    }

    if debug:
        resp["debug"] = _last_debug

    return resp


@app.post("/api/listings")
def create_listing(payload: ListingConfirm):
    # when user clicks confirm on a detection, it becomes a listing here
    db = load_db()

    # meta has the unit and default price for this material
    # comes from catalog.py MATERIAL_META
    meta = MATERIAL_META.get(payload.material, {"unit": "pcs", "price": 100})

    # this is the listing dictionary that gets saved
    listing = {
        "id": str(uuid.uuid4())[:8],
        "material": payload.material,
        "quantity": payload.quantity,
        "unit": payload.unit or meta["unit"],
        "condition": payload.condition,
        "price_per_unit": payload.price_per_unit or meta.get("price", 100),
        "lat": payload.lat,
        "lng": payload.lng,
        "address": payload.address,
        "contractor": payload.contractor,
        "title": payload.title or f"{payload.material} — {payload.quantity}",
        "description": payload.description,
        "confidence": payload.confidence,
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "image_url": payload.image_url,
        "thumb_url": payload.thumb_url,
        "bbox": payload.bbox,
        "dimensions": payload.dimensions,
        "dimensions_label": payload.dimensions_label,
    }

    # insert at the front so newest listings show first
    db["listings"].insert(0, listing)
    save_db(db)
    return listing


@app.get("/api/listings")
def list_listings(material: Optional[str] = None,
                  condition: Optional[str] = None,
                  q: Optional[str] = None,
                  lat: Optional[float] = None,
                  lng: Optional[float] = None,
                  max_distance_km: float = 100):
    # get all active listings, filtered and sorted by nearest first
    db = load_db()

    # only show active listings, not deleted ones
    out = [l for l in db["listings"] if l.get("status", "active") == "active"]

    # if user picked a material, keep only that material
    if material:
        out = [l for l in out if l["material"].lower() == material.lower()]

    # if user picked a condition, keep only that condition
    if condition:
        out = [l for l in out if l["condition"].lower() == condition.lower()]

    # if user typed a search word, look in title, description and material
    if q:
        needle = q.lower()
        out = [l for l in out
               if needle in (l.get("title", "") + l.get("description", "") + l["material"]).lower()]

    # if user gave a location, calculate distance and sort by nearest
    if lat is not None and lng is not None:
        with_dist = []
        # listings with no location cannot be measured. Keep them, listed after
        # the ones we can place, instead of hiding real inventory.
        no_point = []
        for l in out:
            if l.get("lat") is None or l.get("lng") is None:
                no_point.append({**l, "distance_km": None})
                continue
            # haversine_km gives distance between two lat lng points
            d = haversine_km(lat, lng, l["lat"], l["lng"])
            if d <= max_distance_km:
                with_dist.append({**l, "distance_km": round(d, 1)})
        out = sorted(with_dist, key=lambda x: x["distance_km"]) + no_point

    return out


@app.get("/api/listings/{lid}")
def get_listing(lid: str):
    # get one listing by its id
    db = load_db()
    for l in db["listings"]:
        if l["id"] == lid:
            return l
    raise HTTPException(status_code=404, detail="listing not found")


@app.patch("/api/listings/{lid}")
def patch_listing(lid: str, p: ListingPatch):
    # edit a listing: change quantity, condition, price or status
    db = load_db()
    for l in db["listings"]:
        if l["id"] == lid:
            # p.model_dump(exclude_none=True) gives only the fields user sent
            for k, v in p.model_dump(exclude_none=True).items():
                l[k] = v
            save_db(db)
            return l
    raise HTTPException(status_code=404, detail="listing not found")


@app.delete("/api/listings/{lid}")
def delete_listing(lid: str):
    # removing a listing also removes its photos, so dead bytes do not pile up
    db = load_db()
    listing = next((l for l in db["listings"] if l["id"] == lid), None)
    if not listing:
        raise HTTPException(status_code=404, detail="listing not found")

    db["listings"] = [l for l in db["listings"] if l["id"] != lid]

    # two listings can point at the same photo, so only drop a file nothing else uses
    for key in ("image_url", "thumb_url"):
        url = listing.get(key)
        if not url:
            continue
        fid = url.rsplit("/", 1)[-1]
        still_used = any(
            fid in (l.get("image_url") or "") or fid in (l.get("thumb_url") or "")
            for l in db["listings"]
        )
        if not still_used:
            delete_image(fid)

    save_db(db)
    return {"deleted": lid}


@app.post("/api/match")
def match(m: MatchRequest):
    # rank listings by how well they match what the buyer wants
    # score is material 40 + quantity 25 + distance 20 + condition 15
    db = load_db()
    scored = []
    for l in db["listings"]:
        if l.get("status") != "active":
            continue
        # a listing with no coordinates has no distance, so it cannot be scored
        if l.get("lat") is None or l.get("lng") is None:
            continue
        # match_score returns (score, distance)
        score, dist = match_score(l, m.material, m.quantity, m.lat, m.lng, m.condition)
        if dist <= m.max_distance_km:
            scored.append({**l, "match_score": score, "distance_km": dist})
    scored.sort(key=lambda x: -x["match_score"])
    return {"results": scored[:20]}


@app.post("/api/requests")
def create_request(r: BuyerRequest):
    # buyer clicks request material, this creates a pending request
    db = load_db()
    listing = next((l for l in db["listings"] if l["id"] == r.listing_id), None)
    if not listing:
        raise HTTPException(status_code=404, detail="listing not found")

    req = {
        "id": str(uuid.uuid4())[:8],
        "listing_id": r.listing_id,
        "listing_title": listing["title"],
        "contractor": listing.get("contractor"),
        "buyer_name": r.buyer_name,
        "buyer_type": r.buyer_type,
        "quantity": r.quantity or listing["quantity"],
        "message": r.message,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db["requests"].insert(0, req)
    save_db(db)
    return req


@app.get("/api/requests")
def list_requests():
    # return all buyer requests
    return load_db()["requests"]


@app.patch("/api/requests/{rid}")
def patch_request(rid: str, p: RequestPatch):
    # contractor accepts or declines a request
    db = load_db()
    for r in db["requests"]:
        if r["id"] == rid:
            r["status"] = p.status
            save_db(db)
            return r
    raise HTTPException(status_code=404, detail="request not found")


@app.get("/api/materials")
def materials():
    # return all 16 materials so frontend can show them in dropdowns
    return [{"name": k, **v} for k, v in MATERIAL_META.items()]


# this serves photos at /uploads/filename.
# disk first (fast, warm instance), then postgres (survives a cold start).
@app.get("/uploads/{fid}")
def upload(fid: str):
    # fid is a plain filename. anything with a slash is not ours.
    if "/" in fid or "\\" in fid or fid.startswith("."):
        raise HTTPException(status_code=404, detail="image not found")

    # a random fid never changes content, so the browser can keep it for good
    cache = {"Cache-Control": "public, max-age=31536000, immutable"}

    path = UPLOAD_DIR / fid
    if path.exists():
        return FileResponse(path, headers=cache)

    raw, ctype = load_image(fid)
    if not raw:
        raise HTTPException(status_code=404, detail="image not found")
    return Response(content=raw, media_type=ctype or "image/jpeg", headers=cache)
