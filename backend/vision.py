# Photo bytes in, material detections out.
# This file runs AI on the photo in three passes, then merges everything.
#
# Pass 1: YOLOv8n finds everyday objects (chair -> Wood, bus -> Metal)
# Pass 2: YOLO-World finds materials with descriptive prompts (bricks -> Bricks)
# Pass 3: Visual color looks at pixel colors on a small thumbnail
# Then CLIP checks if weak boxes look like construction or household

import io
import os
import tempfile

from catalog import (
    CLIP_GATE, CLIP_LABELS, COCO_TO_MATERIAL, MATERIAL_META,
    WORLD_CLASSES, WORLD_CONF, WORLD_IGNORE, WORLD_NONCON, WORLD_PROMPTS,
)
from scoring import qty_for

# these are the AI models
# they start as None and load only when needed
# first photo is slow because models download and load, after that it is fast
yolo_model = None
world_model = None
clip_model = None
clip_proc = None


def _load_yolo():
    # loads YOLOv8n model
    # this is the small model that finds everyday objects
    global yolo_model
    try:
        from ultralytics import YOLO
        yolo_model = YOLO("yolov8n.pt")
    except Exception as e:
        print("YOLOv8n not loaded:", e)
        yolo_model = False


def _load_world():
    # loads YOLO-World model
    # this is the bigger model that uses text prompts to find materials
    global world_model
    try:
        from ultralytics import YOLO
        world_model = YOLO("yolov8m-worldv2.pt")
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


def yolo_infer(image_bytes):
    # Pass 1: find everyday objects and map them to salvage materials
    # image_bytes is the photo as bytes
    if yolo_model is None:
        _load_yolo()
        if yolo_model is None or yolo_model is False:
            return [], []
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(image_bytes)
            tmp = f.name
        res = yolo_model(tmp, verbose=False, conf=0.25)[0]
        os.unlink(tmp)
    except Exception as e:
        print("YOLO inference failed:", e)
        return [], []

    hits = []
    others = {}
    names = res.names

    # loop through all boxes YOLO found
    for b in res.boxes:
        label = str(names[int(b.cls[0])]).lower()
        conf = float(b.conf[0])
        mat = COCO_TO_MATERIAL.get(label)

        # if this object is not in our material map
        if mat is None:
            # if it is a person, bedsheet, pet etc, put it in others
            # so the UI shows it was excluded
            if label in WORLD_NONCON:
                others[label] = max(others.get(label, 0), conf)
            continue

        # w and h are width and height of the box as fraction of image
        _, _, w, h = (float(v) for v in b.xywhn[0])
        area = max(0.0, min(w * h, 1.0))
        hits.append((mat, conf, area))

    others_list = [{"label": k, "confidence": round(v, 2)} for k, v in others.items()]
    return hits, others_list


def world_infer(image_bytes):
    # Pass 2: descriptive-prompt detection for all 16 materials
    # uses text prompts like "a stack of red clay bricks" to find materials
    if world_model is None:
        _load_world()
        if world_model is None or world_model is False:
            return [], []
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(image_bytes)
            tmp = f.name
        res = world_model.predict(tmp, verbose=False, conf=WORLD_CONF)[0]
        os.unlink(tmp)
    except Exception as e:
        print("YOLO-World inference failed:", e)
        return [], []

    hits = []
    others = {}
    names = res.names

    for b in res.boxes:
        label = str(names[int(b.cls[0])]).lower()
        conf = float(b.conf[0])

        # WORLD_IGNORE are intact room surfaces like wall, ceiling
        # they are not salvage so we skip them
        if label in WORLD_IGNORE:
            continue

        mat = WORLD_PROMPTS.get(label)
        if mat is None:
            # if it is a person, bedsheet, pet etc, put it in others
            if label in WORLD_NONCON:
                others[label] = max(others.get(label, 0), conf)
            continue

        _, _, w, h = (float(v) for v in b.xywhn[0])
        area = max(0.0, min(w * h, 1.0))
        hits.append((mat, conf, area))

    others_list = [{"label": k, "confidence": round(v, 2)} for k, v in others.items()]
    return hits, others_list


def visual_estimate(image_bytes):
    # Pass 3: look at pixel colors on a 160px thumbnail
    # no neural net here, just checks if colors look like wood, bricks, concrete, metal
    try:
        import numpy as np
        from PIL import Image

        # PIL is Python Imaging Library
        # Image.open opens the image, convert("RGB") makes it RGB
        # resize((160, 160)) makes it small so color check is fast
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB").resize((160, 160))
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
    # crops are cropped images from the photo
    # returns a list of probabilities, one per crop
    # if CLIP is not available, returns 1.0 for everything (fail open)
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
            for c in crops[:8]:
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
    # pil_img is the full image, boxes are the detected object boxes
    W, H = pil_img.size
    out = []
    for (x1, y1, x2, y2, _c) in boxes:
        x1, y1 = max(0, int(x1)), max(0, int(y1))
        x2, y2 = min(W, int(x2)), min(H, int(y2))
        if x2 - x1 < 16 or y2 - y1 < 16:
            continue
        out.append(pil_img.crop((x1, y1, x2, y2)))
    return out


def detect_materials(image_bytes):
    # main function: one photo goes in, final detections come out
    # steps happen in order, one after another

    # Step 1: shrink photo for speed
    # phone photos are 5-15MB, AI only needs 1280px max
    small = downscale_for_ai(image_bytes)

    # Step 2: run all three passes
    # yolo_infer finds everyday objects
    # world_infer finds materials with prompts
    # visual_estimate looks at pixel colors
    yolo_hits, yolo_others = yolo_infer(small)
    world_hits, world_others = world_infer(small)
    visual_hits, condition, fabric_cov = visual_estimate(small)

    # collect non-construction items so UI can show what was excluded
    others = list(world_others)
    for o in yolo_others:
        if o["label"] not in {x["label"] for x in others}:
            others.append(o)

    # if the photo is mostly fabric, add it to others so it is not listed
    if fabric_cov >= 0.3:
        others.append({
            "label": "fabric / textile",
            "count": 1,
            "confidence": round(min(0.6 + fabric_cov * 0.3, 0.88), 2),
        })

    # Step 3: CLIP frame check
    # does the whole photo look like construction or household?
    from PIL import Image as PILImage
    full = PILImage.open(io.BytesIO(small)).convert("RGB")
    frame_ok = True
    try:
        import transformers
        if transformers is not None:
            # CLIP returns probability construction vs household
            # if below CLIP_GATE (0.60), the frame looks household
            p = clip_check([full])[0]
            frame_ok = p > CLIP_GATE
    except ImportError:
        pass

    # Step 4: merge hits from all passes into one dict
    # merged[material] = {confidence, coverage, source}
    merged = {}
    for mat, conf, area in world_hits:
        merged[mat] = {"conf": conf, "cov": area, "source": "yolo-world"}
    for mat, conf, area in yolo_hits:
        if mat in merged:
            if conf > merged[mat]["conf"]:
                merged[mat]["conf"] = conf
                merged[mat]["source"] += " + yolov8n"
        else:
            merged[mat] = {"conf": conf, "cov": area, "source": "yolov8n"}
    for mat, conf, cov in visual_hits:
        # if fabric covers most of photo, do not trust concrete or metal from colors
        if fabric_cov > 0.5 and mat in ("Concrete", "Metal"):
            continue
        # if whole frame looks household, do not invent materials from colors alone
        if not frame_ok and mat not in merged:
            continue
        if mat in merged:
            merged[mat]["cov"] = min(merged[mat]["cov"] + cov * 0.5, 1.0)
            merged[mat]["conf"] = round(max(merged[mat]["conf"], conf), 2)
            merged[mat]["source"] += " + visual"
        else:
            merged[mat] = {"conf": conf, "cov": cov, "source": "visual estimate"}

    # Step 5: household rules
    # if people or fabric dominate the photo, drop visual-only hits
    # because a bedsheet photo should not produce a Concrete listing
    subjects = ("person", "man", "woman", "child", "clothes", "bedsheet",
                "fabric / textile", "blanket", "curtain", "dog", "cat",
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

    # Step 6: fallback guess
    # if nothing found but frame looks like construction, guess Concrete
    # but only if it is not a cloth or household frame
    if not merged:
        if fabric_cov > 0.5 or not frame_ok or has_subject:
            pass
        else:
            merged = {"Concrete": {"conf": 0.30, "cov": 0.1,
                                   "source": "fallback (low-confidence guess)"}}

    # Step 7: format detections for the UI
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

    # normalize shares so the list always totals 100%
    if dets:
        total = sum(d["confidence"] for d in dets) or 1.0
        shares = [round(d["confidence"] / total * 100) for d in dets]
        shares[0] += 100 - sum(shares)
        for d, s in zip(dets, shares):
            d["share"] = s
        dets.sort(key=lambda d: -d["share"])

    # is_site tells the frontend if this looks like a construction site
    # prevents random photos (bedsheet, cow, food) from becoming listings
    real = [m for m in merged.values()
            if not str(m["source"]).startswith("fallback")]
    is_site = bool(yolo_hits or world_hits) or (
        frame_ok and any(m["cov"] >= 0.2 for m in real))

    model = "yolo-world + yolov8n + visual"
    return dets[:4], model, others, is_site


def downscale_for_ai(raw, max_side=1280):
    # shrink phone photo before inference
    # original file is untouched, we only make a smaller copy for AI
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        if max(img.size) > max_side:
            img.thumbnail((max_side, max_side), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=88)
            return buf.getvalue()
    except Exception as e:
        print("Downscale skipped:", e)
    return raw
