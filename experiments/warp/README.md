# Warped hero glyphs — sub-problem

**Goal.** Reproduce the rainbow-map lettering: each neighborhood name
*maximally, artisanally crammed* into its polygon, letters individually
warped/scaled so the ink fills the shape — not just the biggest clean
baselines that fit (the current `fitted_hero`, which is the baseline here).

## Framing

Input: one polygon (page coordinates) + one name.
Output: SVG elements (eventually `<path>` glyph outlines, not `<text>`)
whose ink stays inside the polygon and covers as much of it as possible
while staying legible.

## Candidate algorithms (in rough order of ambition)

1. **Per-line envelope stretch** — keep `fitted_hero`'s line layout, but
   convert glyphs to outlines (fontTools `TTFont.getGlyphSet()` →
   `pens.svgPathPen`) and scale each glyph vertically to the polygon's
   local height at its x-position (letters grow into the belly, shrink at
   tapers). Cheap, already very "rainbow".
2. **Quad-strip FFD** — fit a strip of quads between the polygon's upper
   and lower edges along the medial axis; bilinear-warp the whole word's
   outlines through it. Handles bent polygons (Hillside, Porter sliver).
3. **Greedy letter packing** — place letters one at a time, each scaled
   (bounded aspect distortion) to the largest empty rectangle adjacent to
   the previous letter; words may bend mid-run. Closest to hand-lettering,
   hardest to keep readable.

## Success criteria

Measured by `measure.py` on a rendered contact sheet of all 19 real
neighborhood shapes (spill/coverage are ink-pixel ratios):

| Metric | Bar |
|---|---|
| Spill (ink outside polygon / total ink) | ≤ 0.5% |
| Coverage (inked share of polygon area) | ≥ 35% (baseline ≈ see below; rainbow original eyeballs ≈ 50%) |
| Legibility | manual: letters in reading order, per-glyph x/y scale ratio within [0.4, 2.5], no glyph collisions |
| Determinism / runtime | same input → same output; < 5 s for all 19 |

## The loop

```sh
uv run experiments/warp/export_shapes.py   # real hood polygons → shapes.json
uv run experiments/warp/render_sheet.py baseline   # → sheet.svg + sheet_layout.json
# rasterize (headless chrome or a browser) → sheet.png
uv run experiments/warp/measure.py sheet.png       # per-hood coverage/spill table
```

Iterate: implement an algorithm in `render_sheet.py`'s `ALGORITHMS` dict,
re-run, compare the table + eyeball the sheet. Keep the best per-shape
numbers in this README as you go.

## Results log

| Date | Algorithm | Median coverage | Max spill | Notes |
|---|---|---|---|---|
| 2026-07-22 | baseline (`fitted_hero`) | 12.8% | 37.8% (North Point) | clean baselines, no warping. Known issues: `min_size` floor overflows tiny slivers (North Point/Twin City/Porter); single-axis layout leaves bent shapes (Hillside, Ball Square's south lobe) mostly empty. |
