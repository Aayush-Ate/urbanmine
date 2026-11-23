"""Detection geometry for the material passes.

Two model passes can see the same pile, and one pass can see two piles of the
same material. Collapsing every box of a material into one entry — the old
behaviour — kept the biggest pile and silently threw the rest of the
measurement away, so a yard with three brick stacks measured as one.

Here boxes are grouped per physical object first, then summed per material.
Coverage therefore tracks how much of the frame the material really fills.

Overlap is decided two ways:

* IoU >= 0.5 catches two boxes drawn around one pile.
* intersection / smaller_area >= 0.85 catches a small box sitting inside a big
  one. That is the same pile seen at two scales, where IoU stays low (~0.25)
  and a plain NMS would count it twice.

Nothing here loads torch. Pure geometry over the hits the models already
produced, so it runs in tests without weights.

No detection library on purpose: this needs one overlap matrix, and
`supervision` would add scipy (imported by its package __init__), av and
matplotlib — roughly 128 MB of image — for about ten lines of arithmetic.
"""

import numpy as np

# same pile, two boxes drawn around it
SAME_OBJECT_IOU = 0.5
# one box nested inside another: same pile at two scales
CONTAINMENT = 0.85
# coverage is a fraction of the frame, so it cannot exceed 1
MAX_COVERAGE = 1.0


def _intersection_matrix(boxes):
    """(n, n) area shared by each pair of xyxy boxes."""
    x1 = np.maximum(boxes[:, None, 0], boxes[None, :, 0])
    y1 = np.maximum(boxes[:, None, 1], boxes[None, :, 1])
    x2 = np.minimum(boxes[:, None, 2], boxes[None, :, 2])
    y2 = np.minimum(boxes[:, None, 3], boxes[None, :, 3])
    return np.clip(x2 - x1, 0.0, None) * np.clip(y2 - y1, 0.0, None)


def overlap_matrix(boxes):
    """(n, n) pair matrix of the two overlaps that matter here.

    * ``iou`` — shared area over the union, for two boxes drawn around the
      same pile.
    * ``ios`` — shared area over the smaller box's area. A tight box on one
      brick inside the box on the whole stack scores ~1.0 here while its iou
      is only ~0.25, which is exactly the pair a plain NMS counts twice.
    """
    boxes = np.asarray(boxes, dtype=float).reshape(-1, 4)
    inter = _intersection_matrix(boxes)
    wh = np.clip(boxes[:, 2:] - boxes[:, :2], 0.0, None)
    area = wh[:, 0] * wh[:, 1]

    union = area[:, None] + area[None, :] - inter
    smaller = np.minimum(area[:, None], area[None, :])
    iou = np.divide(inter, union, out=np.zeros_like(inter), where=union > 0)
    ios = np.divide(inter, smaller, out=np.zeros_like(inter), where=smaller > 0)
    return iou, ios


def same_object_matrix(boxes):
    """Boolean (n, n) matrix: True when two boxes are the same physical pile."""
    boxes = np.asarray(boxes, dtype=float).reshape(-1, 4)
    n = len(boxes)
    if n == 0:
        return np.zeros((0, 0), dtype=bool)

    iou, ios = overlap_matrix(boxes)
    same = (iou >= SAME_OBJECT_IOU) | (ios >= CONTAINMENT)
    np.fill_diagonal(same, True)
    return same


def _groups(same):
    """Connected components of the same-object matrix, as index lists.

    Transitive on purpose: if A matches B and B matches C, all three are one
    pile even when A and C barely overlap.
    """
    n = same.shape[0]
    seen = set()
    groups = []
    for start in range(n):
        if start in seen:
            continue
        seen.add(start)
        stack = [start]
        members = []
        while stack:
            i = stack.pop()
            members.append(i)
            for j in np.nonzero(same[i])[0]:
                j = int(j)
                if j not in seen:
                    seen.add(j)
                    stack.append(j)
        groups.append(sorted(members))
    return groups


def _join_sources(sources):
    out = []
    for s in sources:
        if s and s not in out:
            out.append(s)
    return " + ".join(out)


def merge_by_object(passes):
    """Merge model passes into one entry per material.

    ``passes`` is a list of ``(source_name, hits)`` where each hit is
    ``(material, confidence, coverage, box)``. Returns ``{material: {...}}``
    with ``cov`` summed over distinct piles, ``piles`` counting them, ``conf``
    the strongest hit, ``box`` the box the UI should crop, and ``source``
    naming every pass that contributed.
    """
    rows = []
    for source, hits in passes:
        for material, conf, area, box in hits:
            rows.append((material, float(conf), float(area), tuple(box), source))

    if not rows:
        return {}

    # keep materials in first-seen order, like the two loops this replaced
    order = []
    for row in rows:
        if row[0] not in order:
            order.append(row[0])

    merged = {}
    for material in order:
        idx = [i for i, row in enumerate(rows) if row[0] == material]
        boxes = np.array([rows[i][3] for i in idx], dtype=float).reshape(-1, 4)
        groups = _groups(same_object_matrix(boxes))

        piles = []
        for group in groups:
            members = [rows[idx[j]] for j in group]
            # one physical pile: confidence and box come from the clearest
            # view of it, size from the largest view (a tight box on one brick
            # inside the pile's mask under-measures the pile)
            best = max(members, key=lambda r: (r[1], r[2]))
            piles.append({
                "conf": max(r[1] for r in members),
                "area": max(r[2] for r in members),
                "box": best[3],
                "sources": [r[4] for r in members],
            })

        # distinct piles add up; the frame is the ceiling
        total = min(sum(p["area"] for p in piles), MAX_COVERAGE)
        top = max(piles, key=lambda p: (p["conf"], p["area"]))
        merged[material] = {
            "conf": top["conf"],
            "cov": round(total, 4),
            "source": _join_sources([s for p in piles for s in p["sources"]]),
            "box": top["box"],
            "piles": len(piles),
        }
    return merged
