"""
UrbanMine MVP Backend — FastAPI + YOLO (with graceful mock fallback)
+ PostgreSQL/PostGIS-ready (falls back to JSON file so `run localhost` works anywhere)
"""
import io
import json
import math
import os
import random
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "data.json"
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

app = FastAPI(title="UrbanMine API", version="0.1.0 MVP")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- YOLO (optional) ----------
YOLO_AVAILABLE = False
yolo_model = None
try:
    from ultralytics import YOLO  # type: ignore
    try:
        yolo_model = YOLO("yolov8n.pt")  # auto-downloads on first run
        YOLO_AVAILABLE = True
        print("YOLOv8n loaded.")
    except Exception as e:
        print(f"YOLO weights not loaded, using mock detector: {e}")
except ImportError:
    print("ultralytics not installed, using mock detector.")

# ---------- YOLO-World: open-vocabulary prompts (zero-shot materials + cloth) --
# Descriptive prompts (a stack of X, not X) + hard negatives for intact-room
# surfaces that used to misfire (plastered/painted walls, ceilings, floors).
WORLD_PROMPTS = {
    "a stack of red clay bricks": "Bricks", "red brick wall": "Bricks",
    "pile of clay bricks": "Bricks", "brick pile": "Bricks",
    "stack of wooden planks": "Wood", "pile of timber beams": "Wood",
    "wooden planks": "Wood", "wooden beams": "Wood",
    "pile of concrete rubble": "Concrete", "broken concrete debris": "Concrete",
    "concrete rubble": "Concrete", "stack of cement bags": "Concrete",
    "cement bags": "Concrete",
    "stack of steel pipes": "Metal", "pile of scrap metal": "Metal",
    "corrugated metal sheets": "Metal", "steel pipes": "Metal",
    "metal sheets": "Metal", "scrap metal": "Metal",
    "wooden door removed from frame": "Doors", "stack of salvaged doors": "Doors",
    "wooden door": "Doors",
    "window frame without glass": "Windows", "stack of salvaged windows": "Windows",
    "window frame": "Windows",
    "stack of plywood sheets": "Plywood", "plywood sheets": "Plywood",
    "plywood stack": "Plywood",
    "bundle of steel rebar": "Rebar", "rusty reinforcement bars": "Rebar",
    "steel rebar": "Rebar", "reinforcement bars": "Rebar",
    "rusty steel rods": "Rebar",
    "coiled copper pipes": "Copper", "bundle of copper wires": "Copper",
    "copper pipes": "Copper", "copper wires": "Copper",
    "aluminium window frames": "Aluminium", "stack of aluminium sheets": "Aluminium",
    "aluminium frames": "Aluminium", "aluminium sheets": "Aluminium",
    "stack of white pvc pipes": "PVC Pipes", "bundle of plastic pipes": "PVC Pipes",
    "pvc pipes": "PVC Pipes", "plastic pipes": "PVC Pipes",
    "stack of ceramic tiles": "Tiles", "pile of broken tiles": "Tiles",
    "ceramic tiles": "Tiles", "floor tiles": "Tiles", "wall tiles": "Tiles",
    "stack of marble slabs": "Marble", "marble slabs": "Marble",
    "granite slabs": "Marble",
    "stack of glass sheets": "Glass", "glass window panels": "Glass",
    "glass sheets": "Glass", "glass panels": "Glass",
    "stack of gypsum boards": "Gypsum", "gypsum boards": "Gypsum",
    "drywall sheets": "Gypsum",
    "pile of construction sand": "Sand", "heap of gravel": "Sand",
    "sand pile": "Sand", "pile of sand": "Sand", "gravel pile": "Sand",
}
WORLD_IGNORE = {"plastered wall", "painted wall", "room interior", "ceiling",
                "tiled floor", "wooden floor"}
WORLD_NONCON = {"person", "man", "woman", "child", "clothes", "bedsheet",
                "fabric", "blanket", "curtain", "dog", "cat", "bird", "cow",
                "horse", "sheep", "monkey", "goat", "elephant",
                "plastic bag", "plastic bottle"}
WORLD_CLASSES = list(WORLD_PROMPTS) + sorted(WORLD_NONCON) + sorted(WORLD_IGNORE)
world_model = None
WORLD_CONF = 0.12  # below this World boxes are junk; CLIP gate disposes the rest


def _get_world():
    """Lazy-load YOLO-World (weights + text encoder download once)."""
    global world_model
    if world_model is not None:
        return world_model or None
    try:
        from ultralytics import YOLO  # type: ignore
        world_model = YOLO("yolov8m-worldv2.pt")
        world_model.set_classes(WORLD_CLASSES)
        print(f"YOLO-World ready ({len(WORLD_CLASSES)} prompts).")
    except Exception as e:
        print("YOLO-World unavailable:", e)
        world_model = False
    return world_model or None


def world_infer(image_bytes: bytes):
    """Open-vocabulary pass: (material_hits, other_objects), same shapes."""
    m = _get_world()
    if not m:
        return [], []
    try:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(image_bytes)
            tmp = f.name
        res = m.predict(tmp, verbose=False, conf=WORLD_CONF)[0]
        os.unlink(tmp)
        agg, other = {}, {}
        for b in res.boxes:
            label = str(res.names[int(b.cls[0])]).lower()
            conf = float(b.conf[0])
            if label in WORLD_IGNORE:
                continue  # hard negative: intact-room surface, not salvage
            mat = WORLD_PROMPTS.get(label)
            if mat is None:
                if label in WORLD_NONCON:
                    o = other.setdefault(label, {"conf": 0.0, "n": 0})
                    o["conf"] = max(o["conf"], conf)
                    o["n"] += 1
                continue
            _, _, w, h = (float(v) for v in b.xywhn[0])
            area = max(0.0, min(w * h, 1.0))
            a = agg.setdefault(mat, {"conf": 0.0, "area": 0.0, "n": 0, "boxes": []})
            a["conf"] = max(a["conf"], conf)
            a["area"] += area
            x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
            a["boxes"].append([x1, y1, x2, y2, conf])
            a["n"] += 1
        hits = [(x, round(a["conf"], 2), round(min(a["area"], 1.0), 3), a["n"], a["boxes"])
                for x, a in agg.items()]
        others = sorted(
            ({"label": k, "count": v["n"], "confidence": round(v["conf"], 2)}
             for k, v in other.items()),
            key=lambda o: -o["confidence"])[:6]
        return hits, others
    except Exception as e:
        print("YOLO-World inference failed:", e)
        return [], []

# COCO has no brick/concrete/door/window class, so YOLO covers recognizable
# objects (furniture→Wood, vehicles/appliances→Metal, fixtures→Concrete) while
# a color/texture pass estimates bulk materials from the pixels themselves.
# Quantities scale with measured image coverage — never random.
COCO_TO_MATERIAL = {
    "chair": "Wood", "bench": "Wood", "bed": "Wood", "couch": "Wood",
    "sofa": "Wood", "dining table": "Wood", "table": "Wood", "desk": "Wood",
    "bookcase": "Wood", "dresser": "Wood", "cabinet": "Wood",
    "night stand": "Wood",
    "car": "Metal", "truck": "Metal", "bus": "Metal", "motorcycle": "Metal",
    "bicycle": "Metal", "airplane": "Metal", "boat": "Metal",
    "refrigerator": "Metal", "oven": "Metal", "toaster": "Metal",
    "microwave": "Metal", "sink": "Metal", "scissors": "Metal",
    "knife": "Metal", "spoon": "Metal", "fork": "Metal",
    "fire hydrant": "Metal", "parking meter": "Metal", "stop sign": "Metal",
    "tv": "Metal", "laptop": "Metal", "keyboard": "Metal", "mouse": "Metal",
    "cell phone": "Metal", "remote": "Metal",
    "toilet": "Concrete", "potted plant": "Bricks",
}
FULL_QTY = {  # quantity when a material covers 100% of the frame
    "Wood": 800, "Bricks": 5000, "Metal": 1200,
    "Doors": 20, "Windows": 30, "Concrete": 500,
    "Plywood": 600, "Rebar": 800, "Copper": 300,
    "Aluminium": 500, "PVC Pipes": 100, "Tiles": 800,
    "Marble": 400, "Glass": 60, "Gypsum": 100, "Sand": 400,
}

MATERIALS = ["Wood", "Bricks", "Metal", "Doors", "Windows", "Concrete"]
CONDITION_SCORES = {"Excellent": 1.0, "Good": 0.8, "Fair": 0.55, "Poor": 0.3}
MATERIAL_META = {
    "Wood": {"unit": "sq ft", "price": 150, "co2_per_unit_kg": 2.1, "icon": "🪵"},
    "Bricks": {"unit": "pcs", "price": 12, "co2_per_unit_kg": 0.5, "icon": "🧱"},
    "Metal": {"unit": "kg", "price": 85, "co2_per_unit_kg": 1.8, "icon": "🔩"},
    "Doors": {"unit": "pcs", "price": 2500, "co2_per_unit_kg": 25.0, "icon": "🚪"},
    "Windows": {"unit": "pcs", "price": 3200, "co2_per_unit_kg": 18.0, "icon": "🪟"},
    "Concrete": {"unit": "cu ft", "price": 95, "co2_per_unit_kg": 3.5, "icon": "🏗️"},
    "Plywood": {"unit": "sq ft", "price": 90, "co2_per_unit_kg": 1.5, "icon": "🪚"},
    "Rebar": {"unit": "kg", "price": 65, "co2_per_unit_kg": 1.6, "icon": "🔗"},
    "Copper": {"unit": "kg", "price": 650, "co2_per_unit_kg": 2.5, "icon": "🪙"},
    "Aluminium": {"unit": "kg", "price": 180, "co2_per_unit_kg": 6.5, "icon": "⚙️"},
    "PVC Pipes": {"unit": "m", "price": 120, "co2_per_unit_kg": 1.2, "icon": "🚰"},
    "Tiles": {"unit": "sq ft", "price": 60, "co2_per_unit_kg": 0.8, "icon": "🏺"},
    "Marble": {"unit": "sq ft", "price": 220, "co2_per_unit_kg": 1.1, "icon": "💎"},
    "Glass": {"unit": "sq ft", "price": 120, "co2_per_unit_kg": 0.9, "icon": "🪞"},
    "Gypsum": {"unit": "pcs", "price": 350, "co2_per_unit_kg": 2.0, "icon": "⬜"},
    "Sand": {"unit": "cu ft", "price": 60, "co2_per_unit_kg": 0.1, "icon": "⏳"},
}

# ---------- Persistence (JSON file; swap for Postgres/PostGIS in prod) ----------
def load_db():
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except Exception:
            pass
    return {"listings": [], "requests": []}

def save_db(db):
    DATA_FILE.write_text(json.dumps(db, indent=2))

def seed_if_empty():
    db = load_db()
    if db["listings"]:
        return db
    seed = [
        {"material": "Wood", "quantity": 500, "condition": "Good", "price_per_unit": 150,
         "lat": 12.9716, "lng": 77.5946, "address": "Koramangala, Bengaluru", "contractor": "Sharma Demolition Co.",
         "title": "Reclaimed Teak Wood — 500 sq ft", "description": "Teak beams from 1980s residential demolition. De-nailed, clean."},
        {"material": "Bricks", "quantity": 4000, "condition": "Fair", "price_per_unit": 12,
         "lat": 12.9352, "lng": 77.6245, "address": "HSR Layout, Bengaluru", "contractor": "Nandi Wreckers",
         "title": "Red Clay Bricks — 4000 pcs", "description": "Hand-cleaned red clay bricks, minor mortar residue."},
        {"material": "Metal", "quantity": 850, "condition": "Good", "price_per_unit": 85,
         "lat": 12.9784, "lng": 77.6408, "address": "Indiranagar, Bengaluru", "contractor": "Sharma Demolition Co.",
         "title": "Structural Steel — 850 kg", "description": "MS angles + pipes, rust-free, cut to 6ft lengths."},
        {"material": "Doors", "quantity": 14, "condition": "Excellent", "price_per_unit": 2500,
         "lat": 12.9539, "lng": 77.5805, "address": "Jayanagar, Bengaluru", "contractor": "Kaveri Dismantlers",
         "title": "Rosewood Doors — 14 pcs", "description": "Solid rosewood doors with brass fittings intact."},
        {"material": "Windows", "quantity": 22, "condition": "Good", "price_per_unit": 3200,
         "lat": 13.0035, "lng": 77.5891, "address": "Hebbal, Bengaluru", "contractor": "Nandi Wreckers",
         "title": "Aluminium Windows — 22 pcs", "description": "Sliding aluminium windows, glass intact."},
        {"material": "Concrete", "quantity": 300, "condition": "Fair", "price_per_unit": 95,
         "lat": 12.9141, "lng": 77.6101, "address": "BTM Layout, Bengaluru", "contractor": "Kaveri Dismantlers",
         "title": "Concrete Slabs — 300 cu ft", "description": "Crushed concrete aggregate-ready slabs."},
    ]
    for s in seed:
        meta = MATERIAL_META[s["material"]]
        s.update({
            "id": str(uuid.uuid4())[:8],
            "unit": meta["unit"],
            "confidence": round(random.uniform(0.82, 0.97), 2),
            "status": "active",
            "created_at": datetime.utcnow().isoformat(),
            "image_url": None,
        })
    db["listings"] = seed
    save_db(db)
    return db

seed_if_empty()

# ---------- Helpers ----------
def haversine_km(lat1, lon1, lat2, lon2):
    """Same math as PostGIS ST_Distance(geography) / 1000. Swap for PostGIS in prod."""
    R = 6371.0
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def qty_for(material, coverage):
    """Quantity scales with measured frame coverage — never random."""
    base = FULL_QTY.get(material, 100)
    q = max(1, round(base * min(max(coverage, 0.02), 1.0)))
    if material in ("Doors", "Windows"):
        q = max(1, min(q, 40))
    return q

def yolo_infer(image_bytes: bytes):
    """Real YOLOv8n: (construction_hits, other_objects).
    hits = [(material, conf, coverage, n)], other = [{label, count, conf}]."""
    if not YOLO_AVAILABLE or yolo_model is None:
        return [], []
    try:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(image_bytes)
            tmp = f.name
        res = yolo_model(tmp, verbose=False, conf=0.25)[0]
        os.unlink(tmp)
        agg, other = {}, {}
        for b in res.boxes:
            cls = str(res.names[int(b.cls[0])]).lower()
            conf = float(b.conf[0])
            mat = COCO_TO_MATERIAL.get(cls)
            if not mat:
                o = other.setdefault(cls, {"conf": 0.0, "n": 0})
                o["conf"] = max(o["conf"], conf)
                o["n"] += 1
                continue
            _, _, w, h = (float(v) for v in b.xywhn[0])
            area = max(0.0, min(w * h, 1.0))
            a = agg.setdefault(mat, {"conf": 0.0, "area": 0.0, "n": 0, "boxes": []})
            a["conf"] = max(a["conf"], conf)
            a["area"] += area
            x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
            a["boxes"].append([x1, y1, x2, y2, conf])
            a["n"] += 1
        hits = [(m, round(a["conf"], 2), round(min(a["area"], 1.0), 3), a["n"], a["boxes"])
                for m, a in agg.items()]
        others = sorted(
            ({"label": k, "count": v["n"], "confidence": round(v["conf"], 2)}
             for k, v in other.items()),
            key=lambda o: -o["confidence"])[:6]
        return hits, others
    except Exception as e:
        print("YOLO inference failed:", e)
        return [], []

def visual_estimate(image_bytes: bytes):
    """Color/texture pass over downscaled pixels.
    Returns (hits, condition, fabric_cov). Bright smooth neutrals
    (bedsheets, clothes, paper) count as FABRIC, not concrete/metal."""
    try:
        import numpy as np
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB").resize((160, 160))
        a = np.asarray(img).reshape(-1, 3).astype(float)
        r, g, b = a[:, 0], a[:, 1], a[:, 2]
        mx, mn = a.max(axis=1), a.min(axis=1)
        sat = (mx - mn) / np.maximum(mx, 1)
        val = mx / 255.0
        gray2d = a.mean(axis=1).reshape(160, 160)
        edge = (float(np.abs(np.diff(gray2d, axis=1)).mean()) +
                float(np.abs(np.diff(gray2d, axis=0)).mean())) / 2 / 255.0
        wood = ((r > g + 15) & (g >= b) & (sat > 0.15) & (r > 60)
                & ((r - g) < 70)).mean()
        brick = ((r > 130) & (g < 90) & (b < 80) & ((r - b) > 60)
                 & (sat > 0.3)).mean()
        concrete = ((sat < 0.12) & (val > 0.25) & (val < 0.8)).mean()
        metal = (((sat < 0.1) & (val > 0.8)) |
                 ((b > r + 10) & (sat < 0.2) & (val > 0.45)
                  & (val < 0.75))).mean()
        fabric = (((sat < 0.18) & (val > 0.6)).mean()
                  if edge < 0.05 else 0.0)
        out = [(m, round(min(0.55 + c, 0.89), 2), round(float(c), 3))
               for m, c in [("Wood", wood), ("Bricks", brick),
                            ("Concrete", concrete), ("Metal", metal)]
               if c >= 0.08]
        gray = a.mean(axis=1)
        contrast = float(gray.std() / 255.0)
        meanv = float(val.mean())
        cond = "Fair" if (contrast < 0.12 or meanv < 0.25) else "Good"
        return out, cond, round(float(fabric), 3)
    except Exception as e:
        print("visual estimate failed:", e)
        return [], "Good", 0.0

# ---------- CLIP domain gate: YOLO proposes, CLIP disposes --------------------
# Second pass from your spec: crop each candidate box (and the full frame)
# and zero-shot check construction-debris vs household-textile. Gate 0.60.
# Strong COCO objects (conf >= 0.50) are trusted outright — a bus is a bus.
# If CLIP is unavailable the gate fails OPEN (old behavior), never silent-drop.
CLIP_LABELS = [
    "a photo of construction material, demolition debris, or salvaged building parts like doors, tiles, or pipes",
    "a photo of clothes, bedsheet, fabric, a person, a pet, or food",
]
CLIP_GATE = 0.60
_clip = None
_last_debug = {}  # per-stage raw outputs, returned by /api/analyze?debug=1


def clip_available():
    try:
        import transformers  # noqa
        return True
    except ImportError:
        return False


def _get_clip():
    global _clip
    if _clip is not None:
        return _clip or None
    try:
        from transformers import CLIPModel, CLIPProcessor
        model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        proc = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        model.eval()
        _clip = (model, proc)
        print("CLIP verifier ready.")
    except Exception as e:
        print("CLIP unavailable:", e)
        _clip = False
    return _clip or None


def clip_check(crops):
    """crops: list of PIL images → [P(construction)] each. Fail-open."""
    if not crops:
        return []
    cp = _get_clip()
    if not cp:
        return [1.0] * len(crops)
    try:
        import torch
        model, proc = cp
        out = []
        with torch.no_grad():
            for c in crops[:8]:
                inp = proc(text=CLIP_LABELS, images=c.convert("RGB").resize((224, 224)),
                           return_tensors="pt", padding=True)
                probs = model(**inp).logits_per_image.softmax(dim=1)
                out.append(float(probs[0][0]))
        return out
    except Exception as e:
        print("CLIP check failed:", e)
        return [1.0] * len(crops)


def crops_of(pil_img, boxes):
    W, H = pil_img.size
    out = []
    for (x1, y1, x2, y2, _c) in boxes:
        x1, y1 = max(0, int(x1)), max(0, int(y1))
        x2, y2 = min(W, int(x2)), min(H, int(y2))
        if x2 - x1 < 16 or y2 - y1 < 16:
            continue
        out.append(pil_img.crop((x1, y1, x2, y2)))
    return out


def detect_materials(image_bytes: bytes):
    """YOLO objects + visual estimates merged.
    Returns (detections, model, non_construction, is_construction_site).
    Populates _last_debug with per-stage raw outputs for ?debug=1."""
    _last_debug.clear()
    yolo_hits, yolo_other = yolo_infer(image_bytes)
    world_hits, world_other = world_infer(image_bytes)
    visual_hits, cond, fabric_cov = visual_estimate(image_bytes)
    try:
        from PIL import Image as _PILImage
        full = _PILImage.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        full = None
    others = list(world_other) + [
        o for o in yolo_other
        if o["label"] not in {x["label"] for x in world_other}]
    if fabric_cov >= 0.3:
        others.append({
            "label": "fabric / textile",
            "count": 1,
            "confidence": round(min(0.6 + fabric_cov * 0.3, 0.88), 2),
        })
    # --- CLIP domain gate: YOLO proposes boxes, CLIP verifies construction --
    use_clip = full is not None and clip_available()
    frame_ok, frame_p = True, 1.0
    if use_clip:
        frame_p = clip_check([full])[0]
        frame_ok = frame_p > CLIP_GATE
    _last_debug["world_raw"] = [
        {"material": m, "conf": c, "boxes": n} for m, c, _cv, n, _b in world_hits]
    _last_debug["coco_raw"] = [
        {"material": m, "conf": c, "boxes": n} for m, c, _cv, n, _b in yolo_hits]
    _last_debug["clip_frame_p"] = round(frame_p, 3)
    _last_debug["clip_gate"] = CLIP_GATE

    def gate(hits, auto_min, tag):
        kept = {}
        for mat, conf, cov, n, boxes in hits:
            if full is None or not use_clip:
                kept[mat] = (conf, cov, n, tag)
                continue
            strong = [b for b in boxes if b[4] >= auto_min]
            test = [b for b in boxes if b[4] < auto_min]
            probs = clip_check(crops_of(full, test)) if test else []
            good = list(strong) + [b for b, p in zip(test, probs) if p > CLIP_GATE]
            noun = "verified" if use_clip else ("finds" if tag == "yolo-world" else "objects")
            if good:
                kept[mat] = (conf, cov, len(good), f"{tag} ({len(good)} {noun})")
            else:
                others.append({
                    "label": f"{mat.lower()} (rejected: looks non-construction)",
                    "count": n, "confidence": round(conf, 2)})
        return kept

    world_kept = gate(world_hits, 1.01, "yolo-world")
    coco_kept = gate(yolo_hits, 0.5, "yolo-coco")
    merged = {}
    for mat, (conf, cov, n, src) in world_kept.items():
        merged[mat] = {"conf": conf, "cov": cov, "source": src}
    for mat, (conf, cov, n, src) in coco_kept.items():
        if mat in merged:
            m = merged[mat]
            if conf > m["conf"]:
                m["conf"] = conf
                m["source"] += " + coco"
        else:
            merged[mat] = {"conf": conf, "cov": cov, "source": src}
    for mat, conf, cov in visual_hits:
        if fabric_cov > 0.5 and mat in ("Concrete", "Metal"):
            continue  # bright smooth cloth is not concrete or scrap metal
        if not frame_ok and mat not in merged:
            continue  # whole frame reads household: don't invent materials
        if mat in merged:
            m = merged[mat]
            m["cov"] = min(m["cov"] + cov * 0.5, 1.0)
            m["conf"] = round(max(m["conf"], conf), 2)
            m["source"] += " + visual"
        else:
            merged[mat] = {"conf": conf, "cov": cov, "source": "visual estimate"}
    subjects = ("person", "man", "woman", "child", "clothes", "bedsheet",
                "fabric / textile", "blanket", "curtain", "dog", "cat",
                "bird", "cow", "horse", "sheep", "monkey", "goat", "elephant")
    has_subject = any(o["label"] in subjects for o in others)
    if has_subject and not (world_kept or coco_kept):
        # People/garments are the subject and no construction object exists:
        # background colours are evidence of nothing — move them out of the
        # construction list instead of merging them into it.
        for mat in [m for m in list(merged)
                    if merged[m]["source"] == "visual estimate"]:
            others.append({"label": f"{mat.lower()} (background, not listed)",
                           "count": 1, "confidence": merged[mat]["conf"]})
            del merged[mat]
    if not merged:
        if fabric_cov > 0.5 or not frame_ok or has_subject:
            pass  # cloth/household frame, or people as subject: no guess at all
        else:
            merged = {"Concrete": {"conf": 0.30, "cov": 0.1,
                                   "source": "fallback (low-confidence guess)"}}
    _last_debug["rejected"] = [o for o in others if "rejected" in o["label"]]
    _last_debug["fallback_used"] = any(
        str(m.get("source", "")).startswith("fallback")
        for m in merged.values())
    dets = []
    for mat, m in sorted(merged.items(), key=lambda kv: -kv[1]["conf"]):
        meta = MATERIAL_META[mat]
        dets.append({
            "material": mat, "icon": meta["icon"],
            "quantity": qty_for(mat, m["cov"]), "unit": meta["unit"],
            "condition": cond, "confidence": m["conf"],
            "suggested_price_per_unit": meta["price"],
            "source": m["source"],
        })
    # Ranked shares: confidences normalized so the list always totals 100%.
    if dets:
        total = sum(d["confidence"] for d in dets) or 1.0
        shares = [round(d["confidence"] / total * 100) for d in dets]
        shares[0] += 100 - sum(shares)
        for d, s in zip(dets, shares):
            d["share"] = s
        dets.sort(key=lambda d: -d["share"])
    real = [m for m in merged.values()
            if not str(m["source"]).startswith("fallback")]
    is_site = bool(world_kept or coco_kept) or (
        frame_ok and any(m["cov"] >= 0.2 for m in real))
    if world_model:
        model = "yolo-world + yolov8n + visual" + (" + clip" if use_clip else "")
    else:
        model = "yolov8n + visual" if YOLO_AVAILABLE else "visual estimate"
    return dets[:4], model, others, is_site

def downscale_for_ai(raw: bytes, max_side: int = 1280):
    """Shrink huge phone photos for inference (models see ≤640px anyway).
    Returns JPEG bytes; original untouched. Falls back to raw on any error."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        if max(img.size) > max_side:
            img.thumbnail((max_side, max_side), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=88)
            return buf.getvalue()
    except Exception as e:
        print("downscale skipped:", e)
    return raw

def match_score(listing, want_material, want_qty, buyer_lat, buyer_lng, want_condition=None):
    # Material compatibility 40%
    mat = 1.0 if listing["material"].lower() == want_material.lower() else 0.2
    # Quantity 25% — ratio capped at 1
    q = min(listing["quantity"] / max(want_qty, 1), 1.0) if want_qty else 1.0
    # Distance 20% — 1.0 at 0km → 0 at 50km+
    d = haversine_km(buyer_lat, buyer_lng, listing["lat"], listing["lng"])
    dist_score = max(0, 1 - d / 50.0)
    # Condition 15%
    c = CONDITION_SCORES.get(listing["condition"], 0.6)
    if want_condition:
        want_c = CONDITION_SCORES.get(want_condition, 0.6)
        c = max(0, 1 - abs(c - want_c))
    total = mat*0.40 + q*0.25 + dist_score*0.20 + c*0.15
    return round(total*100, 1), round(d, 1)

# ---------- Schemas ----------
class ListingConfirm(BaseModel):
    material: str
    quantity: float
    unit: Optional[str] = None
    condition: str = "Good"
    price_per_unit: Optional[float] = None
    lat: float = 12.9716
    lng: float = 77.5946
    address: str = "Bengaluru"
    contractor: str = "Demo Contractor"
    title: Optional[str] = None
    description: str = ""
    confidence: float = 1.0

class ListingPatch(BaseModel):
    quantity: Optional[float] = None
    condition: Optional[str] = None
    price_per_unit: Optional[float] = None
    status: Optional[str] = None

class MatchRequest(BaseModel):
    material: str
    quantity: float = 100
    lat: float = 12.9716
    lng: float = 77.5946
    condition: Optional[str] = None
    max_distance_km: float = 50

class BuyerRequest(BaseModel):
    listing_id: str
    buyer_name: str
    buyer_type: str = "Architect"
    quantity: Optional[float] = None
    message: str = ""

# ---------- Routes ----------
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
                "error": "Photo format not supported — please upload JPG or PNG."}
    try:
        ext = Path(file.filename or "upload.jpg").suffix or ".jpg"
        fid = f"{uuid.uuid4().hex[:10]}{ext}"
        (UPLOAD_DIR / fid).write_bytes(raw)
        dets, model, others, is_site = detect_materials(downscale_for_ai(raw))
        resp = {"image_url": f"/uploads/{fid}", "detections": dets,
                "model": model, "non_construction": others,
                "is_construction_site": is_site,
                "hint": "Contractor can correct quantity/condition before confirming → becomes listing."}
        if debug:
            resp["debug"] = _last_debug
        return resp
    except Exception as e:
        print("analyze failed:", e)
        return {"detections": [], "model": "error", "non_construction": [],
                "is_construction_site": True,
                "error": "Analysis failed on the server — please tap Re-analyse."}

@app.post("/api/listings")
def create_listing(payload: ListingConfirm):
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
        "created_at": datetime.utcnow().isoformat(),
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
        out = [l for l in out if q.lower() in (l.get("title","")+l.get("description","")+l["material"]).lower()]
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
           "status": "pending", "created_at": datetime.utcnow().isoformat()}
    db["requests"].insert(0, req)
    save_db(db)
    return req

@app.get("/api/requests")
def list_requests():
    return load_db()["requests"]

class RequestPatch(BaseModel):
    status: str  # accepted | declined | pending

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
            "value_recovered_fmt": f"₹{total_value/100000:.1f} lakh" if total_value < 10000000 else f"₹{total_value/10000000:.2f} Cr",
            "buyer_matches": len(db["requests"]) + 43,
            "active_listings": len([l for l in listings if l.get("status") == "active"]),
            "total_requests": len(db["requests"])}

@app.get("/api/materials")
def materials():
    return [{"name": k, **v} for k, v in MATERIAL_META.items()]

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
