"""Prices, units, prompts, and gates for all 16 materials.

Every number the app shows comes from here. Change a price and listings,
match, and impact all follow, because they all read MATERIAL_META.
"""
# 16 sellable materials. unit = how buyers buy it, price = ₹/unit default,
# co2_per_unit_kg = rough tonnes-diverted factor, icon = frontend dot.
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

# The two labels for the CLIP check: construction or household. Each weak
# box is scored against both; below 0.60 construction it is rejected.
CLIP_LABELS = [
    "a photo of construction material, demolition debris, or salvaged building parts like doors, tiles, or pipes",
    "a photo of clothes, bedsheet, fabric, a person, a pet, or food",
]
CLIP_GATE = 0.60
