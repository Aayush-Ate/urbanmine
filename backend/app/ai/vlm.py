"""A hosted vision model, used instead of the four local passes when configured.

One request replaces YOLO-World, YOLOv8n, the colour pass and the CLIP gate. A
multimodal model names the materials, estimates how much of each is visible,
judges condition, and says whether the frame is a site at all — the counting and
condition questions the local passes cannot answer.

Set VLM_API_KEY (or GEMINI_API_KEY) to turn it on. Without a key, `configured()`
is False and `detect_materials` never calls this module, so a fresh clone still
runs with zero keys on the local models. `AI_PROVIDER=local` forces the local
path even when a key exists; `VLM_MODEL` overrides the model id.

Everything here is stdlib plus Pillow: no new dependency for a provider that may
not be used. Failures return None, and the caller falls back to the local stack,
because a network blip should never mean "no materials found".
"""
import base64
import io
import json
import os
import urllib.request

from PIL import Image

from app.core.catalog import CONDITION_PRICE, FULL_QTY, MATERIAL_META

# Flash is the cheap, fast tier and is enough for naming a pile of bricks.
DEFAULT_MODEL = "gemini-2.5-flash"
API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

# A 1024px copy carries the material detail and keeps the request small.
MAX_SIDE = 1024
TIMEOUT_S = float(os.getenv("VLM_TIMEOUT_S", "30"))

# A model that answers "brick" or "timber" still means one of the 16.
ALIASES = {
    "brick": "Bricks", "bricks": "Bricks", "clay brick": "Bricks",
    "timber": "Wood", "lumber": "Wood", "wood plank": "Wood", "plank": "Wood",
    "steel": "Metal", "iron": "Metal", "scrap": "Metal", "steel pipe": "Metal",
    "rebar": "Rebar", "reinforcement": "Rebar",
    "aluminum": "Aluminium", "aluminium": "Aluminium",
    "pvc pipe": "PVC Pipes", "pvc": "PVC Pipes", "plastic pipe": "PVC Pipes",
    "tile": "Tiles", "ceramic tile": "Tiles",
    "marble slab": "Marble", "granite": "Marble",
    "glass pane": "Glass", "window glass": "Glass",
    "gypsum board": "Gypsum", "drywall": "Gypsum",
    "rubble": "Concrete", "cement": "Concrete", "concrete block": "Concrete",
    "door": "Doors", "window": "Windows", "sand": "Sand", "gravel": "Sand",
}


def api_key():
    return (os.getenv("VLM_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()


def model_id():
    return (os.getenv("VLM_MODEL") or DEFAULT_MODEL).strip()


def configured():
    # AI_PROVIDER=local is the escape hatch for an offline demo or a test run.
    return bool(api_key()) and os.getenv("AI_PROVIDER", "auto").strip().lower() != "local"


def _prompt():
    # The model is told the unit and scale for every material, so "about 40
    # bricks" comes back as a number in the same unit the catalog prices in.
    table = "\n".join(
        f"- {name}: priced per {m['unit']}, size read as {m['measure']}, "
        f"a full frame of it is roughly {FULL_QTY.get(name, 100)} {m['unit']}"
        for name, m in MATERIAL_META.items()
    )
    return f"""You are a demolition surveyor. Judge one site photo and list what is
worth salvaging. The only materials you may name:
{table}

Answer with JSON only, no prose and no markdown:
{{
  "is_construction_site": true or false,
  "materials": [
    {{
      "material": "<one name from the list above, spelled exactly>",
      "quantity": <number in that material's unit, estimated from what is visible>,
      "condition": "Excellent" | "Good" | "Fair" | "Poor",
      "confidence": <0 to 1>,
      "bbox": [x1, y1, x2, y2] or null,
      "note": "<at most 8 words>"
    }}
  ],
  "not_construction": [{{"label": "<thing you saw>", "confidence": <0 to 1>}}]
}}

Rules:
- bbox is normalised 0 to 1, [left, top, right, bottom], around the pile itself.
- Quantity is an estimate for what is visible. Do not invent a truckload.
- A bedroom, living room, person, pet, food, or a single small object is not a
  site: return is_construction_site false and an empty materials list.
- List at most 6 materials. Fewer, confident entries beat a long guess.
- Only list material you can actually see, never what a site usually contains."""


def _ask(image_b64):
    # One POST, key in a header rather than the query string so it cannot end
    # up in a proxy access log.
    body = {
        "contents": [{
            "parts": [
                {"text": _prompt()},
                {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
            ]
        }],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "maxOutputTokens": 1024,
        },
    }
    req = urllib.request.Request(
        f"{API_ROOT}/{model_id()}:generateContent",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key()},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return json.loads(resp.read().decode())


def _answer_text(payload):
    for cand in payload.get("candidates") or []:
        for part in (cand.get("content") or {}).get("parts") or []:
            if isinstance(part.get("text"), str):
                return part["text"]
    return ""


def _material(raw):
    if not isinstance(raw, str):
        return None
    want = raw.strip().lower()
    for known in MATERIAL_META:
        if known.lower() == want:
            return known
    return ALIASES.get(want)


def _bbox(raw):
    # Anything that is not four numbers inside the frame is discarded: the
    # browser crops with these, and a bad box shows the wrong object.
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(v) for v in raw)
    except (TypeError, ValueError):
        return None
    if not all(0.0 <= v <= 1.0 for v in (x1, y1, x2, y2)):
        return None
    if x2 - x1 < 0.01 or y2 - y1 < 0.01:
        return None
    return [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)]


def _quantity(name, raw):
    # Guesses are clamped to the same "whole frame" ceiling the local pipeline
    # uses, so a hallucinated 90,000 sq ft of marble cannot become a listing.
    try:
        q = float(raw)
    except (TypeError, ValueError):
        q = 0.0
    if q <= 0:
        return None
    ceiling = FULL_QTY.get(name, 100)
    q = min(q, ceiling)
    return int(round(q)) if MATERIAL_META[name]["measure"] in ("pieces", "weight") else round(q, 1)


def _shape(answer):
    """Turn the model's JSON into the list /api/analyze already returns."""
    raw_materials = answer.get("materials") if isinstance(answer, dict) else None
    best = {}
    for item in raw_materials or []:
        if not isinstance(item, dict):
            continue
        name = _material(item.get("material"))
        if name is None:
            continue
        qty = _quantity(name, item.get("quantity"))
        if qty is None:
            continue
        try:
            conf = float(item.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        conf = min(max(conf, 0.05), 1.0)
        condition = item.get("condition") if item.get("condition") in CONDITION_PRICE else "Good"
        note = item.get("note") if isinstance(item.get("note"), str) else ""
        candidate = {
            "material": name,
            "quantity": qty,
            "unit": MATERIAL_META[name]["unit"],
            "mode": MATERIAL_META[name]["measure"],
            "condition": condition,
            "confidence": round(conf, 2),
            "suggested_price_per_unit": round(
                MATERIAL_META[name]["price"] * CONDITION_PRICE[condition]
            ),
            "bbox": _bbox(item.get("bbox")),
            "source": f"vlm ({note[:40]})" if note else "vlm",
        }
        # one entry per material: the most confident box wins, and a boxed hit
        # beats an unboxed one at the same confidence
        current = best.get(name)
        if current is None or (conf, candidate["bbox"] is not None) > (
            current["confidence"], current["bbox"] is not None
        ):
            best[name] = candidate

    dets = sorted(best.values(), key=lambda d: -d["confidence"])
    if dets:
        total = sum(d["confidence"] for d in dets) or 1.0
        shares = [round(d["confidence"] / total * 100) for d in dets]
        shares[0] += 100 - sum(shares)
        for d, s in zip(dets, shares):
            d["share"] = s

    others = []
    for item in answer.get("not_construction") or []:
        if not isinstance(item, dict) or not isinstance(item.get("label"), str):
            continue
        try:
            c = float(item.get("confidence", 0.5))
        except (TypeError, ValueError):
            c = 0.5
        others.append({"label": item["label"][:40], "confidence": round(min(max(c, 0.05), 1.0), 2)})

    # A frame with no material is not a site, whatever the field says.
    is_site = bool(answer.get("is_construction_site")) and bool(dets)
    checked = len([m for m in raw_materials or [] if isinstance(m, dict)]) + len(others)
    return {
        "dets": dets,
        "others": others,
        "is_site": is_site,
        "verification": {
            "checked": checked,
            "rejected": len(others),
            "kept": len(dets),
        },
        "model": f"vlm:{model_id()}",
    }


def vlm_detect(raw):
    """Photo bytes in, the same shape the local pipeline returns — or None.

    None means "no key, no answer, or a bad answer": the caller then runs the
    local models, so the feature degrades instead of failing.
    """
    if not configured():
        return None
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        if max(img.size) > MAX_SIDE:
            img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=88)
        payload = _ask(base64.b64encode(buf.getvalue()).decode())
        answer = json.loads(_answer_text(payload) or "{}")
        return _shape(answer)
    except Exception as e:
        print("VLM unavailable, using local models:", e)
        return None
