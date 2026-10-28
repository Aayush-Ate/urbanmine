# Photo bytes in, material detections out.
# This file runs AI on the photo in three passes, then merges everything.
#
# Pass 1: YOLOv8n finds everyday objects (chair -> Wood, bus -> Metal)
# Pass 2: YOLO-World finds materials with descriptive prompts (bricks -> Bricks)
# Pass 3: Visual color looks at pixel colors on a small thumbnail
# Then CLIP checks the whole frame and any weak boxes before we trust them.

import io
import os

from PIL import Image

from catalog import (
    CLIP_GATE, CLIP_LABELS, COCO_TO_MATERIAL, MATERIAL_META,
    WORLD_CLASSES, WORLD_CONF, WORLD_IGNORE, WORLD_NONCON, WORLD_PROMPTS,
)
from scoring import qty_for

# these are the AI models
# they start as None and load only when needed
# first photo is slow because models download and load, after that it is fast
YOLO_AVAILABLE = False
yolo_model = None
world_model = None
clip_model = None
clip_proc = None

# filled by detect_materials, returned by /api/analyze?debug=1
_last_debug = {}


def _load_yolo():
    # loads YOLOv8n model
    # this is the small model that finds everyday objects
    global YOLO_AVAILABLE, yolo_model
    try:
        from ultralytics import YOLO
        path = os.getenv("YOLO_MODEL_PATH") or "yolov8n.pt"
        yolo_model = YOLO(path)
        YOLO_AVAILABLE = True
    except Exception as e:
        print("YOLOv8n not loaded:", e)
        yolo_model = False


def _load_world():
    # loads YOLO-World model
    # this is the bigger model that uses text prompts to find materials
    global world_model
    try:
        from ultralytics import YOLO
        path = os.getenv("WORLD_MODEL_PATH") or "yolov8m-worldv2.pt"
        world_model = YOLO(path)
        world_model.set_classes(WORLD_CLASSES)
    except Exception as e:
        print("YOLO-World not loaded:", e)
        world_model = False


def _load_clip():
    # loads CLIP model
    # CLIP looks at an image and tells us if it is construction or household
    # it prevents bedsheets and people from becoming listings
    global clip_model, clip_proc
    try:
        from transformers import CLIPModel, CLIPProcessor
        clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        clip_proc = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        clip_model.eval()
    except Exception as e:
        print("CLIP not loaded:", e)
        clip_model = False


def _run_infer(model, image, conf, label_to_mat, ignore_set, noncon_set):
    # shared helper for yolo_infer and world_infer
    #
    # IN:
    #   model        - loaded ultralytics model (or False if unavailable)
    #   image        - PIL Image (RGB)
    #   conf         - confidence threshold (float)
    #   label_to_mat - function mapping a label to a material, or None
    #   ignore_set   - labels to skip entirely (intact room surfaces)
    #   noncon_set   - labels that are household, not construction
    #
    # OUT:
    #   hits   - list of (material, confidence, area_fraction, box)
    #   others - list of {"label": str, "confidence": float} household items
    #
    # WHY:
    #   yolo and world both produce boxes with labels and confidences.
    #   One helper avoids writing the same box-loop twice.
    if model is None or model is False:
        return [], []
    try:
        res = model(image, verbose=False, conf=conf)[0]
    except Exception as e:
        print("inference failed:", e)
        return [], []

    hits = []
    others = {}
    names = res.names

    for b in res.boxes:
        label = str(names[int(b.cls[0])]).lower()
        c = float(b.conf[0])

        if label in ignore_set:
            continue

        mat = label_to_mat(label)
        if mat is None:
            if label in noncon_set:
                others[label] = max(others.get(label, 0), c)
            continue

        x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
        _, _, w, h = (float(v) for v in b.xywhn[0])
        area = max(0.0, min(w * h, 1.0))
        hits.append((mat, c, area, (x1, y1, x2, y2)))

    others_list = [{"label": k, "confidence": round(v, 2)} for k, v in others.items()]
    return hits, others_list


def yolo_infer(image):
    # Pass 1: find everyday objects and map them to salvage materials
    #
    # IN:  PIL Image (RGB)
    # OUT: (hits, others)
    # WHY: chair, bed, couch -> Wood; car, bus, truck -> Metal
    if yolo_model is None:
        _load_yolo()
    return _run_infer(yolo_model, image, 0.25, COCO_TO_MATERIAL.get, set(), WORLD_NONCON)


def world_infer(image):
    # Pass 2: descriptive-prompt detection for all 16 materials
    #
    # IN:  PIL Image (RGB)
    # OUT: (hits, others)
    # WHY: text prompts like "a stack of red clay bricks" find salvage materials
    if world_model is None:
        _load_world()
    return _run_infer(world_model, image, WORLD_CONF, WORLD_PROMPTS.get, WORLD_IGNORE, WORLD_NONCON)


def visual_estimate(image):
    # Pass 3: look at pixel colors on a 160px thumbnail
    #
    # IN:  PIL Image (RGB)
    # OUT: (hits, condition, fabric_coverage)
    # WHY: no neural net, just checks if colors look like wood, bricks, concrete, metal
    try:
        import numpy as np

        # PIL is Python Imaging Library
        # resize((160, 160)) makes it small so color check is fast
        img = image.convert("RGB").resize((160, 160))
        a = np.asarray(img).reshape(-1, 3).astype(float)

        r, g, b = a[:, 0], a[:, 1], a[:, 2]
        mx, mn = a.max(axis=1), a.min(axis=1)
        sat = (mx - mn) / np.maximum(mx, 1)
        val = mx / 255.0

        gray2d = a.mean(axis=1).reshape(160, 160)
        edge = (float(np.abs(np.diff(gray2d, axis=1)).mean()) +
                float(np.abs(np.diff(gray2d, axis=0)).mean())) / 2 / 255.0

        # these check if colors match wood, bricks, concrete, metal
        wood = ((r > g + 15) & (g >= b) & (sat > 0.15) & (r > 60)
                & ((r - g) < 70)).mean()
        brick = ((r > 130) & (g < 90) & (b < 80) & ((r - b) > 60)
                 & (sat > 0.3)).mean()
        concrete = ((sat < 0.12) & (val > 0.25) & (val < 0.8)).mean()
        metal = (((sat < 0.1) & (val > 0.8)) |
                 ((b > r + 10) & (sat < 0.2) & (val > 0.45) & (val < 0.75))).mean()

        # fabric check: bright smooth cloth means bedsheet or clothes
        # edge < 0.05 means the image is smooth, not detailed
        fabric = ((sat < 0.18) & (val > 0.6)).mean() if edge < 0.05 else 0.0

        out = []
        for m, c in [("Wood", wood), ("Bricks", brick),
                     ("Concrete", concrete), ("Metal", metal)]:
            if c >= 0.08:
                out.append((m, round(min(0.55 + c, 0.89), 2), round(float(c), 3)))

        gray = a.mean(axis=1)
        contrast = float(gray.std() / 255.0)
        meanv = float(val.mean())

        # low contrast or dark means the material looks worn (Fair)
        # otherwise it looks Good
        cond = "Fair" if (contrast < 0.12 or meanv < 0.25) else "Good"
        return out, cond, round(float(fabric), 3)
    except Exception as e:
        print("Visual estimate failed:", e)
        return [], "Good", 0.0


def clip_check(crops):
    # CLIP gate: score each crop as probability it looks like construction material
    #
    # IN:  list of PIL Image crops
    # OUT: list of probabilities (0 to 1), one per crop
    # WHY: if CLIP is missing, returns 1.0 for everything (fail open)
    if not crops:
        return []
    if clip_model is None:
        _load_clip()
    if clip_model is None or clip_model is False:
        return [1.0] * len(crops)
    try:
        import torch
        out = []
        with torch.no_grad():
            for c in crops:
                inp = clip_proc(text=CLIP_LABELS, images=c.convert("RGB").resize((224, 224)),
                                return_tensors="pt", padding=True)
                probs = clip_model(**inp).logits_per_image.softmax(dim=1)
                out.append(float(probs[0][0]))
        return out
    except Exception as e:
        print("CLIP check failed:", e)
        return [1.0] * len(crops)


def crops_of(pil_img, boxes):
    # cut out box regions from the image so CLIP can inspect each one
    #
    # IN:  PIL Image, list of (x1, y1, x2, y2, confidence) boxes
    # OUT: list of PIL Image crops, one per box
    # WHY: CLIP needs to look at each detected box individually, not the whole photo
    W, H = pil_img.size
    out = []
    for (x1, y1, x2, y2, _c) in boxes:
        x1, y1 = max(0, int(x1)), max(0, int(y1))
        x2, y2 = min(W, int(x2)), min(H, int(y2))
        if x2 - x1 < 2 or y2 - y1 < 2:
            continue
        out.append(pil_img.crop((x1, y1, x2, y2)))
    return out


def clip_filter_hits(image, hits):
    # per-box CLIP check: weak boxes must look like construction
    #
    # IN:  PIL Image, list of (material, confidence, area, box) hits
    # OUT: (kept_hits, rejected) where rejected is a list for ?debug=1
    # WHY: YOLO-World can label a bedsheet as Concrete at low confidence.
    #      Strong boxes (0.50 and up) skip CLIP. Weak boxes get cropped and checked.
    strong = [h for h in hits if h[1] >= 0.50]
    weak = [h for h in hits if h[1] < 0.50]

    # only check the first 8 weak boxes so a busy photo stays fast
    check = []
    boxes = []
    for h in weak[:8]:
        x1, y1, x2, y2 = h[3]
        if x2 - x1 < 2 or y2 - y1 < 2:
            continue
        check.append(h)
        boxes.append((x1, y1, x2, y2, h[1]))

    if not check:
        return strong + weak, []

    crops = crops_of(image, boxes)
    probs = clip_check(crops)
    if len(probs) < len(check):
        probs += [1.0] * (len(check) - len(probs))

    kept = []
    rejected = []
    for h, p in zip(check, probs):
        if p >= CLIP_GATE:
            kept.append(h)
        else:
            rejected.append({
                "material": h[0],
                "confidence": round(h[1], 2),
                "clip_p": round(p, 3),
            })

    # weak boxes after the first 8 are kept, not silently dropped
    rest = weak[8:]
    return strong + kept + rest, rejected


def merge_hits(world_hits, yolo_hits):
    # combine detections from both passes into one dict
    #
    # IN:
    #   world_hits - list of (mat, conf, area, box) from YOLO-World
    #   yolo_hits  - list of (mat, conf, area, box) from YOLOv8n
    #
    # OUT: dict {material: {"conf": float, "cov": float, "source": str}}
    # WHY: if both models find bricks, keep the higher confidence and note both sources
    merged = {}
    for mat, conf, area, _box in world_hits:
        merged[mat] = {"conf": conf, "cov": area, "source": "yolo-world"}
    for mat, conf, area, _box in yolo_hits:
        if mat in merged:
            merged[mat]["conf"] = max(merged[mat]["conf"], conf)
            merged[mat]["cov"] = max(merged[mat]["cov"], area)
            merged[mat]["source"] += " + yolov8n"
        else:
            merged[mat] = {"conf": conf, "cov": area, "source": "yolov8n"}
    return merged


def add_visual_hits(merged, visual_hits, frame_ok, fabric_cov):
    # add color-based detections to the merged dict
    #
    # IN:
    #   merged      - dict from merge_hits
    #   visual_hits - list of (mat, conf, cov) from visual_estimate
    #   frame_ok    - bool, does the whole photo look like construction?
    #   fabric_cov  - float, how much of the photo is bright smooth cloth
    #
    # OUT: updated merged dict
    # WHY: colors can catch bulk piles that boxes miss, but not on cloth-dominant photos
    for mat, conf, cov in visual_hits:
        if fabric_cov > 0.5 and mat in ("Concrete", "Metal"):
            continue
        if not frame_ok and mat not in merged:
            continue
        if mat in merged:
            merged[mat]["cov"] = min(merged[mat]["cov"] + cov * 0.5, 1.0)
            merged[mat]["conf"] = round(max(merged[mat]["conf"], conf), 2)
            merged[mat]["source"] += " + visual"
        else:
            merged[mat] = {"conf": conf, "cov": cov, "source": "visual estimate"}
    return merged


def collect_others(world_others, yolo_others, fabric_cov):
    # build the non-construction list shown under the detections
    #
    # IN:  others from both model passes, fabric coverage
    # OUT: one list, no duplicate labels
    # WHY: the UI shows what was excluded, so a bedsheet or a person is visible
    #      instead of quietly turning into a Concrete listing.
    others = list(world_others)
    seen = {o["label"] for o in others}
    for o in yolo_others:
        if o["label"] not in seen:
            others.append(o)
            seen.add(o["label"])
    if fabric_cov >= 0.3:
        others.append({
            "label": "fabric / textile",
            "count": 1,
            "confidence": round(min(0.6 + fabric_cov * 0.3, 0.88), 2),
        })
    return others


def drop_household_hits(merged, others):
    # remove detections that come from household photos
    #
    # IN:
    #   merged - dict from add_visual_hits
    #   others - list of non-construction items
    #
    # OUT: (merged, others, has_subject) with household visual hits moved to others
    # WHY: a bedsheet photo should not produce a Concrete listing.
    #      if people or fabric dominate, drop visual-only hits.
    subjects = ("person", "man", "woman", "child", "clothes", "bedsheet",
                "fabric", "fabric / textile", "blanket", "curtain", "dog", "cat",
                "bird", "cow", "horse", "sheep", "monkey", "goat", "elephant")
    has_subject = any(o["label"] in subjects for o in others)

    if has_subject:
        for mat in list(merged):
            if merged[mat]["source"] == "visual estimate":
                others.append({
                    "label": f"{mat.lower()} (background, not listed)",
                    "count": 1,
                    "confidence": merged[mat]["conf"],
                })
                del merged[mat]

    return merged, others, has_subject


def fallback_guess(merged, frame_ok, fabric_cov, has_subject):
    # if nothing found but frame looks like construction, guess Concrete
    #
    # IN:
    #   merged      - dict from drop_household_hits
    #   frame_ok    - bool
    #   fabric_cov  - float
    #   has_subject - bool, are there people/fabric in the photo?
    #
    # OUT: merged dict (possibly with a fallback Concrete entry)
    # WHY: construction-looking empty frames get a labeled low-confidence guess.
    #      cloth or household frames get no guess at all.
    if not merged:
        if fabric_cov > 0.5 or not frame_ok or has_subject:
            pass
        else:
            merged = {"Concrete": {"conf": 0.30, "cov": 0.1,
                                   "source": "fallback (low-confidence guess)"}}
    return merged


def build_detections(merged, condition):
    # format merged dict into UI detection objects
    #
    # IN:
    #   merged    - dict from fallback_guess
    #   condition - string from visual_estimate ("Good" or "Fair")
    #
    # OUT: list of detection dicts with material, icon, quantity, unit, etc.
    # WHY: turn internal data into the shape the frontend expects
    dets = []
    for mat, m in sorted(merged.items(), key=lambda kv: -kv[1]["conf"]):
        meta = MATERIAL_META[mat]
        dets.append({
            "material": mat,
            "icon": meta["icon"],
            "quantity": qty_for(mat, m["cov"]),
            "unit": meta["unit"],
            "condition": condition,
            "confidence": m["conf"],
            "suggested_price_per_unit": meta["price"],
            "source": m["source"],
        })
    return dets


def normalize_shares(dets):
    # make confidence shares always total 100%
    #
    # IN:  list of detection dicts
    # OUT: same list with "share" field added to each, sorted by share descending
    # WHY: the frontend shows shares as percentages, they should add up to 100
    if dets:
        total = sum(d["confidence"] for d in dets) or 1.0
        shares = [round(d["confidence"] / total * 100) for d in dets]
        shares[0] += 100 - sum(shares)
        for d, s in zip(dets, shares):
            d["share"] = s
        dets.sort(key=lambda d: -d["share"])
    return dets


def is_construction_site(merged, frame_ok):
    # decide if the photo looks like a construction site
    #
    # IN:
    #   merged   - dict after fallback_guess
    #   frame_ok - bool from the CLIP frame check
    #
    # OUT: boolean
    # WHY: prevents random photos (bedsheet, cow, food) from becoming listings.
    #      a real detection counts. a fallback only counts when the frame passed CLIP.
    if not merged:
        return False
    for m in merged.values():
        if not str(m["source"]).startswith("fallback"):
            return True
    return frame_ok


def model_name():
    # name the engines that actually ran, so the UI does not claim YOLO
    # when the model failed to load (for example on a small host).
    names = []
    if world_model:
        names.append("yolo-world")
    if YOLO_AVAILABLE:
        names.append("yolov8n")
    names.append("visual")
    if clip_model:
        names.append("clip")
    return " + ".join(names)


def detect_materials(image_bytes):
    # main entry: photo bytes in, final detections out
    #
    # IN:  image_bytes - raw photo bytes
    # OUT: (detections, model_name, non_construction, is_construction_site)
    # WHY: runs the steps in order: shrink, three passes, CLIP, merge,
    #      add visual, drop household, fallback, build, normalize.
    _last_debug.clear()

    # Step 1: shrink once, reuse for all passes
    small = downscale_for_ai(image_bytes)
    image = Image.open(io.BytesIO(small)).convert("RGB")

    # Step 2: run all three passes on the same downscaled image
    yolo_hits, yolo_others = yolo_infer(image)
    world_hits, world_others = world_infer(image)
    visual_hits, condition, fabric_cov = visual_estimate(image)

    # Step 3: CLIP frame check, then CLIP on weak boxes
    # if CLIP is missing it returns 1.0, so the app fails open
    frame_p = clip_check([image])[0]
    frame_ok = frame_p > CLIP_GATE
    yolo_hits, yolo_rejected = clip_filter_hits(image, yolo_hits)
    world_hits, world_rejected = clip_filter_hits(image, world_hits)

    # Step 4: collect non-construction items
    others = collect_others(world_others, yolo_others, fabric_cov)

    # Step 5: merge both model passes
    merged = merge_hits(world_hits, yolo_hits)

    # Step 6: add color-based hits
    merged = add_visual_hits(merged, visual_hits, frame_ok, fabric_cov)

    # Step 7: drop household visual hits if people/fabric dominate
    merged, others, has_subject = drop_household_hits(merged, others)

    # Step 8: fallback guess on empty construction-looking frames
    merged = fallback_guess(merged, frame_ok, fabric_cov, has_subject)

    # Step 9: format detections for the UI
    dets = build_detections(merged, condition)

    # Step 10: normalize shares to 100%
    dets = normalize_shares(dets)

    # Step 11: decide if this is a construction site
    is_site = is_construction_site(merged, frame_ok)

    rejected = yolo_rejected + world_rejected
    _last_debug["world_raw"] = [{"material": m, "conf": round(c, 2),
                                 "area": round(a, 3)} for m, c, a, _b in world_hits]
    _last_debug["coco_raw"] = [{"material": m, "conf": round(c, 2),
                                "area": round(a, 3)} for m, c, a, _b in yolo_hits]
    _last_debug["clip_frame_p"] = round(frame_p, 3)
    _last_debug["clip_gate"] = CLIP_GATE
    _last_debug["clip_box_rejected"] = rejected
    _last_debug["rejected"] = rejected
    _last_debug["fabric_coverage"] = fabric_cov
    _last_debug["fallback_used"] = any(
        str(m.get("source", "")).startswith("fallback")
        for m in merged.values())

    return dets[:4], model_name(), others, is_site


def downscale_for_ai(raw, max_side=1280):
    # shrink phone photo before inference
    # original file is untouched, we only make a smaller copy for AI
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        if max(img.size) > max_side:
            img.thumbnail((max_side, max_side), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=88)
            return buf.getvalue()
    except Exception as e:
        print("Downscale skipped:", e)
    return raw
