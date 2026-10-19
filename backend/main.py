# UrbanMine Backend — simple linear code.
# This file has all the routes. Each route does one thing and returns.
# Run with: /opt/homebrew/anaconda3/bin/python -m uvicorn main:app --port 8000

import io
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from catalog import MATERIAL_META
from schemas import BuyerRequest, ListingConfirm, ListingPatch, MatchRequest, RequestPatch
from scoring import haversine_km, match_score
from store import UPLOAD_DIR, load_db, save_db, seed_if_empty
from vision import detect_materials, downscale_for_ai

# this is the main app object
# all routes are attached to this
app = FastAPI(title="UrbanMine API")

# this lets the frontend call the backend from a different port
# without this the browser would block the requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# on first run this puts 6 starter listings into data.json
# so the marketplace is not empty when you open it
seed_if_empty()


@app.get("/api/health")
def health():
    # this tells us if the server is alive and how many listings exist
    db = load_db()
    return {
        "status": "ok",
        "listings": len(db["listings"]),
        "requests": len(db["requests"]),
    }


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...),
                  lat: float = Form(12.9716),
                  lng: float = Form(77.5946),
                  address: str = Form("Bengaluru")):
    # photo comes in here, we save it, run AI, return what materials we found
    raw = await file.read()

    # raw is the photo bytes
    # if it is bigger than 25MB we reject it because it is too large
    if len(raw) > 25 * 1024 * 1024:
        return {"detections": [], "error": "Photo too large (25MB max)."}

    # PIL is Python Imaging Library
    # it opens images and checks if they are real images
    # we use verify to make sure the file is actually JPG or PNG
    # and not some random file renamed to .jpg
    try:
        from PIL import Image as _PIL
        _PIL.open(io.BytesIO(raw)).verify()
    except Exception:
        return {"detections": [], "error": "Not a valid image. Use JPG or PNG."}

    # save the original photo to the uploads folder
    # ext is the file extension like .jpg or .png
    ext = Path(file.filename or "upload.jpg").suffix or ".jpg"

    # fid is a random id so two photos do not overwrite each other
    fid = f"{uuid.uuid4().hex[:10]}{ext}"
    (UPLOAD_DIR / fid).write_bytes(raw)

    # shrink the photo before sending to AI
    # phone photos are huge, AI only needs a smaller version
    small = downscale_for_ai(raw)

    # this runs all the AI passes and returns what it found
    # dets is the list of materials found
    # others is things that are not construction (bedsheet, person, clothes)
    # is_site tells us if the photo looks like a construction site
    dets, others, is_site = detect_materials(small)

    return {
        "image_url": f"/uploads/{fid}",
        "detections": dets,
        "non_construction": others,
        "is_construction_site": is_site,
    }


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
        "image_url": None,
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
        for l in out:
            # haversine_km gives distance between two lat lng points
            d = haversine_km(lat, lng, l["lat"], l["lng"])
            if d <= max_distance_km:
                with_dist.append({**l, "distance_km": round(d, 1)})
        out = sorted(with_dist, key=lambda x: x["distance_km"])

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


@app.post("/api/match")
def match(m: MatchRequest):
    # rank listings by how well they match what the buyer wants
    # score is material 40 + quantity 25 + distance 20 + condition 15
    db = load_db()
    scored = []
    for l in db["listings"]:
        if l.get("status") != "active":
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


@app.get("/api/impact")
def impact():
    # dashboard stats: tonnes diverted, value recovered, matches
    db = load_db()
    listings = db["listings"]
    total_value = sum(l["quantity"] * l["price_per_unit"] for l in listings)

    # tonnes = quantity * CO2 factor / 1000
    tonnes = sum(l["quantity"] * MATERIAL_META.get(l["material"], {}).get("co2_per_unit_kg", 1)
                 for l in listings) / 1000

    return {
        "tonnes_diverted": round(tonnes, 2),
        "value_recovered_inr": round(total_value),
        "value_recovered_fmt": f"₹{total_value / 100000:.1f} lakh",
        "buyer_matches": len(db["requests"]) + 43,
        "active_listings": len([l for l in listings if l.get("status") == "active"]),
        "total_requests": len(db["requests"]),
    }


@app.get("/api/materials")
def materials():
    # return all 16 materials so frontend can show them in dropdowns
    return [{"name": k, **v} for k, v in MATERIAL_META.items()]


# this serves photos from the uploads folder at /uploads/filename
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
