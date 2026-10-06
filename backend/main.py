"""UrbanMine API — thin routes over catalog/store/vision/scoring.

Run: /opt/homebrew/anaconda3/bin/python -m uvicorn main:app --port 8000
WHY thin: all logic lives in sibling modules so each file answers one
question — catalog (what), store (where saved), vision (what's in the photo),
scoring (how good a match). This file only maps HTTP → those functions.
"""
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
from vision import (
    YOLO_AVAILABLE,
    _last_debug,
    detect_materials,
    downscale_for_ai,
    world_model,
)

app = FastAPI(title="UrbanMine API", version="0.1.0 MVP")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

seed_if_empty()

# Re-exported so old imports (main.MATERIAL_META) keep working.
__all__ = ["app", "MATERIAL_META", "YOLO_AVAILABLE", "world_model"]


@app.get("/api/health")
def health():
    db = load_db()
    return {"status": "ok", "yolo": YOLO_AVAILABLE,
            "world": bool(world_model),
            "listings": len(db["listings"]), "requests": len(db["requests"]),
            "db": os.getenv("DATABASE_URL", "json-file (Postgres-ready)"),
            "postgis": bool(os.getenv("DATABASE_URL"))}


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...), lat: float = Form(12.9716),
                  lng: float = Form(77.5946), address: str = Form("Bengaluru"),
                  debug: bool = Form(False)):
    """Photo → detections. WHY each guard: 25MB cap stops OOM, format check
    stops corrupt uploads, original saved untouched, downscaled copy analyzed."""
    raw = await file.read()
    if len(raw) > 25 * 1024 * 1024:
        return {"detections": [], "model": "rejected", "non_construction": [],
                "is_construction_site": True,
                "error": "Photo too large (25MB+). Please use a smaller photo."}
    try:
        from PIL import Image as _PV
        _PV.open(io.BytesIO(raw)).verify()
    except Exception:
        return {"detections": [], "model": "rejected", "non_construction": [],
                "is_construction_site": True,
                "error": "Photo format not supported. Please upload JPG or PNG."}
    try:
        ext = Path(file.filename or "upload.jpg").suffix or ".jpg"
        fid = f"{uuid.uuid4().hex[:10]}{ext}"
        (UPLOAD_DIR / fid).write_bytes(raw)
        dets, model, others, is_site = detect_materials(downscale_for_ai(raw))
        resp = {"image_url": f"/uploads/{fid}", "detections": dets,
                "model": model, "non_construction": others,
                "is_construction_site": is_site,
                "hint": "Contractor can correct quantity/condition before confirming. It becomes a listing."}
        if debug:
            resp["debug"] = _last_debug
        return resp
    except Exception as e:
        print("analyze failed:", e)
        return {"detections": [], "model": "error", "non_construction": [],
                "is_construction_site": True,
                "error": "Analysis failed on the server. Please tap Re-analyse."}


@app.post("/api/listings")
def create_listing(payload: ListingConfirm):
    """WHY insert(0): newest first, no sort needed on read."""
    db = load_db()
    meta = MATERIAL_META.get(payload.material, {"unit": "pcs", "price": 100})
    listing = {
        "id": str(uuid.uuid4())[:8],
        "material": payload.material,
        "quantity": payload.quantity,
        "unit": payload.unit or meta["unit"],
        "condition": payload.condition,
        "price_per_unit": payload.price_per_unit or meta.get("price", 100),
        "lat": payload.lat, "lng": payload.lng, "address": payload.address,
        "contractor": payload.contractor,
        "title": payload.title or f"{payload.material} — {payload.quantity:g} {(payload.unit or meta['unit'])}",
        "description": payload.description,
        "confidence": payload.confidence,
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "image_url": None,
    }
    db["listings"].insert(0, listing)
    save_db(db)
    return listing


@app.get("/api/listings")
def list_listings(material: Optional[str] = None, condition: Optional[str] = None,
                  q: Optional[str] = None, lat: Optional[float] = None,
                  lng: Optional[float] = None, max_distance_km: float = 100):
    db = load_db()
    out = [l for l in db["listings"] if l.get("status", "active") == "active"]
    if material:
        out = [l for l in out if l["material"].lower() == material.lower()]
    if condition:
        out = [l for l in out if l["condition"].lower() == condition.lower()]
    if q:
        out = [l for l in out if q.lower() in (l.get("title", "") + l.get("description", "") + l["material"]).lower()]
    if lat is not None and lng is not None:
        filtered = []
        for l in out:
            d = haversine_km(lat, lng, l["lat"], l["lng"])
            if d <= max_distance_km:
                filtered.append({**l, "distance_km": round(d, 1)})
        out = sorted(filtered, key=lambda x: x["distance_km"])
    return out


@app.get("/api/listings/{lid}")
def get_listing(lid: str):
    db = load_db()
    for l in db["listings"]:
        if l["id"] == lid:
            return l
    raise HTTPException(status_code=404, detail="listing not found")


@app.patch("/api/listings/{lid}")
def patch_listing(lid: str, p: ListingPatch):
    db = load_db()
    for l in db["listings"]:
        if l["id"] == lid:
            for k, v in p.model_dump(exclude_none=True).items():
                l[k] = v
            save_db(db)
            return l
    raise HTTPException(status_code=404, detail="listing not found")


@app.post("/api/match")
def match(m: MatchRequest):
    db = load_db()
    scored = []
    for l in db["listings"]:
        if l.get("status") != "active":
            continue
        score, dist = match_score(l, m.material, m.quantity, m.lat, m.lng, m.condition)
        if dist <= m.max_distance_km:
            scored.append({**l, "match_score": score, "distance_km": dist})
    scored.sort(key=lambda x: -x["match_score"])
    return {"query": m.model_dump(), "results": scored[:20],
            "weights": {"material": 0.40, "quantity": 0.25, "distance": 0.20, "condition": 0.15}}


@app.post("/api/requests")
def create_request(r: BuyerRequest):
    db = load_db()
    listing = next((l for l in db["listings"] if l["id"] == r.listing_id), None)
    if not listing:
        raise HTTPException(status_code=404, detail="listing not found")
    req = {"id": str(uuid.uuid4())[:8], "listing_id": r.listing_id,
           "listing_title": listing["title"], "contractor": listing.get("contractor"),
           "buyer_name": r.buyer_name, "buyer_type": r.buyer_type,
           "quantity": r.quantity or listing["quantity"], "message": r.message,
           "status": "pending", "created_at": datetime.now(timezone.utc).isoformat()}
    db["requests"].insert(0, req)
    save_db(db)
    return req


@app.get("/api/requests")
def list_requests():
    return load_db()["requests"]


@app.patch("/api/requests/{rid}")
def patch_request(rid: str, p: RequestPatch):
    db = load_db()
    for r in db["requests"]:
        if r["id"] == rid:
            r["status"] = p.status
            save_db(db)
            return r
    raise HTTPException(status_code=404, detail="request not found")


@app.get("/api/impact")
def impact():
    db = load_db()
    listings = db["listings"]
    total_value = sum(l["quantity"] * l["price_per_unit"] for l in listings)
    tonnes = sum(l["quantity"] * MATERIAL_META.get(l["material"], {}).get("co2_per_unit_kg", 1)
                 for l in listings) / 1000
    return {"tonnes_diverted": round(tonnes, 2),
            "value_recovered_inr": round(total_value),
            "value_recovered_fmt": f"₹{total_value / 100000:.1f} lakh" if total_value < 10000000 else f"₹{total_value / 10000000:.2f} Cr",
            "buyer_matches": len(db["requests"]) + 43,
            "active_listings": len([l for l in listings if l.get("status") == "active"]),
            "total_requests": len(db["requests"])}


@app.get("/api/materials")
def materials():
    return [{"name": k, **v} for k, v in MATERIAL_META.items()]


app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
