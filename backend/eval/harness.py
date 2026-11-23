"""Accuracy harness for the material detector.

Guessing which confidence cut is right is expensive; measuring it is cheap.
This runs the real pipeline over a labeled manifest and reports, per material,
precision / recall / F1 — then sweeps the confidence cut so the values in
``WORLD_CONF_BY_MATERIAL`` come from data instead of intuition.

usage, from backend/:

    python -m eval.harness --manifest eval/manifest.jsonl
    python -m eval.harness --manifest eval/manifest.jsonl --out eval/report.json
    python -m eval.harness --manifest eval/manifest.jsonl --min-recall 0.8

manifest.jsonl, one photo per line:

    {"image": "uploads/0b3bbb7267.jpg", "materials": ["Bricks"],
     "coverage": {"Bricks": 0.4}}

``materials`` is what a human says is really in the frame; ``[]`` means the
photo contains no salvage material (a bedroom, a desk, an empty yard) and any
prediction on it is a false positive. ``coverage`` is optional and only feeds
the quantity-error column.
"""

import argparse
import json
import os
import sys

# sweep grid for the confidence cut. WORLD_CONF_BY_MATERIAL is applied after
# the label is known, so this is the same knob the pipeline uses.
SWEEP = [round(0.05 * i, 2) for i in range(1, 19)]


def load_manifest(path):
    """Read and validate the manifest. Fail loudly: a typo in a label silently
    measured as a false negative would make the report lie."""
    records = []
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{lineno}: not JSON ({e})") from e
            if "image" not in row or "materials" not in row:
                raise ValueError(f"{path}:{lineno}: needs 'image' and 'materials'")
            if not isinstance(row["materials"], list):
                raise ValueError(f"{path}:{lineno}: 'materials' must be a list")
            records.append({
                "image": row["image"],
                "materials": list(row["materials"]),
                "coverage": dict(row.get("coverage") or {}),
            })
    if not records:
        raise ValueError(f"{path}: no records")
    return records


def predictions_of(dets):
    """pipeline output -> {material: confidence}."""
    return {d["material"]: float(d["confidence"]) for d in dets}


def score(records, predictions, cut=0.0):
    """Per-material precision / recall / F1 at one confidence cut.

    ``predictions[i]`` is ``{material: confidence}`` for ``records[i]``. A hit
    below ``cut`` counts as absent, which is what a raise of the threshold
    does to the pipeline.
    """
    stats = {}

    def row(material):
        return stats.setdefault(
            material, {"tp": 0, "fp": 0, "fn": 0, "support": 0, "predicted": 0})

    for record, pred in zip(records, predictions):
        truth = set(record["materials"])
        hits = {m for m, c in pred.items() if c >= cut}

        for material in hits:
            r = row(material)
            r["predicted"] += 1
            if material in truth:
                r["tp"] += 1
            else:
                r["fp"] += 1
        for material in truth:
            r = row(material)
            r["support"] += 1
            if material not in hits:
                r["fn"] += 1

    for material, r in stats.items():
        tp, fp, fn = r["tp"], r["fp"], r["fn"]
        r["precision"] = round(tp / (tp + fp), 3) if tp + fp else 0.0
        r["recall"] = round(tp / (tp + fn), 3) if tp + fn else 0.0
        p, rec = r["precision"], r["recall"]
        r["f1"] = round(2 * p * rec / (p + rec), 3) if p + rec else 0.0

    return stats


def macro_f1(stats):
    if not stats:
        return 0.0
    return round(sum(r["f1"] for r in stats.values()) / len(stats), 3)


def sweep_cut(records, candidates):
    """Best confidence cut per material.

    ``candidates[i]`` is the raw ``(material, confidence)`` list the models
    produced for ``records[i]`` before the post-CLIP filtering — read from the
    pipeline's own debug blob, so the sweep costs no extra inference. Returns
    ``{material: {"cut": ..., "f1": ...}}`` for materials that appear in truth.
    """
    truth_materials = sorted({m for r in records for m in r["materials"]})
    out = {}

    for material in truth_materials:
        best_cut, best_f1 = None, -1.0
        for cut in SWEEP:
            tp = fp = fn = 0
            for record, raw in zip(records, candidates):
                seen = any(m == material and c >= cut for m, c in raw)
                truth = material in record["materials"]
                if seen and truth:
                    tp += 1
                elif seen and not truth:
                    fp += 1
                elif truth:
                    fn += 1
            p = tp / (tp + fp) if tp + fp else 0.0
            rec = tp / (tp + fn) if tp + fn else 0.0
            f1 = 2 * p * rec / (p + rec) if p + rec else 0.0
            # prefer the higher cut on a tie: same F1, fewer false positives
            if f1 > best_f1 or (f1 == best_f1 and cut > (best_cut or 0)):
                best_cut, best_f1 = cut, f1
        out[material] = {"cut": best_cut, "f1": round(best_f1, 3)}
    return out


def quantity_error(records, dets_by_image):
    """Mean absolute error of measured coverage, for lines that carry it."""
    errors = []
    for record, dets in zip(records, dets_by_image):
        for material, expected in record["coverage"].items():
            hit = next((d for d in dets if d["material"] == material), None)
            measured = float(hit.get("coverage", 0.0)) if hit else 0.0
            errors.append(abs(measured - float(expected)))
    if not errors:
        return None
    return round(sum(errors) / len(errors), 4)


def run(manifest, out=None, min_recall=None, limit=None):
    # imported here so --help and the pure scoring functions work without the
    # model stack installed
    from app.ai import vision

    records = load_manifest(manifest)
    if limit:
        records = records[:limit]

    predictions, candidates, dets_by_image, failed = [], [], [], []
    for record in records:
        path = record["image"]
        if not os.path.isabs(path):
            path = os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), path)
        try:
            with open(path, "rb") as fh:
                dets, _model, _others, _site, _verif = vision.detect_materials(fh.read())
        except OSError as e:
            failed.append(f"{record['image']}: {e}")
            continue

        predictions.append(predictions_of(dets))
        dets_by_image.append(dets)
        debug = getattr(vision, "_last_debug", {}) or {}
        raw = [(h["material"], h["conf"])
               for key in ("world_raw", "coco_raw") for h in debug.get(key, [])]
        candidates.append(raw)

    kept = records[:len(predictions)]
    stats = score(kept, predictions)
    report = {
        "images": len(kept),
        "failed": failed,
        "per_material": stats,
        "macro_f1": macro_f1(stats),
        "quantity_mae": quantity_error(kept, dets_by_image),
        "suggested_cuts": sweep_cut(kept, candidates) if any(candidates) else {},
    }

    print(f"images: {len(kept)}   macro F1: {report['macro_f1']}")
    if report["quantity_mae"] is not None:
        print(f"coverage MAE: {report['quantity_mae']}")
    print(f"{'material':<12}{'P':>7}{'R':>7}{'F1':>7}{'n':>6}{'cut':>7}")
    for material, r in sorted(stats.items()):
        cut = report["suggested_cuts"].get(material, {}).get("cut", "")
        print(f"{material:<12}{r['precision']:>7}{r['recall']:>7}"
              f"{r['f1']:>7}{r['support']:>6}{str(cut):>7}")
    for line in failed:
        print("skipped:", line, file=sys.stderr)

    if out:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
            fh.write("\n")
        print(f"wrote {out}")

    if min_recall is not None:
        weak = {m: r["recall"] for m, r in stats.items() if r["recall"] < min_recall}
        if weak:
            print(f"recall under {min_recall}: {weak}", file=sys.stderr)
            return 1
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="material detector accuracy harness")
    ap.add_argument("--manifest", default="eval/manifest.jsonl")
    ap.add_argument("--out", default=None, help="write the JSON report here")
    ap.add_argument("--min-recall", type=float, default=None,
                    help="exit 1 when any material falls under this recall")
    ap.add_argument("--limit", type=int, default=None, help="first N images only")
    args = ap.parse_args(argv)
    return run(args.manifest, args.out, args.min_recall, args.limit)


if __name__ == "__main__":
    sys.exit(main())
