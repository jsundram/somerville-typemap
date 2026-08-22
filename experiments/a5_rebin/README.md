# Rebinning Kontur population (H3) into A5 pentagons

**Question:** can the [Kontur Population
dataset](https://data.humdata.org/dataset/kontur-population-dataset) — global
population on 400 m H3 hexagons — be rebinned onto [A5](https://a5geo.org)
pentagon cells?

**Answer: yes, and it is ordinary areal interpolation.** No A5 cell is a union
of H3 cells, so this is not a relabelling: each hexagon's population has to be
split across the pentagons it overlaps. Done as a polygon overlay it conserves
population exactly and lands within a few percent per cell. `rebin.py` does it;
`hierarchy_check.py` documents the A5 API traps that make a naive version wrong.

## Resolution mapping

Kontur ships H3 res 8 ("400 m", mean 0.7373 km²), plus 3 km (res 6) and 22 km
(res 4) aggregates. A5 levels are *exactly* equal area — that is the appeal
here: population density is `population / cell_area(res)` with a constant
divisor, no cos(lat) or per-cell area column.

| A5 res | cell area | vs Kontur 400 m | note |
|-------:|----------:|----------------:|------|
| 11 | 8.1073 km² | 11 hexes/cell | strong aggregation |
| 12 | 2.0268 km² | 2.75 hexes/cell | good default for city-scale maps |
| 13 | 0.5067 km² | 0.69 hexes/cell | closest match to the source grid |
| 14 | 0.1267 km² | 0.17 hexes/cell | finer than the data; interpolation only |
| 10 | 32.429 km² | ≈ H3 res 6 (36.13 km²) | matches the 3 km product |
| 7 | 2075.5 km² | ≈ H3 res 4 (1770 km²) | matches the 22 km product |

## Methods and what they cost

`rebin.py` implements three, all conserving total population to float precision:

- **`area`** — clip each hexagon against the A5 cells it touches and split its
  population by intersection area. Assumes uniform density inside a source
  hexagon, which is the only assumption the source data supports.
- **`subsample`** — push H3 children (res+3, 343 per hexagon) into the A5 cell
  containing each child centre. No polygon clipping; matches `area` to ~0.1 pp
  and is ~5× slower in Python, but it is the shape that ports to SQL.
- **`centroid`** — whole hexagon to the cell containing its centre. Cheap and,
  at these resolutions, wrong (see below).

Measured against a fixture — a known continuous density field integrated onto
H3 res 8 as "source", and integrated directly onto A5 cells as ground truth
(`uv run experiments/a5_rebin/rebin.py --demo --res N`):

| target | `area` mean / max err | `subsample` | `centroid` |
|--------|----------------------|-------------|------------|
| A5 res 11 | 1.7% / 3.7% | 1.7% / 3.7% | 4.0% / 8.0% |
| A5 res 12 | 3.1% / 8.8% | 3.2% / 9.0% | 22% / 63% |
| A5 res 13 | 5.2% / 21% | 5.2% / 21% | 74% / 200% |
| A5 res 14 | 8.0% / 44% | 8.1% / 40% | 170% / 766% |

Read it as: aggregating upward is nearly lossless; rebinning to a cell the size
of the source hexagon costs ~5% typical and ~20% worst-cell, which is the price
of not knowing how population is arranged *inside* a 400 m hexagon; going finer
buys resolution the data does not contain. Centroid binning is only tolerable
at res 11 and below — at res 13 it leaves 39% of the cells empty and
overshoots another 30% by more than 1.5x.

`--selftest` checks the overlay against Monte Carlo sampling of single hexagons
at four latitudes: worst L1 0.018 (Monte Carlo noise at n=20 000 is ~0.01).

## Scale

Pure-Python `pya5`: ~230 hexagons/s single core for the overlay (measured on a
541-hexagon Boston extract, `--res 13`, boundary geometry cached), i.e. ~1.2
CPU-hours per million hexagons. Somerville is ~14 hexagons; Massachusetts
~37 000 (≈3 min); the global 400 m file is 6.6 GB, so for anything
country-scale or larger use the [DuckDB A5
extension](https://duckdb.org/community_extensions/extensions/a5) or the Rust
crate rather than this script — the work is embarrassingly parallel by tile.

## Can the rebinning error be avoided by going upstream?

Kontur is a derived product: it starts from GHSL, blends in Meta/CIESIN HRSL
where available, and uses Microsoft Building Footprints, Copernicus land cover
and OSM to redistribute and to mask out false positives (quarries, wide roads).
So the 400 m hexagons are already a *binning choice*, and binning the upstream
data straight into A5 would skip one hop. `source_grid.py` measures what that
hop costs: the same fixture field, integrated onto each candidate source grid,
rebinned onto A5, scored against the field integrated directly onto A5 cells.

| source grid | source cell | A5 res 12 | A5 res 13 | A5 res 14 |
|---|---|---|---|---|
| H3 res 8 (Kontur) | 0.737 km² | 3.4% / 8.8% | 5.2% / 21% | 8.0% / 44% |
| raster 860 m (same area as the hexagon) | 0.740 km² | 1.7% / 6.5% | 5.1% / 19% | 8.2% / 43% |
| raster 100 m (GHS-POP) | 0.01 km² | 0.6% / 1.1% | 0.6% / 0.9% | 0.6% / 0.9% |
| raster 30 m (HRSL) | 0.0009 km² | 0.6% / 1.1% | 0.6% / 1.0% | 0.6% / 0.8% |

mean / max per-cell error. 0.6% is the fixture's own quadrature noise — 100 m
and 30 m are indistinguishable from each other and from exact.

Three things fall out:

- **The penalty is a function of source-cell size over target-cell size, not of
  shape.** 860 m squares and Kontur's hexagons — same area, different tiling —
  score the same to within a fraction of a point. Nothing about pentagons vs
  hexagons is the problem; the source bin being comparable to the target bin is.
- **A 100 m source erases the penalty.** Once source cells are ~50x smaller
  than the target, "which pentagon does this belong to" has an unambiguous
  answer for all but a sliver of the input, and the interpolation assumption
  stops mattering. Going finer than 100 m buys nothing *for this*.
- **Below the source resolution nothing helps.** A5 res 14 (0.127 km²) is
  smaller than a Kontur hexagon; from Kontur the values there are invented, and
  no method fixes that. Only a finer source makes res 14 meaningful.

### But is it more accurate, and is the data there?

Resampling loss is only one error term, and the smaller one. Kontur's own
allocation error at 400 m — how much of a hexagon's population sits where the
model says — is far larger than 5%, and going upstream trades a known 5% for
whatever the upstream product's error is, *minus the corrections Kontur applied*
(the OSM masks and building-footprint redistribution are the value Kontur adds
over raw GHS-POP). So "bin the original data" is more accurate only if you
either keep those corrections or pick a source that does not need them.

What is actually available:

| source | resolution | availability |
|---|---|---|
| GHS-POP R2023A (JRC/Copernicus) | 100 m Mollweide (also 3″/30″ WGS84) | open, global, current — the practical upstream choice |
| Meta/CIESIN HRSL | 30 m, ~160 countries | on HDX/AWS, but **not updated since 2024** |
| Microsoft Global ML Building Footprints | vector, ~1.4 B buildings, some heights | ODbL, global |
| OSM buildings / landuse | vector | ODbL |
| **US Census 2020 P.L. blocks** | block polygons, **enumerated counts** | open (TIGER/Line + P.L. 94-171) |

For anywhere in the US — Somerville included — the last row is the answer. A
census block here is a fraction of an A5 res-13 cell, and it carries a counted
population rather than a modelled one; GHS-POP's US layer is itself a
disaggregation of that census data, and Kontur is a re-binning of GHS-POP. So
going Kontur -> A5 for a Somerville map is a round trip through two models to
get back a worse version of a number that is published directly. Blocks -> A5
by area weight (optionally dasymetric onto building footprints, which is where
Microsoft/OSM buildings earn their keep) is both simpler and strictly better.

Globally, or in countries without an open block-level census, GHS-POP 100 m ->
A5 is the upstream path that pays: it removes the resampling penalty entirely,
at the cost of Kontur's corrections. Kontur -> A5 remains the right call when
you want those corrections and the target is res 12 or coarser, where the
penalty is ~3%.

## Census blocks for a whole state (blocks.py)

For Massachusetts — or any US state — 2020 census blocks are the better input,
and `blocks.py` bins any polygon layer with a population column into A5:

```sh
curl -O https://www2.census.gov/geo/tiger/TIGER2020PL/LAYER/TABBLOCK20/2020/tl_2020_25_tabblock20.zip
uv run experiments/a5_rebin/blocks.py tl_2020_25_tabblock20.zip --pop-field POP20 --audit
uv run experiments/a5_rebin/blocks.py tl_2020_25_tabblock20.zip --pop-field POP20 \
    --res 13 --out ma_a5.csv
```

`tabblock20` already carries `POP20`, `HOUSING20` and `ALAND20`, so no join to
the P.L. 94-171 tables is needed. Measured throughput on the polygon path is
~500 polygons/s, so a statewide run is minutes, not hours.

Why blocks beat Kontur here: the counts are enumerated rather than modelled,
and in built-up areas a block is one or two city blocks — far smaller than an
A5 res-13 cell — so the interpolation penalty that costs 5.2% from Kontur
drops to the noise floor (the 100 m row in the table above). Kontur's US
numbers are a re-binning of GHS-POP, which is itself a disaggregation of this
same census data; going to Kontur for a US map is a round trip through two
models.

Three caveats, all of which matter more the further west you go in MA:

- **Rural blocks are big.** In the Berkshires a block can span square
  kilometres — larger than a res-13 cell — and its people cluster along a road
  while the block covers forest. Straight areal weighting smears them. `--audit`
  reports exactly what share of the state's population sits in blocks larger
  than the target cell; `--weights <buildings>` fixes it by splitting each
  block's count across the building footprints inside it first (MassGIS
  structures, or Microsoft/OSM footprints) before the A5 overlay. That is
  strictly better than either raw source.
- **Differential privacy.** 2020 block counts carry injected noise from the
  TopDown algorithm — a few people either way per block, occasionally
  nonsensical (population in a water block). Aggregating into 0.5 km² cells
  averages most of it out; at res 14, or in sparse rural cells, it is visible.
- **Vintage and group quarters.** Blocks are April 2020; Kontur refreshes more
  often. And dorms/prisons are counted where they stand, which is correct but
  produces spikes (Tufts) that modelled surfaces smooth away.

Use `ALAND20` rather than the polygon area when reporting density if you care
about waterfront cells; drop zero-population blocks first (most of the file).

Not yet run against the real TIGER file — this sandbox has no route to
`www2.census.gov` — so the pipeline is exercised against synthetic polygon
layers in both areal and dasymetric modes (population conserved exactly in
both).

## A5 API traps (measured, `hierarchy_check.py`)

With `pya5` 0.9.0, reproduced with `a5-js` 0.9.0:

1. **`polygon_to_cells()` returns a compacted, mixed-resolution covering.**
   Asking for res 13 over a Somerville-sized box returns 27 cells at res 12 *and*
   13. Treating them as one resolution triple-counts area (a res-12 pentagon
   covers its four res-13 children).
2. **The hierarchy is index arithmetic, not geometry.** For a random point,
   `cell_to_parent(lonlat_to_cell(p, r+k), r) == lonlat_to_cell(p, r)` only
   ~65% of the time, at every resolution and for k = 1, 2, 3. A cell's children
   have the same total area as the cell but their union overlaps the cell's own
   `cell_to_boundary` polygon by just 58%.
3. **`grid_disk(c, k>=2)` can leak a coarser cell into the ring.** `k=1` was
   clean in testing.

`lonlat_to_cell`, `cell_to_boundary`, `cell_area` and `grid_disk(c, 1)` are
mutually consistent — a point is inside its own cell's polygon 100% of the time,
at every resolution tested — so `rebin.py` builds candidate sets only from
those, and grows rings until the candidates provably cover the source hexagon.
Trap 2 also means you cannot sample a cell by averaging over its children
(that is what made the first version of the fixture report 23% error), and that
`compact`/`uncompact` should not be used for area bookkeeping. Worth filing
upstream; until then, treat the hierarchy as unusable for areal work.

## Running it

```sh
uv run experiments/a5_rebin/rebin.py --demo --res 13     # accuracy fixture
uv run experiments/a5_rebin/source_grid.py               # source-grid comparison
uv run experiments/a5_rebin/rebin.py --selftest          # overlay vs Monte Carlo
uv run experiments/a5_rebin/hierarchy_check.py           # the API probe

# real data: Kontur ships GeoPackage; the script wants h3,population
ogr2ogr -f CSV kontur.csv kontur_population_20231101.gpkg -select h3,population
uv run experiments/a5_rebin/rebin.py --csv kontur.csv --res 13 --out a5.csv
```

Output is `a5,population,density_per_km2` with `a5` as the 16-hex-digit cell id
(`a5.hex_to_u64` to get the integer back). Kontur's geometry is EPSG:3857 —
reproject to EPSG:4326 before indexing if you read the geometry rather than the
`h3` column. The fixture uses a synthetic density field, not Kontur's numbers:
the sandbox this was developed in cannot reach `data.humdata.org`, so the
pipeline is verified against ground truth it can compute, and the CSV path is
what runs against the real file.

Kontur Population is CC-BY 4.0; A5 is Apache-2.0.
