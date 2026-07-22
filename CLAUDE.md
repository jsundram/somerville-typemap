# somerville-typemap — working notes for Claude

Typographic map of Somerville, MA: print-oriented SVG where every feature
is text (Axis Maps area fills + rainbow-map crammed hero labels). See
README.md for the vision and data sources.

## Commands

```sh
uv run render_fixture.py          # engine smoke test → out/fixture.svg
uv run fetch_neighborhoods.py     # city polygons (rarely needed; cached)
uv run fetch_osm.py               # OSM refetch (rarely needed; cached)
uv run fetch_boundaries.py        # municipal boundaries (rarely needed)
uv run render_map.py              # THE build → out/layers/*.svg, out/somerville.svg,
                                  #             out/borders_debug.json
uv run build_viewer.py            # → out/viewer.html (layer toggles, pan/zoom)
```

All scripts use PEP 723 inline deps; run with `uv run`. The OSM cache is
committed, so `render_map.py` works offline from a fresh clone — only run
fetchers when data must actually refresh (they cache-on-success, exit 0
on failure; overpass-api.de often 504s → .fr mirror fallback is automatic).

Preview renders: headless Chrome screenshots, e.g.
`"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new
--screenshot=out.png --window-size=W,H --hide-scrollbars file://...`.
The user's review artifact (claude.ai) is rebuilt by copying out/viewer.html
over the previously-published scratchpad file and republishing the same path.

## Architecture

- `typemap/svgdoc.py` — SVG builder; text-on-path; `id_prefix` keeps ids
  unique when layer docs are combined (`write_combined`).
- `typemap/fills.py` — the engine: `linepack_fill` (rows clipped to
  polygon), `contour_fill` (text on inward-buffered rings, upright-run
  splitting), `street_label`, `fitted_hero` (crammed multi-line heroes,
  geometric containment).
- `typemap/osm.py` — Overpass JSON → layered shapely geometries. Streets
  merged per name; unnamed water inherits waterway-centerline names;
  culverted streams excluded; route relations carry the Community Path.
- `typemap/borders.py` — border classification: `shared_borders`,
  `classify` (two-tier: qualify-ratio then kind priority), `split_chunks`.
- `render_map.py` — assembly. Layers: L1 basemap (only drawn layer),
  L2 neighborhoods, L3 transit, L4 adjacent towns, L5 heroes,
  L6 roads/parks/water typography, L7 boundary lines, L8 boundary
  annotations. Border pipeline: chunk → classify → smooth/extend/snap →
  substring-trim stroke → mean-deviation acceptance → repeat labels.
- `config/style.py` (palette/fonts/type hierarchy) and `config/words.py`
  (fill words, station lines, TOWNS, PATH_FAMILY, RAIL_RENAME) — the
  user's iterate-here layer; prefer config changes over code changes.

## Ongoing experiments (each has its own README = its spec)

- `experiments/warp/` — crammed hero glyphs. **User-driven** via
  `experiments/warp/iterate.sh` and the `/warp-iterate` skill; check the
  README results log + taste rules before touching. Don't modify their
  algorithms without being asked.
- `experiments/borders/` — boundary-annotation alignment. Loop:
  `uv run render_map.py` → `uv run experiments/borders/measure.py`
  (coverage + worst mean/max deviation) → tune `draw_run` thresholds
  (`mean_cap`, `slack`, kept-ratio) in render_map.py → re-measure.
  `sheet.py` renders closeups of the worst runs.

## Data gotchas (hard-won; don't re-derive)

- Neighborhood polygons: city open data, Public Domain, 2017 vintage,
  Bostonography-crowdsourced then city-adjusted. They don't perfectly
  tile the municipal boundary — render_map absorbs gap slivers into
  adjacent hoods and drops sub-visible spikes (North Point's legal
  sliver toward Charlestown) via morphological opening.
- OSM: roadside cycle tracks are named after their street (only
  PATH_FAMILY renders as path); the Community Path crosses Davis plaza
  as a footway and continues west only as a route relation; Winter
  Brook/Alewife culverted segments must stay excluded or borders go
  blue on land; commuter rail is named by route ("New Hampshire Route"
  = Lowell Line → RAIL_RENAME); GLX shares corridors and is excluded
  from border classification on purpose.
- Dual carriageways (McGrath, Fellsway, Mystic Ave): twin centerlines —
  street labels suppress the twin; border strokes ride one carriageway
  (~11px mean deviation, known + accepted for now).

## Conventions

- Commit at each working milestone on a feature branch; imperative
  subject + explanatory body.
- Screenshots/verification before declaring a visual change done — read
  the rendered image, don't assume.
- The viewer defaults (which layers start visible) live in
  build_viewer.py LAYER_META; keep print_order (render_map) and Z_ORDER
  (build_viewer) in sync when adding layers.
