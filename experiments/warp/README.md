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
experiments/warp/iterate.sh [algorithm]    # render → rasterize (headless Chrome) → measure
```

That one script runs the whole measured loop: `render_sheet.py` →
`sheet.svg` → headless Chrome → `sheet.png` → `measure.py` (table on
stdout, also saved to `measure.txt`). `export_shapes.py` only needs
re-running if the page transform changes. `build_review.py` assembles
`review.html` (the artifact review page) from the outputs.

Automated driving: the `/warp-iterate` skill runs one full iteration
(read this README → implement/tune → `iterate.sh` → log results →
republish the review artifact); `/loop /warp-iterate` keeps it going,
pausing for human taste feedback when it matters.

Iterate: implement an algorithm in `render_sheet.py`'s `ALGORITHMS` dict,
re-run, compare the table + eyeball the sheet. Keep the best per-shape
numbers in this README as you go.

## How to check in / steer

The contact sheet is the review surface and this README is the steering
wheel — no code required to guide the work:

1. **Look at `sheet.svg`** (or the PNG) after any run. Every judgment
   call is visible there on all 19 real shapes at once.
2. **Adjust the bars** in the success-criteria table — e.g. raise
   coverage to 45%, tighten the distortion bound if letters look mushy,
   or add per-shape notes ("Hillside may split its name across the two
   legs of the L", "North Point may abbreviate to NORTH PT").
3. **Annotate the results log** — a row per run keeps the history; add a
   `verdict` note per run (ship it / too distorted / try X).
4. **Rules of taste** belong here too, as bullets the algorithms must
   honor (e.g. "never rotate letters within a word by more than ±20°",
   "prefer fewer, bigger lines over more, smaller ones").

Anything written here is treated as the spec on the next iteration.

## Taste rules (edit freely)

- Reading order must survive: top line first, left to right.
- A stretched letter should still look like the same typeface, not a balloon.
- Lines in a multi-line label may take **different font sizes** — fit each
  line to its own chord instead of sharing the smallest line's size. It
  should still read as one label (keep adjacent-line size ratios modest).
- An earlier (smaller) line may float from the widest line's **start to a
  bit past its center** (~⅓ of the slack) — far right reads as a suffix,
  but don't glue it to the start if there's more room inward, and let it
  **grow to fill** its corner (user notes 2026-07-22: INNER in Inner
  Belt ×2, TEN in Ten Hills).
- No letter may be crushed unreadable at a taper — pull the line inward
  off sharp corners instead (user note 2026-07-22: the T in TEELE).
- Letters stay upright: cap the baseline tilt *within* one glyph (~±11°)
  — the word may ride a wavy baseline, but individual letters must not
  shear into parallelograms (user calls 2026-07-22: T crossbar in TEELE,
  first R in PORTER, the U in Union's SQUARE).
- Hillside: try breaking the word — HILL and SIDE as two separate, very
  close words (user suggestion 2026-07-22); escalate to FFD if that's
  not enough.

## Results log

| Date | Algorithm | Median coverage | Max spill | Notes |
|---|---|---|---|---|
| 2026-07-22 | baseline (`fitted_hero`) | 12.8% | 37.8% (North Point) | clean baselines, no warping. Known issues: `min_size` floor overflows tiny slivers (North Point/Twin City/Porter); single-axis layout leaves bent shapes (Hillside, Ball Square's south lobe) mostly empty. |
| 2026-07-22 | perline (per-line font sizes, user-suggested) | 16.1% | 28.1% (North Point) | +3.3pt median; Porter/Twin City spill → 0. Taste flags: Twin City visually reads "CITY TWIN" and Inner Belt order ambiguous (steep axis + size inversion breaks reading order); EAST/SOMERVILLE size ratio extreme (~3:1); Hillside still 5.5% (needs bent-shape handling). User verdict: fix reading order; no ratio cap needed; proceed to envelope stretch. |
| 2026-07-22 | perline + reading-order fix | 14.0% | 28.1% (North Point) | small early lines start-align over the widest line: Twin City reads TWIN/CITY, Inner Belt in order — but INNER collapses in its corner (−1.9pt median). |
| 2026-07-22 | envelope (glyph outlines, per-glyph vertical stretch) | 18.9% | 4.7% (Boynton Yards) | first outline renderer; sliver spill solved (North Point 17.2%/0.0). Flags: adjacent-glyph height jumps read ransom-note (SPRING/WINTER/UNION); interline band collapses line 2 under a tiny line 1 (Inner Belt 5.4%); spill at slanted boundaries — center-ray misses glyph corners (Boynton). Next: smooth the envelope across glyphs, widen the band, sample edge rays. |
| 2026-07-22 | envelope v2 (continuous warp: shared advance-edge samples, piecewise-linear inside glyphs; wider interline band) | 25.0% | 3.2% (Boynton Yards) | ransom-note jumps gone; letter tops flow with the shape. Remaining: partitions scored before geometric shrink, so Inner Belt (9.7%)/Ten Hills (12.6%) keep collapsed layouts; straight baselines leave bellies empty below and spill where the baseline exits the polygon (Boynton). Next lever: two-sided envelope — per-glyph baseline follows the lower boundary. |
| 2026-07-22 | envelope v3 (two-sided: bottoms follow the lower boundary; post-shrink partition re-scoring; shared interline splits; pairwise row-collision shrink; floating early lines) | 35.0% | 3.4% (Spring Hill) | **coverage bar met** (median 35.0% ≥ 35%). Inner Belt 30.8%, Ten Hills 35.7%, Twin City 32.3% (single line, lovely). Open: spill bar missed in 8 cells (worst 3.4%, glyphs poke slanted boundaries between samples); Porter Square's stacked lines read tangled on the steep diagonal even though rows don't touch — likely wants a single line or abbreviation; Hillside (19.6%) still the bent-shape holdout. |
| 2026-07-22 | envelope v4 (dense samples, margin 3, asymmetric taper-window fit, growth pass, floating past center) | 32.0% | 0.6% (Porter Square) | **spill bar effectively met** (18/19 ≤ 0.2%); Ten Hills untangled; INNER fills its corner. Costs: taper trims gave back coverage (Ball Square 23.1%, −3pt median vs v3) — bars now trade against each other. TEELE's T still wedge-crushed (room check permits 50% one-sided compression); Hillside tail still mush (bent shape needs FFD); Porter still stacks on the steep sliver. Next: within-glyph envelope-slope cap for glyph coherence; revisit trim thresholds to win coverage back. |
