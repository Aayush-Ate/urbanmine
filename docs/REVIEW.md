---
title: "AI-Powered Construction Material Recovery & Marketplace"
subtitle: "UrbanMine · SDG 12, Responsible Consumption and Production"
date: "Review 1 · 2 November 2026"
---

# The team

| Name | ID |
|---|---|
| Aadhithya Prem | 1BF25CS002 |
| A N Sheshanaga Kishan | 1BF25CS001 |
| Arunavaya Singh | 1BF25CS047 |
| Aaditya Sinha | 1BF25CS007 |
| Aayush Ate | 1BF25CS010 |

**Project:** AI-Powered Construction Material Recovery & Marketplace  
**SDG:** 12, Responsible Consumption and Production

# What it is

A contractor photographs a demolition site. The AI lists what is salvageable, with
quantity, condition and price. One click publishes it. A buyer searches, gets
match-scored, and sends a request.

**Live:** https://fullstackproject-app.vercel.app

React 18 · FastAPI · YOLO-World + YOLOv8n + CLIP · Neon Postgres · Cesium

---

# Problem Identification

**Everything in a building that comes down was paid for once, and most of it goes
to landfill.**

- Buyers pay new-material prices for material that could be salvaged for a fraction of that
- Contractors have no fast way to catalogue what is on site, because measuring, photographing and pricing each pile takes longer than skipping it
- Salvaged material is never listed anywhere, so a buyer cannot search for it

The constraint that shapes the product: cataloguing has to cost one photo, not an
afternoon.

---

# Why SDG 12

**Goal 12: Responsible Consumption and Production.** Two targets carry this project.

**12.2**: By 2030, achieve the sustainable management and efficient use of
natural resources.

**12.5**: By 2030, substantially reduce waste generation through prevention,
reduction, recycling and reuse.

A building's timber, bricks and metal are resources that have already been
extracted. Sending them to landfill means extracting again for the next build,
and the reuse never happens because nobody wrote the stock down.

**What the build does about it**

- One photo replaces the survey that normally ends in "leave it", so salvage gets listed instead of skipped
- Distance is part of the match score, so material travels 20 km rather than 200
- The Impact tab totals material diverted and value recovered, which is the number this goal asks for

---

---

# Problem Identification: scope

**Users**

| User | Goal |
|---|---|
| Demolition contractor | Photograph, confirm, published in under a minute |
| Architect / interior designer | Find reclaimed doors, windows, tiles and marble near the site |
| Scrap dealer | Find bulk metal, rebar and copper by weight and distance |

**In this review's build:** photo AI, listings, smart match, requests, impact, location picker, satellite maps, mobile shell, deployed demo.

**Left out deliberately:** payments, accounts, chat, logistics, multi-city, admin.

---

# System Design: architecture

**Three parts behind one URL.**

```
Browser (React + Vite)
   │  fetch /api/* and /uploads/*
   ▼
Vercel frontend rewrite ───► FastAPI container (Vercel)
   same origin, no CORS           │
                                  ├─ AI: YOLO-World, YOLOv8n, colour, CLIP
                                  └─ Neon Postgres, JSON file fallback
```

The frontend's `vercel.json` rewrites `/api` and `/uploads` to the backend alias,
so the browser only ever talks to one origin and CORS never appears.

The backend ships as a container because torch, ultralytics and transformers will
not fit a normal serverless function.

---

# System Design: data flow

**Upload to listing**

```
photo → EXIF or device GPS → shrink to 1600px → analyse → edit → confirm → listing
```

**Buyer flow**

```
material + quantity + point + condition + radius → ranking → request → accept/decline
```

- Postgres holds listings as one JSONB row and photo bytes as their own rows, so both survive a container restart
- The disk copy is a cache; serving a photo tries disk first, then the database
- Distance is haversine in Python, which agrees with `ST_Distance(geography)/1000`, so rankings would survive a move to PostGIS

---

# System Analysis: why these choices

| Chosen | Instead of | Reason |
|---|---|---|
| Python + FastAPI | MERN / Express | The hard problem is vision, and that is all Python |
| React 18 + Vite | Next.js | Dashboard with no SEO, no router, heavy client media |
| YOLO-World + YOLOv8n + CLIP | A trained model | No labelled demolition dataset exists yet |
| Postgres on Neon | SQLite | The container's disk is discarded and several instances can run at once; SQLite would give each one a different marketplace |
| One JSONB row | Normalised tables | The shape changes weekly; split it when two writers matter |
| Vercel Container Runtime | Plain serverless | ~2GB image with baked weights; a JS lambda cannot carry it |
| CesiumJS satellite | Leaflet | Satellite-first, with a terrain and 3D tiles path |

---

# Technical Implementation: codebase

**One question per file.**

```
backend/
  app/
    main.py           routes only
    schemas.py        request shapes
    core/catalog.py   16 materials: units, salvage prices, prompts, gates
    core/scoring.py   haversine, qty_for, match_score
    ai/vision.py      all model loading and the four passes
    storage/store.py  Postgres or data.json, plus photo bytes
    storage/images.py 1600px copy and 480px thumbnail
  tests/              50 tests, no model downloads
frontend/
  src/App.jsx         shell and five panels
  src/components/     LocationPicker, MeasureModal
  src/lib/            cesium, measureMath
```

---

# Technical Implementation: AI pipeline

Four passes run on each photo, then merge into one ranked list:

1. Downscale to 1280px once; the original is stored untouched
2. **YOLO-World-m** finds the 16 materials from descriptive prompts at confidence 0.12
3. **YOLOv8n** catches everyday objects and maps them (chair becomes Wood, bus becomes Metal)
4. **Colour pass**, numpy only, picks up bulk piles the boxes miss
5. **CLIP** scores weak boxes and the whole frame against a 0.60 gate

Merge, drop household hits, fall back to a labelled guess, normalise shares to 100%.

A bedsheet photo produces no listing. A low-confidence result is labelled a guess.
`?debug=1` returns every stage.

---

# Technical Implementation: quality

- **50 tests**, stdlib `unittest`, models stubbed, under a second with no weights downloaded
- Quantities come from measured coverage through `qty_for`; `random` never touches them
- Match score: material 40, quantity 25, distance 20 (zero past 50 km), condition 15
- The photo ruler uses a known object (brick, tile, sheet) as the scale, because a browser cannot reach LiDAR
- Location is read from the device instead of assumed, and a photo's GPS tag is adopted only within 25 km of where the user is
- Removing a listing takes two taps and cleans up its photos

---

# User Interface: shell

Five panels in one app:

- **Upload** — dropzone or camera, auto-analyse, editable detections, publish
- **Marketplace** — filters, satellite globe with pins, request, remove
- **Smart Match** — ranked rows with score dials
- **Requests** — accept or decline
- **Impact** — four cards showing the maths

Desktop gets a sidebar above 900px; mobile gets a brand bar and bottom tabs.

Concrete and iron palette, flat with no shadows, motion disabled under
`prefers-reduced-motion`, skip link and tab roles, and `alert()` replaced by
inline status regions.

---

# User Interface: location and measuring

**Setting a point takes one of five inputs, none of them typed coordinates:**

- address search (HERE, then Nominatim fallback)
- area presets
- device GPS
- a tap on the globe
- a dragged pin

Every move reverse-geocodes into a human address and labels where the point came
from. Search is biased toward that point rather than clamped to a city. Globes
start where the device is, or show the whole globe if permission is refused.

**On the photo:** set a known object, draw the line, get millimetres. Both ends
drag and the number follows the finger. A custom reference accepts mm, cm or
inch, and a zero reference is refused with a reason instead of producing a
useless scale.

---

# Results

| Check | Result |
|---|---|
| Live frontend | https://fullstackproject-app.vercel.app |
| Backend | Vercel container, region `sin1`, alias verified |
| Database | Neon Postgres, Singapore, `"store": "postgres"` |
| Materials served | 16 |
| Test suite | 50 of 50 passing |
| Demo path | Upload a photo, get priced detections, publish |

---

# Limitations and next steps

**Known now**

- No auth: a request carries a typed name and nothing else
- One JSONB row, so a concurrent write can overwrite another
- CO2 figures are estimates rather than LCA data
- No AR measuring, since a browser cannot reach LiDAR
- A line drawn across an oblique surface reads short, because there is no perspective correction

**Next**

- Real tables and authentication
- Object storage once photo volume grows
- A trained segmentation model once `uploads/` holds labelled site photos

---

# Timeline

| Date | Milestone |
|---|---|
| 27 Sep | Scaffold: React, FastAPI, mocked AI |
| 28 Sep | YOLOv8n, colour pass, Cesium satellite, mobile shell |
| 29 Sep | YOLO-World, CLIP gate, 16 materials, debug flag |
| 30 Sep | Neon Postgres, public MIT repository |
| 2 Oct | Photo ruler for real quantities, salvage pricing |
| 31 Oct | Package restructure, docs consolidated, deployed demo |

---

# Thank you

**Live demo:** https://fullstackproject-app.vercel.app

**Repository:** https://github.com/Aayush-Ate/urbanmine (MIT)

Questions?

<!--
Regenerate from the repo root:
  pandoc docs/REVIEW.md --slide-level=1 -o docs/UrbanMine-Review-2026-11-02.pptx
-->
