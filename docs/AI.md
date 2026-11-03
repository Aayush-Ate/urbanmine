# Which model, and why

The original build used four local passes because there was no labelled
demolition dataset to train on. That was right for a first October, and wrong as
a place to stop: the stack weighs ~2GB, needs 2GB of RAM, takes 30–60s on a cold
start, and still cannot count a pile or read condition.

This note records the alternatives, what was picked, and how to change it again.

## The candidates

| Option | What it is good at | What it costs | Verdict here |
|---|---|---|---|
| **YOLO-World** (what was there) | Real-time open-vocabulary boxes from text prompts; no training data | 16 prompts → noisy labels; misses piles; no quantity or condition | Keep as the keyless fallback |
| **YOLOv8n** (what was there) | Fast COCO objects | Has no brick, tile or rebar class; maps a bed to Wood | Kept only for everyday-object context |
| **CLIP** (what was there) | Cheap "is this construction?" gate | Binary, per crop, no counting | Kept in the fallback path; the gate is what killed the bedsheet listings |
| **OWLv2** | Strong zero-shot boxes; a 2026 comparison in *Multimedia Tools and Applications* put it top on their detection and grounding sets | Heavier than YOLO-World, slower; still no quantity/condition | Good drop-in detector upgrade, does not fix the real gap |
| **Grounding DINO** | Best zero-shot *precision* of the open-vocabulary detectors; phrase grounding | Slowest of the detectors; ~2GB with torch anyway | Better boxes, same 2GB deploy problem |
| **Florence-2 / DINO-X class VLMs** | Detection + caption + OCR in one small model | Needs torch and a GPU for comfort; quantity is still not its answer | Interesting, not a size win |
| **YOLOE** | Prompt-driven *and* prompt-free, YOLO speed, small | Needs the same torch runtime; no condition judgement | The right choice **if** the local stack stays |
| **RF-DETR, fine-tuned** | Best accuracy per the 2026 Roboflow guide, once you have labelled data | YOLO-World prompts stop being enough; needs labels and a training loop | The eventual answer, not this review's |
| **Hosted multimodal model (Gemini Flash class)** | One call returns materials, quantities, condition and "is this a site"; no torch, no weights, no GPU | A key, a network call, a few cents per thousand photos | **Chosen as the default path** |

Sources: Roboflow's *Best Computer Vision Models in 2026* (July 2026), a 2026
cross-paradigm benchmark in *Sensors* (MDPI) covering YOLO-World, Grounding DINO,
OWL-ViT and OWLv2, and a 2026 *Multimedia Tools and Applications* comparison that
found OWLv2 strongest of the four on their data. The honest read of those
benchmarks is that no single open-vocabulary detector wins everywhere — and none
of them answers "how many bricks is that", which is the question this product
actually asks.

## What is running now

`app/ai/vlm.py` is a second provider behind the same `detect_materials(bytes)`
signature. It is used when a key exists:

```bash
# backend/.env (gitignored) — either name works
VLM_API_KEY="…"            # or GEMINI_API_KEY
VLM_MODEL="gemini-2.5-flash"
# VLM_TIMEOUT_S=30
# AI_PROVIDER=local        # force the old local stack, e.g. an offline demo
```

`/api/health` now reports `"ai": "vlm:<model>"` or `"ai": "local"`, so a demo can
say which one answered. `analysis` responses return the same fields either way.

What the hosted call is asked for, and what is enforced on the reply:

| The model returns | What the backend does with it |
|---|---|
| Any material name | Matched against the 16 in `catalog.py`, plus a small alias map ("timber" → Wood); anything else is dropped |
| A quantity | Clamped to that material's "whole frame" ceiling in `FULL_QTY`; zero or negative is dropped |
| Condition | Must be Excellent/Good/Fair/Poor, else Good; the price is recomputed from `CONDITION_PRICE`, not trusted from the model |
| A bbox | Must be four numbers inside 0–1 with a real area, else no box (an absent box means the UI shows the whole frame) |
| "This is not a site" | `is_construction_site: false` and no detections, so nothing can be published |

A timeout, a 500, or prose instead of JSON returns `None`, and the local passes
run. A network blip costs seconds; it never becomes "no materials found".

## Why this is the better answer for *this* product

1. **It answers the question being asked.** The UI needs a material, a quantity,
   a condition and a price. A detector gives a box and a label; the model gives
   the other three.
2. **It deletes the deploy problem.** No torch, no transformers, no 150MB of
   weights, no 2GB RAM. The backend drops into a normal serverless function,
   which is what the "keep the deploy light" requirement needed.
3. **It is cheaper to change.** A prompt tweak replaces a retraining loop, until
   there is real labelled data to train on.
4. **The failure mode is already handled.** The local stack is still there, so a
   missing key or a dead network degrades instead of breaking.

## What it costs, plainly

- **A network dependency on the analyze path.** First photo now waits on an HTTP
  round trip (~1–3 s) instead of a local inference.
- **A key in the backend.** It is read from the environment, sent as a header
  (never a query string, so it stays out of access logs), and never reaches the
  browser. Rotate it in one place.
- **Non-determinism.** Temperature is 0 and the JSON is validated, but the same
  photo can still produce 1,150 bricks one day and 1,200 the next. The contractor
  confirms before anything is published, which is the real mitigation.
- **Vendor shape.** The request/response format is Gemini-shaped. A second
  provider is a `_ask()` function, not a refactor — `_shape()` is provider-neutral.

## The next step, when there is data

`backend/uploads/` (or the BYTEA rows) is a growing pile of real site photos. The
move after this review is to label a few hundred of them and fine-tune a small
detector (RF-DETR or YOLOE), then use the hosted model only as the referee that
checks the fine-tuned boxes. That path is written down here so the next person
does not re-derive it: **labels first, training second, prompts third.**
