# /// script
# requires-python = ">=3.11"
# dependencies = ["pya5>=0.9", "h3>=4", "shapely>=2", "geopandas>=1", "pyogrio", "numpy"]
# ///
"""Bin a polygon population layer (e.g. US census blocks) into A5 cells.

The companion to rebin.py: same areal interpolation, but the source is
arbitrary polygons carrying a count rather than H3 hexagons.  For anywhere in
the US this is the better input -- 2020 census blocks carry an enumerated
population, and in built-up areas a block is far smaller than an A5 res-13
cell, so the interpolation assumption barely bites (see README).

  # Massachusetts, straight areal weighting.  tabblock20 already carries
  # POP20 / ALAND20, so no join to the P.L. tables is needed.
  curl -O https://www2.census.gov/geo/tiger/TIGER2020PL/LAYER/TABBLOCK20/2020/tl_2020_25_tabblock20.zip
  uv run experiments/a5_rebin/blocks.py tl_2020_25_tabblock20.zip \
      --pop-field POP20 --res 13 --out ma_a5.csv

  # dasymetric: push each block's count onto buildings first, so rural blocks
  # do not smear people across forest
  uv run experiments/a5_rebin/blocks.py tl_2020_25_tabblock20.zip \
      --pop-field POP20 --weights ma_buildings.gpkg --res 13 --out ma_a5.csv

--weights takes any polygon layer (MassGIS structures, Microsoft/OSM
footprints); each block's population is split across the weight polygons it
contains, proportional to their area, before the A5 overlay.  Blocks holding
no weight polygon fall back to plain areal weighting.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import a5
import geopandas as gpd

sys.path.insert(0, str(Path(__file__).parent))
from rebin import bin_polygons  # noqa: E402


def load(path: str, layer: str | None) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path, layer=layer) if layer else gpd.read_file(path)
    return gdf.to_crs(4326) if gdf.crs and gdf.crs.to_epsg() != 4326 else gdf


def dasymetric(blocks: gpd.GeoDataFrame, pop_field: str, weights: gpd.GeoDataFrame):
    """Split each block's population across the weight polygons inside it.

    Uses an equal-area projection for the weights so that a big building
    counts for more than a small one regardless of latitude.
    """
    joined = gpd.sjoin(weights.to_crs(6933), blocks.to_crs(6933)[[pop_field, "geometry"]],
                       how="inner", predicate="intersects")
    joined["w"] = joined.area
    share = joined.groupby("index_right")["w"].transform("sum")
    joined["pop"] = joined[pop_field] * joined["w"] / share
    placed = set(joined["index_right"])
    out = [(geom, pop) for geom, pop in
           zip(joined.to_crs(4326).geometry, joined["pop"]) if pop > 0]
    leftover = blocks.loc[~blocks.index.isin(placed)]
    out += [(geom, pop) for geom, pop in zip(leftover.geometry, leftover[pop_field])
            if pop > 0]
    print(f"dasymetric: {len(placed):,} blocks onto {len(joined):,} weight polygons, "
          f"{len(leftover):,} blocks fell back to areal weighting", file=sys.stderr)
    return out


def audit(blocks: gpd.GeoDataFrame, pop_field: str, res: int) -> int:
    """Is this layer actually finer than the target cells, and where is it not?

    Areal interpolation is near-free while source polygons are much smaller
    than the target cell, and degrades once they are comparable (rebin.py's
    table).  For census blocks that split is geographic: city blocks are tiny,
    rural blocks can span kilometres, so this reports the share of people
    sitting in blocks too big for the chosen resolution -- the share that
    would benefit from --weights.
    """
    cell_km2 = a5.cell_area(res) / 1e6
    areas = blocks.to_crs(6933).area / 1e6
    pop = blocks[pop_field].astype(float)
    print(f"{len(blocks):,} blocks, {pop.sum():,.0f} people; A5 res-{res} cell = "
          f"{cell_km2:.4f} km2")
    print(f"block area km2: median {areas.median():.4f}  mean {areas.mean():.4f}  "
          f"p95 {areas.quantile(0.95):.4f}  max {areas.max():.2f}")
    for mult in (0.25, 1.0, 4.0):
        big = areas > cell_km2 * mult
        print(f"  blocks larger than {mult:>4.2f}x the cell: {big.sum():>7,} "
              f"({big.mean():>5.1%} of blocks, {pop[big].sum() / pop.sum():>5.1%} "
              f"of population)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="polygon layer: shapefile / GeoPackage / GeoJSON")
    ap.add_argument("--layer", help="layer name, for multi-layer sources")
    ap.add_argument("--pop-field", default="POP20", help="population column")
    ap.add_argument("--weights", help="polygon layer to redistribute within blocks")
    ap.add_argument("--weights-layer")
    ap.add_argument("--res", type=int, default=13, help="A5 resolution")
    ap.add_argument("--out", help="output CSV (default stdout)")
    ap.add_argument("--audit", action="store_true",
                    help="report block sizes against the target cell and exit")
    args = ap.parse_args()

    blocks = load(args.source, args.layer)
    blocks = blocks[blocks[args.pop_field].fillna(0) > 0]
    if args.audit:
        return audit(blocks, args.pop_field, args.res)

    cells = (dasymetric(blocks, args.pop_field, load(args.weights, args.weights_layer))
             if args.weights
             else [(g, p) for g, p in zip(blocks.geometry, blocks[args.pop_field])])

    t0 = time.perf_counter()
    binned = bin_polygons(cells, args.res)
    dt = time.perf_counter() - t0
    km2 = a5.cell_area(args.res) / 1e6
    total = sum(p for _, p in cells)
    print(f"{len(cells):,} source polygons ({total:,.0f} people) -> {len(binned):,} "
          f"A5 res-{args.res} cells in {dt:.1f}s; binned total {sum(binned.values()):,.0f}",
          file=sys.stderr)

    out = open(args.out, "w", newline="") if args.out else sys.stdout
    writer = csv.writer(out)
    writer.writerow(["a5", "population", "density_per_km2"])
    for cell, pop in sorted(binned.items()):
        writer.writerow([a5.u64_to_hex(cell), f"{pop:.6f}", f"{pop / km2:.6f}"])
    if args.out:
        out.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
