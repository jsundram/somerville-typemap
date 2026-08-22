# /// script
# requires-python = ">=3.11"
# dependencies = ["pya5>=0.9", "h3>=4", "shapely>=2", "numpy"]
# ///
"""Rebin H3-binned population (Kontur Population) into A5 pentagon cells.

Kontur Population ships as H3 res-8 hexagons ("400m") carrying a `population`
count.  A5 (a5geo.org) is a pentagonal DGGS whose cells are *exactly* equal
area within a resolution level.  The two grids are incongruent -- no A5 cell
is a union of H3 cells -- so rebinning is areal interpolation, not
relabelling.  Three strategies, measured against a fixture:

  area      polygon overlay: split each hexagon's population across the A5
            cells it touches, proportional to intersection area.  Conserves
            population exactly (pycnophylactic); assumes population is
            uniform inside a source hexagon.
  subsample push H3 children (res+K) into the A5 cell containing each child
            centre.  No polygon clipping; approaches `area` as K grows.
  centroid  dump each hexagon into the A5 cell containing its centre.  Only
            defensible when the target cells are far larger than the source.

Usage:
  uv run experiments/a5_rebin/rebin.py --demo                 # accuracy fixture
  uv run experiments/a5_rebin/rebin.py --selftest             # overlay vs Monte Carlo
  uv run experiments/a5_rebin/rebin.py --csv kontur.csv --res 13 --out a5.csv

Input CSV needs columns `h3` (res-8 index) and `population`.  From the Kontur
GeoPackage:  ogr2ogr -f CSV kontur.csv kontur_population.gpkg -select h3,population

Two A5 traps this script works around (see README):
  * polygon_to_cells() returns a compacted, MIXED-resolution covering;
  * the cell hierarchy is index-level only -- a cell's children do not tile
    the parent's own boundary (~58% overlap), so parent/child relations must
    not be used for area bookkeeping or for sampling a cell.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import sys
import time
from collections import defaultdict
from functools import lru_cache

import a5
import h3
from shapely.geometry import Point, Polygon

# A5 res 13 = 0.5067 km^2, the closest level to H3 res 8 (0.7373 km^2 mean).
DEFAULT_RES = 13
COVERAGE_TOL = 1e-3  # fraction of a source hexagon allowed to escape the candidates


def hex_polygon(h3_index: str) -> Polygon:
    return Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(h3_index)])


@lru_cache(maxsize=1 << 20)
def a5_polygon(cell: int) -> Polygon:
    """Cached: cell_to_boundary costs ~140us and neighbouring hexes reuse cells."""
    return Polygon(a5.cell_to_boundary(cell))


def candidates(poly: Polygon, res: int) -> list[int]:
    """A5 cells at `res` that could overlap `poly`.

    Seeded only from lonlat_to_cell() and grid_disk(), the two operations that
    agree with cell_to_boundary(); polygon_to_cells() would need uncompacting,
    and uncompacting moves the covered region (broken hierarchy).  Grow rings
    until the candidates cover the polygon.  Planar lon/lat areas are fine
    here: across one 400m hexagon the lon/lat -> metric map is affine, so
    ratios of areas -- all this function needs -- are preserved.
    """
    ring = list(poly.exterior.coords)
    cells = {a5.lonlat_to_cell(v, res) for v in ring}
    cells.add(a5.lonlat_to_cell(poly.representative_point().coords[0], res))

    for _ in range(5):
        if sum(poly.intersection(a5_polygon(c)).area for c in cells) >= poly.area * (
            1 - COVERAGE_TOL
        ):
            break
        grown = {n for c in cells for n in a5.grid_disk(c, 1)} | cells
        cells = {c for c in grown if a5.get_resolution(c) == res}
    return sorted(cells)


def rebin_area(rows, res: int) -> dict[int, float]:
    out: dict[int, float] = defaultdict(float)
    for h3_index, pop in rows:
        poly = hex_polygon(h3_index)
        parts = [(c, poly.intersection(a5_polygon(c)).area) for c in candidates(poly, res)]
        total = sum(a for _, a in parts)
        if total <= 0:  # degenerate hexagon; fall back to the containing cell
            out[a5.lonlat_to_cell(poly.representative_point().coords[0], res)] += pop
            continue
        for cell, area in parts:
            if area > 0:
                out[cell] += pop * area / total
    return dict(out)


def rebin_subsample(rows, res: int, k: int = 3) -> dict[int, float]:
    out: dict[int, float] = defaultdict(float)
    for h3_index, pop in rows:
        children = h3.cell_to_children(h3_index, h3.get_resolution(h3_index) + k)
        share = pop / len(children)
        for child in children:
            lat, lng = h3.cell_to_latlng(child)
            out[a5.lonlat_to_cell((lng, lat), res)] += share
    return dict(out)


def rebin_centroid(rows, res: int) -> dict[int, float]:
    out: dict[int, float] = defaultdict(float)
    for h3_index, pop in rows:
        lat, lng = h3.cell_to_latlng(h3_index)
        out[a5.lonlat_to_cell((lng, lat), res)] += pop
    return dict(out)


METHODS = {"area": rebin_area, "subsample": rebin_subsample, "centroid": rebin_centroid}


# --------------------------------------------------------------------------
# fixture: a known continuous density field, binned onto H3 and onto A5
# independently, so the rebinning error can be read off against ground truth
# --------------------------------------------------------------------------

SOMERVILLE = (-71.135, 42.372, -71.072, 42.418)  # w, s, e, n


def true_density(lng: float, lat: float) -> float:
    """People per km^2: a Somerville-ish field, two dense cores over a base."""
    v = 2000.0
    for blng, blat, sigma in [(-71.122, 42.396, 0.010), (-71.088, 42.381, 0.006)]:
        d2 = ((lng - blng) * math.cos(math.radians(blat))) ** 2 + (lat - blat) ** 2
        v += 9000.0 * math.exp(-d2 / (2 * sigma**2))
    return v * (1 + 0.25 * math.sin((lng + 71.1) * 100))


def lattice(poly: Polygon, target: int = 400) -> list[tuple[float, float]]:
    """Regular grid of points inside `poly` -- an unbiased sampler.

    Cell hierarchies are useless for this: H3 children leak ~6% outside their
    parent and A5 children ~42%, both enough to bias a mean density.
    """
    minx, miny, maxx, maxy = poly.bounds
    n = max(8, int(math.sqrt(target * (maxx - minx) * (maxy - miny) / poly.area)))
    pts = [
        (minx + (i + 0.5) * (maxx - minx) / n, miny + (j + 0.5) * (maxy - miny) / n)
        for i in range(n)
        for j in range(n)
    ]
    return [p for p in pts if poly.contains(Point(p))]


def integrate(poly: Polygon, area_km2: float) -> float:
    """Mean density over the polygon x the cell's true area.

    The area comes from the grid library, never from the lon/lat polygon: a
    straight-edge polygon under-measures its cell by ~0.5% at 0.5 km2 and ~8%
    at 8 km2, which would swamp the rebinning error being measured.
    """
    pts = lattice(poly)
    return sum(true_density(lng, lat) for lng, lat in pts) / len(pts) * area_km2


def demo(res: int, k: int) -> int:
    w, s, e, n = SOMERVILLE
    bbox = Polygon([(w, s), (e, s), (e, n), (w, n)])
    cell_km2 = a5.cell_area(res) / 1e6

    # source hexes cover a margin beyond the bbox so every scored A5 cell sees
    # a complete neighbourhood of source data; the margin grows with the
    # target cell, which can stick well outside the bbox
    pad = 0.02 + 2.5 * math.sqrt(cell_km2 / math.pi) / 80.0
    grown = Polygon([(w - pad, s - pad), (e + pad, s - pad),
                     (e + pad, n + pad), (w - pad, n + pad)])

    # source: H3 res-8 "Kontur-like" hexagons, each integrating the true field
    src = [(cell, integrate(hex_polygon(cell), h3.cell_area(cell, "km^2")))
           for cell in h3.polygon_to_cells(
               h3.LatLngPoly([(lat, lng) for lng, lat in grown.exterior.coords]), 8)]
    src_total = sum(p for _, p in src)
    print(f"source: {len(src)} H3 res-8 cells, population {src_total:,.0f}")

    # ground truth: the same field integrated directly onto A5 cells.  The
    # target cell set comes from lonlat_to_cell over a lattice, not from
    # polygon_to_cells, to stay on the consistent half of the A5 API.
    scored = {a5.lonlat_to_cell(p, res) for p in lattice(bbox, 4000)}
    truth = {c: integrate(a5_polygon(c), cell_km2) for c in scored}
    print(f"target: {len(truth)} A5 res-{res} cells, {cell_km2:.4f} km2 each "
          f"(exactly equal area)\n")

    print(f"{'method':<12}{'cells':>7}{'sum':>13}{'mass err':>10}"
          f"{'mean |err|':>12}{'max |err|':>11}{'time':>9}")
    for name, fn in METHODS.items():
        t0 = time.perf_counter()
        got = fn(src, res, k) if name == "subsample" else fn(src, res)
        dt = time.perf_counter() - t0
        mass = sum(got.values())
        errs = [abs(got.get(c, 0.0) - v) / v for c, v in truth.items() if v > 0]
        print(f"{name:<12}{len(got):>7}{mass:>13,.0f}"
              f"{(mass - src_total) / src_total:>10.2e}"
              f"{sum(errs) / len(errs):>11.1%}{max(errs):>11.1%}"
              f"{dt / len(src) * 1e3:>7.1f}ms")
    print("\n('time' is per source hexagon; 'err' is per A5 cell, against the "
          "field\nintegrated directly onto that cell)")
    return 0


def selftest(res: int) -> int:
    """Check the polygon overlay against Monte Carlo sampling of one hexagon."""
    random.seed(7)
    worst = 0.0
    for lat, lng in [(42.39, -71.10), (0.5, 10.2), (-33.9, 151.2), (64.1, -21.9)]:
        cell = h3.latlng_to_cell(lat, lng, 8)
        poly = hex_polygon(cell)
        minx, miny, maxx, maxy = poly.bounds
        mc: dict[int, float] = defaultdict(float)
        n, hits = 20000, 0
        while hits < n:
            p = (random.uniform(minx, maxx), random.uniform(miny, maxy))
            if poly.contains(Point(p)):
                mc[a5.lonlat_to_cell(p, res)] += 1 / n
                hits += 1
        overlay = rebin_area([(cell, 1.0)], res)
        l1 = sum(abs(overlay.get(c, 0.0) - mc.get(c, 0.0)) for c in set(mc) | set(overlay))
        worst = max(worst, l1)
        print(f"  ({lat:>6}, {lng:>7})  {len(mc)} cells  L1 vs Monte Carlo {l1:.4f}")
    print(f"worst L1 {worst:.4f} (Monte Carlo noise at n=20000 is ~0.01)")
    return 0 if worst < 0.05 else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", help="input CSV with columns h3,population")
    ap.add_argument("--out", help="output CSV: a5,population,density_per_km2")
    ap.add_argument("--res", type=int, default=DEFAULT_RES, help="A5 resolution")
    ap.add_argument("--method", choices=METHODS, default="area")
    ap.add_argument("-k", type=int, default=3, help="child levels for --method subsample")
    ap.add_argument("--demo", action="store_true", help="run the accuracy fixture")
    ap.add_argument("--selftest", action="store_true",
                    help="check the overlay against Monte Carlo sampling")
    args = ap.parse_args()

    if args.selftest:
        return selftest(args.res)
    if args.demo or not args.csv:
        return demo(args.res, args.k)

    with open(args.csv, newline="") as fh:
        rows = [(r["h3"], float(r["population"])) for r in csv.DictReader(fh)]
    fn = METHODS[args.method]
    t0 = time.perf_counter()
    binned = fn(rows, args.res, args.k) if args.method == "subsample" else fn(rows, args.res)
    dt = time.perf_counter() - t0
    km2 = a5.cell_area(args.res) / 1e6
    print(f"{len(rows):,} hexes -> {len(binned):,} A5 res-{args.res} cells in "
          f"{dt:.1f}s ({len(rows) / dt:,.0f} hex/s); population "
          f"{sum(p for _, p in rows):,.0f} -> {sum(binned.values()):,.0f}",
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
