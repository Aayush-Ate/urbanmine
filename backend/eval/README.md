# Accuracy harness

Measures the material detector on labeled photos and derives the confidence
cuts in `WORLD_CONF_BY_MATERIAL` from the results.

## Why

Every threshold in `app/core/catalog.py` is currently a hand-picked number.
Precision and recall cannot be improved by reading the code — they have to be
measured. 100–200 labeled photos is enough to see which materials the pipeline
is guessing at.

## Label

Copy the example and fill it in:

```sh
cd backend
cp eval/manifest.example.jsonl eval/manifest.jsonl
```

One photo per line:

```json
{"image": "uploads/0b3bbb7267.jpg", "materials": ["Bricks"], "coverage": {"Bricks": 0.35}}
```

- `materials` — what a human sees. `[]` means no salvage material (bedroom,
  desk, empty yard); any prediction there is a false positive.
- `coverage` — optional, your estimate of the frame fraction. Only used for
  the quantity-error column.

Aim for a spread: at least ~15 photos per material you care about, and 20+
negatives (bedrooms, desks, street scenes) because the CLIP gate and the
household drop are what produce most false positives.

## Run

```sh
cd backend
python -m eval.harness --manifest eval/manifest.jsonl --out eval/report.json
```

Output is a per-material table:

```
images: 120   macro F1: 0.71
coverage MAE: 0.081
material          P      R     F1     n    cut
Bricks        0.880  0.733  0.800    15   0.35
Metal         0.615  0.800  0.696    20   0.28
```

`cut` is the confidence threshold with the best F1 for that material, swept
over the raw model hits. Paste the ones that make sense into
`WORLD_CONF_BY_MATERIAL` — a cut below `WORLD_CONF` is fine and intended; the
pass already runs at the lowest floor.

## Use it as a gate

```sh
python -m eval.harness --manifest eval/manifest.jsonl --min-recall 0.8
```

Exits 1 when any material falls under the floor, so it can run in CI once the
manifest exists.

## Limits

- Image-level presence, not box IoU. It answers "did the pipeline find the
  brick pile", not "was the box tight". Tight-box scoring needs box labels and
  is a separate step.
- The sweep uses pre-CLIP hits, so it is guidance. The CLIP gate and the
  household drop can still remove a hit above the suggested cut.
- Accuracy of the report is the accuracy of the labels. Two people labeling the
  same photo differently is the usual source of noise at this size.
