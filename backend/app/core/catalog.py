"""Prices, units, prompts, and gates for all 16 materials.

Every number the app shows comes from here. Change a price and listings,
and match follow, because they all read MATERIAL_META.
"""
# 16 sellable materials. unit = how buyers buy it, price = ₹/unit default,
# icon = the dot colour used by the frontend.
#
# These are RESALE values for used material in Bengaluru, not new-shop MRP.
# A salvaged brick is not a new brick. Scrap metal follows the Indian scrap
# market (steel ≈ ₹35/kg, copper ≈ ₹750/kg, aluminium ≈ ₹180/kg); the rest are
# what a salvage yard pays for a good-condition lot.
# measure = how the size is taken on site: area (L×W), volume (L×W×H),
# length (one run), weight (kg on a scale), pieces (counted).
MATERIAL_META = {
    "Wood": {"unit": "sq ft", "price": 70, "icon": "🪵", "measure": "area"},
    "Bricks": {"unit": "pcs", "price": 6, "icon": "🧱", "measure": "pieces"},
    "Metal": {"unit": "kg", "price": 35, "icon": "🔩", "measure": "weight"},
    "Doors": {"unit": "pcs", "price": 1500, "icon": "🚪", "measure": "pieces"},
    "Windows": {"unit": "pcs", "price": 1800, "icon": "🪟", "measure": "pieces"},
    "Concrete": {"unit": "cu ft", "price": 15, "icon": "🏗️", "measure": "volume"},
    "Plywood": {"unit": "sq ft", "price": 30, "icon": "🪚", "measure": "area"},
    "Rebar": {"unit": "kg", "price": 34, "icon": "🔗", "measure": "weight"},
    "Copper": {"unit": "kg", "price": 750, "icon": "🪙", "measure": "weight"},
    "Aluminium": {"unit": "kg", "price": 180, "icon": "⚙️", "measure": "weight"},
    "PVC Pipes": {"unit": "m", "price": 60, "icon": "🚰", "measure": "length"},
    "Tiles": {"unit": "sq ft", "price": 25, "icon": "🏺", "measure": "area"},
    "Marble": {"unit": "sq ft", "price": 100, "icon": "💎", "measure": "area"},
    "Glass": {"unit": "sq ft", "price": 45, "icon": "🪞", "measure": "area"},
    "Gypsum": {"unit": "pcs", "price": 120, "icon": "⬜", "measure": "pieces"},
    "Sand": {"unit": "cu ft", "price": 50, "icon": "⏳", "measure": "volume"},
}

# A photo cannot tell a sound plank from a rotten one, so the condition is a
# guess and the price has to admit it: a Poor pile is worth a fraction of a
# Good one. Keys match CONDITION_SCORES below.
CONDITION_PRICE = {"Excellent": 1.0, "Good": 0.85, "Fair": 0.65, "Poor": 0.4}

# Phrase given to the model (key) and the material it counts as (value).
# Specific beats generic: bare "door" fires on any rectangle, while
# "wooden door removed from frame" fires on salvage.
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

# These six are not salvage. They are intact-room surfaces, listed here so the
# model has somewhere to put them besides our material prompts. Without a
# "painted wall" option, a bedroom wall matches "concrete wall" (closest
# phrase) and becomes a fake Concrete listing. With it, the box matches here
# and vision.py drops it. Standard null-class practice for open-vocabulary
# models (see Roboflow's YOLO-World prompting guide).
WORLD_IGNORE = {"plastered wall", "painted wall", "room interior", "ceiling",
                "tiled floor", "wooden floor"}

# People, clothes, pets, food. Never listed. They land in
# non_construction[] so the UI shows what was excluded and why.
WORLD_NONCON = {"person", "man", "woman", "child", "clothes", "bedsheet",
                "fabric", "blanket", "curtain", "dog", "cat", "bird", "cow",
                "horse", "sheep", "monkey", "goat", "elephant",
                "plastic bag", "plastic bottle"}
WORLD_CLASSES = list(WORLD_PROMPTS) + sorted(WORLD_NONCON) + sorted(WORLD_IGNORE)

# Below this World confidence, boxes are junk. CLIP gate disposes the rest.
WORLD_CONF = 0.12

# yolov8n only knows everyday objects. It has no brick or concrete class,
# so furniture counts as Wood and vehicles/appliances as Metal scrap.
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

# Quantity when a material fills the whole photo. qty_for() in scoring.py
# multiplies this by measured coverage. Nothing here is random.
FULL_QTY = {
    "Wood": 800, "Bricks": 5000, "Metal": 1200,
    "Doors": 20, "Windows": 30, "Concrete": 500,
    "Plywood": 600, "Rebar": 800, "Copper": 300,
    "Aluminium": 500, "PVC Pipes": 100, "Tiles": 800,
    "Marble": 400, "Glass": 60, "Gypsum": 100, "Sand": 400,
}

MATERIALS = ["Wood", "Bricks", "Metal", "Doors", "Windows", "Concrete"]
CONDITION_SCORES = {"Excellent": 1.0, "Good": 0.8, "Fair": 0.55, "Poor": 0.3}

# CLIP compares two labels. A photo or crop is kept only when the first
# label (construction) scores at least 0.60. The second label includes small
# desk objects so a pen does not get read as scrap metal.
CLIP_LABELS = [
    "a photo of construction material, demolition debris, or salvaged building parts like doors, tiles, or pipes",
    "a photo of clothes, bedsheet, fabric, a person, a pet, food, or a small household object like a pen, phone, or cup",
]
CLIP_GATE = 0.60
