"""Photo bytes in, materials out.

Order of passes (see detect_materials at the bottom):
  1. yolo_infer — standard yolov8n, everyday objects mapped to Wood/Metal.
  2. world_infer — yolov8m-worldv2 with descriptive prompts, all 16 materials.
  3. visual_estimate — plain pixel colors, no neural net (brown is Wood,
     red is Bricks, and so on).
  4. CLIP gate — each weak box checked: construction or household?

Four passes because no labeled demolition dataset exists. Zero-shot prompts
beat training on day one, the color pass catches bulk piles boxes miss, and
CLIP kills bedsheet-type false positives. Debug a photo with
POST /api/analyze?debug=1 plus debug=true.
"""
import io
import os

from catalog import (
    CLIP_GATE,
    CLIP_LABELS,
    COCO_TO_MATERIAL,
    MATERIAL_META,
    WORLD_CLASSES,
    WORLD_CONF,
    WORLD_IGNORE,
    WORLD_NONCON,
    WORLD_PROMPTS,
)
from scoring import qty_for

# ---------- YOLOv8n (closed-set) ----------
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

# ---------- YOLO-World (open-vocabulary, lazy) ----------
world_model = None


def _get_world():
    """Lazy-load so `import main` stays fast; weights download once."""
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


def _aggregate(boxes, names, label_to_mat):
    """One box loop shared by yolo_infer and world_infer.

    boxes: ultralytics boxes, names: index to label, label_to_mat: maps a
    label to a material or None. Returns (hits, others); a hit is
    (material, confidence, coverage, box count, boxes).
    """
    agg, other = {}, {}
    for b in boxes:
        label = str(names[int(b.cls[0])]).lower()
        conf = float(b.conf[0])
        if label in WORLD_IGNORE:
            continue  # hard negative: intact-room surface, not salvage
        mat = label_to_mat(label)
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


def world_infer(image_bytes: bytes):
    """Open-vocabulary pass: (material_hits, other_objects)."""
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
        return _aggregate(res.boxes, res.names, WORLD_PROMPTS.get)
    except Exception as e:
        print("YOLO-World inference failed:", e)
        return [], []


def yolo_infer(image_bytes: bytes):
    """Real YOLOv8n: (construction_hits, other_objects)."""
    if not YOLO_AVAILABLE or yolo_model is None:
        return [], []
    try:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(image_bytes)
            tmp = f.name
        res = yolo_model(tmp, verbose=False, conf=0.25)[0]
        os.unlink(tmp)
        return _aggregate(res.boxes, res.names, COCO_TO_MATERIAL.get)
    except Exception as e:
        print("YOLO inference failed:", e)
        return [], []


def visual_estimate(image_bytes: bytes):
    """Color pass over a 160px thumbnail. Catches bulk piles (a sand heap,
    a brick mass) that boxes miss.

    Bright smooth neutrals read as fabric, not concrete: that is what keeps
    bedsheets and clothes out of the listings. Returns
    (hits, condition, fabric coverage).
    """
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


# CLIP is the second opinion. Each candidate box (and the full frame) is
# scored construction vs household. Strong boxes (COCO at 0.50+) skip the
# check. A bus is a bus. If CLIP is missing, everything passes instead of
# silently vanishing.
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
    """Merges all four passes into the final answer.

    Returns (detections, model name, non_construction, is_construction_site).
    Fills _last_debug for ?debug=1. Rules, each earned by a past misfire:
    strong COCO boxes skip CLIP; weak World boxes are checked per crop;
    fabric-heavy frames drop Concrete/Metal; people as subject plus no
    objects means background colors count for nothing; a construction-looking
    frame with zero hits gets one labeled Concrete guess.
    """
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
    """Shrinks phone photos before inference. Models see 640px at most, so
    anything bigger only costs time. The saved original is untouched."""
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
