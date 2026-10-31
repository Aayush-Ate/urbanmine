# photo in, materials out.
# 3 passes on the same small copy, then merge and filter.
#
# 1. yolov8n: everyday objects -> wood/metal (chair, bus, etc)
# 2. yolo-world: text prompts -> the 16 materials (bricks, doors, pipes...)
# 3. color: pixel colors on a 160px thumb, no net
# then clip checks the photo and the boxes. if it smells like a bedroom
# or a desk, we drop the guess. no crop = no listing.

import io
import os

from PIL import Image

from app.core.catalog import (
    CLIP_GATE, CLIP_LABELS, COCO_TO_MATERIAL, CONDITION_PRICE, MATERIAL_META,
    WORLD_CLASSES, WORLD_CONF, WORLD_IGNORE, WORLD_NONCON, WORLD_PROMPTS,
)
from app.core.scoring import qty_for

# models load lazy. first photo is slow (download + load), after that its fast.
# if a model fails we keep going with what we have.
YOLO_AVAILABLE = False
yolo_model = None
world_model = None
clip_model = None
clip_proc = None

# filled by detect_materials, returned by /api/analyze?debug=1
_last_debug = {}


def _load_yolo():
    # small model. knows everyday objects, not bricks.
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
    # bigger model. we give it material prompts and it draws boxes.
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
    # clip tells us construction vs household. this is the bouncer.
    # bedsheet, pen, person -> not a listing.
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
    # shared box loop for yolov8n and yolo-world.
    # map label -> material. household labels go to others so the ui can
    # show what got thrown out. tiny boxes are junk, skip them.
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
        # a pen on a desk is a tiny box, not a salvage pile
        if area < 0.005:
            continue
        hits.append((mat, c, area, (x1, y1, x2, y2)))

    others_list = [{"label": k, "confidence": round(v, 2)} for k, v in others.items()]
    return hits, others_list


def yolo_infer(image):
    # pass 1. chair/bed/couch -> wood, car/bus/truck -> metal.
    # dumb on purpose: yolov8n has no brick class.
    if yolo_model is None:
        _load_yolo()
    return _run_infer(yolo_model, image, 0.25, COCO_TO_MATERIAL.get, set(), WORLD_NONCON)


def world_infer(image):
    # pass 2. prompts like "stack of red clay bricks" -> bricks.
    # this is the one that actually knows materials.
    if world_model is None:
        _load_world()
    return _run_infer(world_model, image, WORLD_CONF, WORLD_PROMPTS.get, WORLD_IGNORE, WORLD_NONCON)


def visual_estimate(image):
    # pass 3. no net, just colors on a 160px thumb.
    # catches big piles the boxes miss. also guesses condition and how much
    # of the photo is cloth (bedsheet detector).
    try:
        import numpy as np

        # shrink to 160 so the color math is cheap
        img = image.convert("RGB").resize((160, 160))
        a = np.asarray(img).reshape(-1, 3).astype(float)

        r, g, b = a[:, 0], a[:, 1], a[:, 2]
        mx, mn = a.max(axis=1), a.min(axis=1)
        sat = (mx - mn) / np.maximum(mx, 1)
        val = mx / 255.0

        gray2d = a.mean(axis=1).reshape(160, 160)
        edge = (float(np.abs(np.diff(gray2d, axis=1)).mean()) +
                float(np.abs(np.diff(gray2d, axis=0)).mean())) / 2 / 255.0

        # wood = brown-ish, brick = red, concrete = gray, metal = bright/blue
        wood = ((r > g + 15) & (g >= b) & (sat > 0.15) & (r > 60)
                & ((r - g) < 70)).mean()
        brick = ((r > 130) & (g < 90) & (b < 80) & ((r - b) > 60)
                 & (sat > 0.3)).mean()
        concrete = ((sat < 0.12) & (val > 0.25) & (val < 0.8)).mean()
        metal = (((sat < 0.1) & (val > 0.8)) |
                 ((b > r + 10) & (sat < 0.2) & (val > 0.45) & (val < 0.75))).mean()

        # bright smooth cloth = bedsheet/clothes. edge < 0.05 means smooth.
        fabric = ((sat < 0.18) & (val > 0.6)).mean() if edge < 0.05 else 0.0

        out = []
        for m, c in [("Wood", wood), ("Bricks", brick),
                     ("Concrete", concrete), ("Metal", metal)]:
            if c >= 0.08:
                out.append((m, round(min(0.55 + c, 0.89), 2), round(float(c), 3)))

        gray = a.mean(axis=1)
        contrast = float(gray.std() / 255.0)
        meanv = float(val.mean())

        # low contrast or dark = worn, call it Fair
        cond = "Fair" if (contrast < 0.12 or meanv < 0.25) else "Good"
        return out, cond, round(float(fabric), 3)
    except Exception as e:
        print("Visual estimate failed:", e)
        return [], "Good", 0.0


def clip_check(crops):
    # clip score for each crop: 1.0 = construction, 0.0 = household.
    # if clip aint loaded we return 1.0 so the app still works (fail open).
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
    # cut each box out of the photo so clip can look at it alone.
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
    # ask clip about every box: does this crop look like construction?
    #
    # strong boxes used to skip this. thats how a pen labeled metal at 0.42
    # got through. model was confident and wrong. now we check every strong
    # box and the first 8 weak ones so busy photos stay fast.
    #
    # returns kept, rejected, checked. checked is how many boxes clip saw,
    # so the ui can show a real counter.
    strong = [h for h in hits if h[1] >= 0.50]
    weak = [h for h in hits if h[1] < 0.50]

    check = []
    boxes = []
    for h in strong + weak[:8]:
        x1, y1, x2, y2 = h[3]
        if x2 - x1 < 2 or y2 - y1 < 2:
            continue
        check.append(h)
        boxes.append((x1, y1, x2, y2, h[1]))

    if not check:
        return hits, [], 0

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
    return kept + rest, rejected, len(check)


def merge_hits(world_hits, yolo_hits):
    # merge the two model passes. same material from both? keep the higher
    # conf and the box that won, so the ui crops the right thing.
    merged = {}
    for mat, conf, area, box in world_hits:
        merged[mat] = {"conf": conf, "cov": area, "source": "yolo-world", "box": box}
    for mat, conf, area, box in yolo_hits:
        if mat in merged:
            if conf > merged[mat]["conf"]:
                merged[mat]["conf"] = conf
                merged[mat]["box"] = box
            merged[mat]["cov"] = max(merged[mat]["cov"], area)
            merged[mat]["source"] += " + yolov8n"
        else:
            merged[mat] = {"conf": conf, "cov": area, "source": "yolov8n", "box": box}
    return merged


def add_visual_hits(merged, visual_hits, frame_ok, fabric_cov):
    # color can make a real hit stronger. it should never make a listing alone.
    # a color-only hit has no box, so we cant crop it. a wooden pen looks like
    # timber and boom, fake listing. so only boost what a model already found,
    # and only when clip says the frame is construction.
    if not frame_ok:
        return merged
    for mat, conf, cov in visual_hits:
        if mat not in merged:
            continue
        if fabric_cov > 0.5 and mat in ("Concrete", "Metal"):
            continue
        merged[mat]["cov"] = min(merged[mat]["cov"] + cov * 0.5, 1.0)
        merged[mat]["conf"] = round(max(merged[mat]["conf"], conf), 2)
        merged[mat]["source"] += " + visual"
    return merged


def collect_others(world_others, yolo_others, fabric_cov):
    # build the "not construction" list for the ui. one label each.
    # if a lot of the photo is cloth, add fabric/textile so the user sees
    # why the listing got dropped.
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


# Cloth in the frame means the photo is probably a bedroom, not a site.
CLOTH_LABELS = {"clothes", "bedsheet", "fabric", "fabric / textile",
                "blanket", "curtain"}


def drop_household_hits(merged, others, frame_ok):
    # bedsheet or bedroom should not become a listing.
    #
    # household = clip says the frame aint a site, or the excluded list has cloth.
    # then drop the hits only yolov8n found. it sees a bed/chair and calls it wood.
    # yolo-world hits stay: its prompts are real materials, and a worker next to
    # a wood pile is still a wood pile.
    has_cloth = any(item["label"] in CLOTH_LABELS for item in others)
    if frame_ok and not has_cloth:
        return merged, others

    kept = {}
    for material, hit in merged.items():
        from_yolov8_only = ("yolov8n" in hit["source"]
                            and "yolo-world" not in hit["source"])
        if from_yolov8_only:
            others.append({
                "label": f"{material.lower()} (household item, not listed)",
                "count": 1,
                "confidence": hit["conf"],
            })
        else:
            kept[material] = hit

    return kept, others


def build_detections(merged, condition, size=None):
    # turn merged hits into ui objects. bbox is 0..1 so the browser can crop
    # the same spot from the original photo, whatever its size.
    dets = []
    width, height = size or (0, 0)
    for mat, m in sorted(merged.items(), key=lambda kv: -kv[1]["conf"]):
        meta = MATERIAL_META[mat]
        bbox = None
        box = m.get("box")
        if box and width and height:
            x1, y1, x2, y2 = box
            bbox = [
                round(max(0.0, min(x1 / width, 1.0)), 4),
                round(max(0.0, min(y1 / height, 1.0)), 4),
                round(max(0.0, min(x2 / width, 1.0)), 4),
                round(max(0.0, min(y2 / height, 1.0)), 4),
            ]
        dets.append({
            "material": mat,
            "bbox": bbox,
            "quantity": qty_for(mat, m["cov"]),
            "unit": meta["unit"],
            "mode": meta["measure"],
            "condition": condition,
            "confidence": m["conf"],
            # guessed condition, so guessed price: Poor pays 40% of the base
            "suggested_price_per_unit": round(meta["price"] * CONDITION_PRICE.get(condition, 0.85)),
            "source": m["source"],
        })
    return dets


def normalize_shares(dets):
    # make the shares add up to 100. frontend shows them as percentages.
    if dets:
        total = sum(d["confidence"] for d in dets) or 1.0
        shares = [round(d["confidence"] / total * 100) for d in dets]
        shares[0] += 100 - sum(shares)
        for d, s in zip(dets, shares):
            d["share"] = s
        dets.sort(key=lambda d: -d["share"])
    return dets


def is_construction_site(merged):
    # only a real material counts. no fallback, no guessing concrete.
    return bool(merged)


def model_name():
    # list the engines that actually ran. dont claim yolo if it failed to load.
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
    # main entry. photo bytes in, detections out.
    # returns dets, model, others, is_site, verification.
    # verification = {checked, rejected, kept} for the ui counter.
    _last_debug.clear()

    # 1. shrink once, reuse for every pass
    small = downscale_for_ai(image_bytes)
    image = Image.open(io.BytesIO(small)).convert("RGB")

    # 2. run the 3 passes
    yolo_hits, yolo_others = yolo_infer(image)
    world_hits, world_others = world_infer(image)
    visual_hits, condition, fabric_cov = visual_estimate(image)

    # 3. clip on the whole photo, then on the boxes.
    # missing clip returns 1.0 (fail open).
    frame_p = clip_check([image])[0]
    frame_ok = frame_p > CLIP_GATE
    yolo_hits, yolo_rejected, yolo_checked = clip_filter_hits(image, yolo_hits)
    world_hits, world_rejected, world_checked = clip_filter_hits(image, world_hits)

    # 4. non-construction list
    others = collect_others(world_others, yolo_others, fabric_cov)

    # 5. merge the two model passes
    merged = merge_hits(world_hits, yolo_hits)

    # 6. color can boost a hit, never create one
    merged = add_visual_hits(merged, visual_hits, frame_ok, fabric_cov)

    # 7. household photo? drop yolov8n-only hits
    merged, others = drop_household_hits(merged, others, frame_ok)

    # 8. build ui detections
    dets = build_detections(merged, condition, image.size)

    # 9. shares add to 100
    dets = normalize_shares(dets)

    # 10. site is real only if something survived
    is_site = is_construction_site(merged)

    rejected = yolo_rejected + world_rejected
    checked = yolo_checked + world_checked
    verification = {
        "checked": checked,
        "rejected": len(rejected),
        "kept": len(dets),
    }

    _last_debug["world_raw"] = [{"material": m, "conf": round(c, 2),
                                 "area": round(a, 3)} for m, c, a, _b in world_hits]
    _last_debug["coco_raw"] = [{"material": m, "conf": round(c, 2),
                                "area": round(a, 3)} for m, c, a, _b in yolo_hits]
    _last_debug["clip_frame_p"] = round(frame_p, 3)
    _last_debug["clip_gate"] = CLIP_GATE
    _last_debug["clip_box_rejected"] = rejected
    _last_debug["rejected"] = rejected
    _last_debug["fabric_coverage"] = fabric_cov
    _last_debug["verification"] = verification

    return dets[:4], model_name(), others, is_site, verification


def downscale_for_ai(raw, max_side=1280):
    # shrink phone photo before ai. original file stays untouched.
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
