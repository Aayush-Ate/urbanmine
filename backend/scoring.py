"""Distances, quantities, and match ranking. Pure math, no files, no models.

Kept separate so tests can pin it exactly. Match formula: material 40% +
quantity 25% + distance 20% + condition 15%.
"""
import math

from catalog import CONDITION_SCORES, FULL_QTY


def haversine_km(lat1, lon1, lat2, lon2):
    """Kilometers between two points. Same result as PostGIS
    ST_Distance(geography) / 1000."""
    R = 6371.0
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def qty_for(material, coverage):
    """Quantity from measured photo coverage (0 to 1). A half-frame of bricks
    is 2500 pieces. Doors and Windows cap at 40: beyond that you are counting
    pieces, not area."""
    base = FULL_QTY.get(material, 100)
    q = max(1, round(base * min(max(coverage, 0.02), 1.0)))
    if material in ("Doors", "Windows"):
        q = max(1, min(q, 40))
    return q


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
    total = mat * 0.40 + q * 0.25 + dist_score * 0.20 + c * 0.15
    return round(total * 100, 1), round(d, 1)
