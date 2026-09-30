# Hero labels — sub-problem

**Goal (revised 2026-09-29).** Each neighborhood name set as large as it
can go inside its polygon in **undistorted letterforms**, laid out by
*searching* discrete choices (angle, line breaks, abbreviations, curved
baselines) rather than by bending glyphs. Density comes from the typeface
and the layout, not from distortion. The look is **technical**, not
hand-lettered: the map's job is to communicate boundaries locals
recognize, and the type should read like signage/engineering drawings.

Why the change: see `inspo/README.md`. Of five artist maps, only the
rainbow map crams letters, and it is hand-lettered; the rest fit plain
lettering. Seven envelope iterations traded legibility against coverage
(TEELE's T, SQUARE's S, per-glyph de-skew) without converging.

## Framing

Input: one polygon (page coordinates) + one name + its variants.
Output: `<path>` glyph outlines (fontTools → `SVGPathPen`) whose ink stays
inside the polygon, as large as possible, still reading as type.

## Algorithms

`ALGORITHMS` in `render_sheet.py`. Earlier ones stay for comparison.

1. `baseline` — `fitted_hero` as shipped in L5.
2. `perline` — fitted_hero chords, one size per line.
3. `envelope` — per-glyph vertical warp. **Parked at v7 (2026-09-29)**:
   32.8% median / 1.0% worst spill is the number to beat. Queued envelope
   work (quad-strip FFD for Hillside, greedy letter packing) is dropped.
4. `search` — **the new direction.** Enumerate candidates, keep the best:
   - **variant**: the full name plus entries in `config/words.py`
     `HERO_VARIANTS` (abbreviations: BALL SQ, 10 HILLS; hand-authored
     hyphen points: SOMER-VILLE, BRICK-BOTTOM, ASSEM-BLY, POW-DER);
   - **line breaks**: every partition of the variant's words/hyphen
     points into 1–3 lines;
   - **angle**: the polygon's principal axes (min-rotated-rect, both
     directions kept upright), horizontal, plus a coarse sweep (15°);
   - **placement**: each line fit to its own chord (perline logic),
     sized to the largest font where the *actual glyph outlines* fit
     inside the fitting polygon (containment by outline, not bbox);
   - **region split** (Hillside, Porter, Ball Sq) as one more candidate
     type, carrying the existing FLIPS / size-ratio rules;
   - **curved baseline** (phase 6): text on a smoothed centerline for
     long, narrow shapes, sized to the narrowest width along the way.

   Score: smallest line's cap height first, then coverage; small
   penalties for more lines, abbreviations, hyphens, and steep angles.
   Optional mild per-line x-stretch in [0.85, 1.2] (phase 4) — the only
   distortion allowed.

## Typeface direction (phase 4)

Technical, signage/engineering register, heavy weights available, open
license (OFL) so it can ship in print and be committed as TTF for
fontTools. Candidates to compare on the same sheet against today's Arial
Rounded Bold:

| Face | Why |
|---|---|
| Overpass (Heavy/Black) | open Highway Gothic — US road-sign lettering, i.e. the names locals read at intersections |
| Barlow / Barlow Condensed | road-sign/license-plate grotesk; wide weight + width range |
| Big Shoulders Display | Chicago wayfinding signage; condensed, packs tight |
| IBM Plex Sans Condensed | engineering-drawing tone; pairs with Plex Mono for annotations |

The pick should pair with (or replace) `BODY_FONT` in `config/style.py`
so heroes, streets and border annotations read as one system.

## Fitting geometry (phase 5)

Fit against a smoothed polygon (morphological opening removes notches
and spikes); spill is still measured against the true polygon.

## Success criteria

Measured by `measure.py` on a rendered contact sheet of all 19 real
neighborhood shapes (spill/coverage are ink-pixel ratios):

| Metric | Bar |
|---|---|
| Spill (ink outside polygon / total ink) | ≤ 0.5% (expect ~0 by construction) |
| Min cap height (smallest line on the sheet) | report it; higher is better — the new legibility number |
| Coverage (inked share of polygon area) | report; envelope v7 = 32.8% median. Expect a dip before typeface/stretch win it back |
| Legibility | manual: reading order, no glyph collisions, letters undistorted (x-stretch only, within [0.85, 1.2]) |
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

(2026-09-29: rules marked *[envelope]* only bind the parked envelope
algorithm — `search` doesn't bend glyphs, so they're moot there. All
other rules carry over.)

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
- *[envelope]* Letters stay upright: cap the baseline tilt *within* one glyph (~±11°)
  — the word may ride a wavy baseline, but individual letters must not
  shear into parallelograms (user calls 2026-07-22: T crossbar in TEELE,
  first R in PORTER, the U in Union's SQUARE).
- Hillside: try breaking the word — HILL and SIDE as two separate, very
  close words (user suggestion 2026-07-22); escalate to FFD if that's
  not enough.
- Region-split words must read as one label: flow the same reading
  direction (HILL rotated 180° to match SIDE — user 2026-07-22) and keep
  the font-size ratio between words ≤ ~2.2 (user: PORTER vs SQUARE
  contrast too big).
- *[envelope]* A word must not visually break into lines: cap baseline steps between
  adjacent letters (user 2026-07-22: the S in BALL SQUARE's SQUARE
  detached onto "its own line").

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
| 2026-07-22 | envelope v5 (glyph coherence 1.6×, per-glyph de-skew ±11°, retuned trims, gray borders + #333 ink, HILL/SIDE break) | 31.4% | 0.6% (Porter Square) | de-skew works — TWIN CITY/DAVIS/UNION letters upright (user calls addressed for R, U). Misses: TEELE's T now *vanishes* (coherence cap shrank it to its worst sample; T:E height ratio ~1:4 — needs a word-level height-gradient cap + room-aware line placement); HILL/SIDE both landed tangled in Hillside's upper leg, lower rectangle empty — region assignment (FFD) is the real fix, approved and queued. |
| 2026-07-22 | envelope v6 (word-level height cap ≤1.5×, relative taper floor w/ sliver guard, lobe region-split for Hillside/Ball Sq/Porter Sq, disjoint regions, growth cap ×1.1, borders #888/4px) | 31.2% | 1.0% (Ball Sq, Hillside) | taste sweep: TEELE's T fully readable; Porter finally clean (PORTER in the tip, SQUARE down the sliver); Hillside 31.0% with HILL/SIDE in its two legs; North Point sliver-guard restored (31.7%); letters upright everywhere. Worst cell now Brickbottom 22.8%. Coverage vs bars: median 31.2% is honest ink (no collisions/spill inflating it); next coverage levers: Brickbottom/Duck Village/East Somerville single-axis conservatism. |
| 2026-07-22 | envelope v7 (HILL true-180° rotation, word baseline-step cap ±0.25s two-way, stretch bound 2.5→3.0, region size-ratio ≤2.2) | 32.8% | 1.0% (Ball Square) | all four user notes fixed: HILL flows with SIDE (upright glyphs — first attempt mirrored them, both axes must flip); SQUARE's S reattached; Brickbottom bigger (27.4%, was 22.8); PORTER:SQUARE ratio moderated. Worst cell 25.5%. |
| 2026-09-29 | search v0 (undistorted outlines, HERO_VARIANTS + SQ rule + hyphen breaks, long axis only; score = total ink) | 16.8% | 0.0% | spill 0 by construction (cap-band boxes inside a 3px-inset polygon). Min cap 15px. Ink scoring rewards one giant short line: SQ dwarfs ASSEMBLY and TEELE, MA- dwarfs GOUN SQUARE. |
| 2026-09-29 | search v0.1 (score = smallest line's size × (1−penalty), ink as tiebreak; line size ratio ≤ 2×) | 15.7% | 0.0% | min cap 15→21.5px, median 46px; every label reads as one label. Geometry alone picked **ASS- / EMBLY SQ** (the joke: user to decide — force or forbid). Open for phase 3: Twin City reads CITY TWIN (stack on a tilted axis puts line 2 left-low); Hillside (4.6%), North Point, Porter (5.0%) need region split / angle sweep; Brickbottom settles on one small line; coverage leaves big empty areas beside the stack. |
| 2026-09-29 | search v0.2 / phase 3a (per-line placement: binary-searched common size, earliest-fit packing, then spread + grow ≤2× per line; angle sweep: min-rect axis, 3 longest edges, horizontal, 15° steps; tilt penalty 0.06·|sin θ|; raster frame with free-run counts so band queries are numpy ops) | 18.8% | 0.2% (Ball Sq) | min cap 21.5→23.6px, **median cap 46→60px**; runtime still ~4 s. User notes addressed: DUCK / VILLAGE spread apart and both larger; BRICK- / BOTTOM runs along the long straight side (41→56px); TEELE / SQ 43→75px. Twin City now reads TWIN / CITY. Spill 0.2%: the Q's tail descends below the cap band — needs outline-level containment. Still weak: Hillside (8.9%), North Point (7.9%) → region split / sliver handling; Winter Hill looks undersized for its box — investigate. |
| 2026-09-29 | search v0.3 (size trade-offs: lines may drop to 0.8× so siblings grow; score = √(smallest size × √ink); a SQ/SQUARE-only line never exceeds the name line) | 18.8% | 0.2% (Ball Sq) | User note "BALL could be bigger": per-line sizes were already allowed, but max-min scoring equalized them; with trades Winter Hill (HILL 84→109), Boynton (YARDS grows), Duck Village improve. **BALL itself is width-bound** — at every angle its 4 wide letters already span the upper area (~131–137 even with SQ shrunk); taller needs a condensed face or the x-squeeze → phase 4. Trades briefly let DAVIS / giant SQ back in → suffix cap. North Point now NORTH … POINT split far apart (21px) — needs sliver handling. |
| 2026-09-29 | search phase 3b (top-4 layouts refined against real glyph outlines: shrink what pokes out, then grow + nudge ±8% while inside and clear; stacked lines keep full leading between cap bands; cohesion: gap ≤ 1 cap, ≥40% horizontal overlap; lobe split with per-lobe angles, hyphen dropped, split penalty 0.10) | 20.5% | 0.0% | **spill 0 everywhere** (Q tail fixed by outline check); median cap 58→62px; Ball 23→27.5% (user: "BALL could be bigger" — box was over-conservative: side bearings + empty L corner). North Point stays together (NORTH / PT). First outline pass let SQUARE slot between PORTER's letters at 0.12 cap leading → refine now keeps the packing's 0.30. Hillside: best split HILL 47 / SIDE 92 loses to one diagonal HILLSIDE at 61 under legibility-first scoring — user call whether to force the split. Winter Hill still leaves its lower-right empty (undiagnosed). |
| 2026-09-30 | **phase 4 typeface comparison** (search 3b, same sheet; OFL fonts in `fonts/`, static heavy instances cut from the variable fonts; `WARP_FONT=<path> iterate.sh search`; per-font tables in `compare/`) | see below | 0.0% all | Arial Rounded Bold 20.5% / min cap med 62px · Overpass Black 23.5% / 60 · IBM Plex Sans Condensed Bold 23.9% / 67 · Big Shoulders Display Black 30.2% / **86** · Barlow Condensed ExtraBold 31.5% / 77 · **Barlow Condensed Black 34.9% / 76 — beats envelope v7 (32.8%) with undistorted glyphs.** Condensed faces win exactly where the width-bound cells were (BALL, Brickbottom, Magoun). Union now keeps UNION / SQUARE unabbreviated; Ten Hills picks 10 / HILLS. Hillside still one diagonal line. |
| 2026-09-30 | search 3b + **Barlow Condensed ExtraBold** (user pick over Black) + ink-based suffix cap + presence term (score × span^0.25) + lobe splits opt-in (config HERO_SPLITS) | 31.9% | 0.0% | median min cap 76.9px. TEELE / SQ: SQ was pinned at TEELE's size by the suffix rule; now SQ may carry up to the name line's *ink* (size × width) — SQ grows, DAVIS / giant SQ still blocked. North Point: with splits open to every shape it scattered NORTH … PT to opposite tips, hence opt-in. Its stacked NORTH / PT in the fat corner remains: the best straight single line (NORTH POINT, 31px) spans only 32% of the sliver — a straight baseline can't run along it at a readable size → curved baseline (phase 6) or an outside label with a leader. Davis now vertical (DAVIS / SQ at ~90°) — tilt penalty 0.06 may be too weak; watch. |
| 2026-09-30 | **phase 6 curved baselines** (spine = tree diameter of the Voronoi medial axis, Chaikin + moving-average smoothed, evenly resampled; binary-searched size where a window has clearance ≥ ½ cap and radius ≥ 3 caps under the whole word, total turn ≤ 35°; glyph angle = chord across its width; exact outline check; single-line candidates for shapes ≥ 3× long/wide, penalty 0.06; config HERO_CURVES forces) | 31.9% | 0.0% | First pass pinched letters on the inside of bends (HI LL, TW N, PORTEЯ) — the medial axis wiggles with every boundary notch and per-sample tangents are noisy; fixed by smoothing + chord angles + a *local* radius limit (a total-turn cap wasn't enough). Curves now read cleanly (Brickbottom, Twin City, Hillside, Porter, North Point) but come out smaller than the refined straight layouts, so none wins on score; they're available per name via HERO_CURVES. North Point curved = NORTH POINT along the sliver at ~26px vs NORTH / PT stacked in the corner at 46px — user's call. |
| 2026-09-30 | **curved frames** (SpineFrame: t along the spine, v across it — the whole straight search runs on curves: stacked lines, placement, trades, outline refinement; 3 spines per shape at ±24/60/120px smoothing, extended 30% past each end; bend limit *local* per column, radius ≥ 4 caps; letters spaced along mid-height; each spine tried both directions and rows kept only if they read forward where they sit; neighboring letters must not touch) + North Point split over 2- and 3-lobe decompositions, NORTH PT variant dropped (user: "NORTH in the middle lobe, POINT in the last") | 31.9% | 0.0% | User: curves.png labels hadn't reached their potential. Causes: one line only, centered on one spine, and a *global* bend limit from the spine's tightest wiggle pinned every label (all hit it exactly). Local limit: Brickbottom 51→104, Twin City 65→116 — but baseline spacing let BR/TW collide (tops pinch by cap/R, not cap/2R) and Hillside's text came out upside down (spine's overall direction ≠ local) → mid-line spacing, radius 4 caps, both directions + local reading check, letter-gap check. Clean curves: Brickbottom 87, Porter 74, Hillside 68 — still smaller than refined straight layouts, so none wins on score (forceable via HERO_CURVES). **North Point: NORTH … POINT, one per lobe** (19.2%→17.9%, min cap 28.6). Preview of forced curves: `compare/curves.png`. |
| 2026-09-30 | **swell** (per-letter *uniform* sizes from the clearance where each letter sits, centered on the line; neighbors ≤ 12% apart, word ≤ 1.5× — envelope's anti-ransom-note rules; single lines on the main straight axes + spines; penalty 0.04; config HERO_SWELL forces). `curve_compare.py` now shows curved / swell / straight rows | 31.9% | 0.0% | User asked whether per-letter sizing is "too close to warping": no — letterforms stay intact (envelope stretched them), but envelope v1's ransom-note failure mode comes back without gradient caps. Forced swell: **Twin City 77→116** (fills the shape far better than straight 98 or curved 67), **Hillside 58→87** growing into its lower leg, Porter 67→84, North Point one continuous NORTH POINT 28→35; Brickbottom 86 uniform — its word is length-bound (spans the spine end to end), not width-bound. Nothing wins by default: the score leads with the smallest letter, so swell's small end loses to uniform straight sizes. Taste call per name via HERO_SWELL. |
| 2026-09-30 | **roomiest route + word breaks at bends** (route option weighting skeleton edges by length × (clearance/max)²; smoothing ±120 dropped — user; `bend_regions` cuts the shape across the raw route at every ≥30° bend (measured over ±30 px) and words go in adjacent pieces; reading order for splits now judged on the page (next word right of / below); config HERO_BENDS forces; curve_compare adds a construction overlay of the roomy route + bend cuts and a "bends" row) | 31.9% | 0.0% | Roomy route coincides with the longest route in all five thin shapes (their long paths already run through the wide parts) — kept for shapes with thin tails off a wide body. Bends: **Twin City TWIN (94, up the diagonal arm) / CITY (136, in the lobe)** — user's idea; Hillside HILL / SIDE 80/84 one per bend; Porter PORTER / SQUARE **wins by default** (20.4→25.0%); Brickbottom BRICK / BOTTOM 57/126; North Point NORTH / POINT. Two bugs on the way: pieces ordered along a right→left route + forward-only pairs put TWIN in the wrong piece; reading order along the first word's axis rejected TWIN (diagonal) → CITY (right). Runtime now ~11 s for the sheet (budget 5 s) — needs a pass. |
