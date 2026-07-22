# Boundary-annotation alignment — iteration loop

**Goal.** Every border annotation (the colored feature stroke + label in
L8) should track its administrative line (L7) tightly, span the full
extent it truly demarcates, and never appear where it doesn't belong.

## The loop

```sh
uv run render_map.py                      # emits out/borders_debug.json as a side effect
uv run experiments/borders/measure.py     # metrics table + worst offenders
uv run experiments/borders/sheet.py       # closeup SVG of the N worst runs → sheet.svg
```

`out/borders_debug.json` records every annotated run: the border pair
("Davis Square | Teele Square"), classification kind + name, run/stroke
lengths, and sampled mean/max deviation between annotation and border.

## Metrics & bars

| Metric | Bar |
|---|---|
| mean deviation, street/path/water strokes | ≤ 8 px |
| mean deviation, rail strokes | ≤ 25 px (corridors are wide) |
| max deviation, any accepted stroke | ≤ 45 px street / 60 px rail |
| annotated coverage (non-"nothing" length / total border length) | ≥ 70% — but never by faking: an annotation must be real |
| stray annotations (stroke where no border sits within slack) | 0 |

The renderer's acceptance thresholds live in `render_map.py`
(`draw_run`: `mean_cap`, `slack`, kept-ratio) — tune them against these
numbers, then eyeball `sheet.py`'s closeups before shipping.

## Results log

| Date | Change | Coverage | Worst mean dev (street) | Notes |
|---|---|---|---|---|
| 2026-07-22 | baseline measurement | 68% | 11.2px (Mystic Ave) | rail avg 6.0px but Inner Belt\|city-limit Fitchburg at 26.7 mean / 60 max — the "stray toward Community College" |
| 2026-07-22 | rail mean_cap 30→18 | 67% | 11.2px (Mystic Ave) | stray rejected; surviving rail runs avg 1.8px; Fitchburg reads Union Sq → Community College via real borders. Residual ⚠s (Mystic Ave 11.2, McGrath 10.6) are dual-carriageway centerline offsets — the border runs between the carriageways; arguably correct as drawn. |
