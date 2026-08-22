# /// script
# requires-python = ">=3.11"
# dependencies = ["pya5>=0.9", "h3>=4", "shapely>=2", "numpy"]
# ///
"""How much of the rebinning error comes from Kontur's 400 m hexagons?

`rebin.py` measures the cost of going Kontur(H3 res 8) -> A5.  This asks the
follow-up: if instead of Kontur we binned the *upstream* sources into A5
directly -- GHS-POP at 100 m, HRSL at 30 m -- how much of that error goes
away?

Same fixture as rebin.py: a known continuous density field.  It is integrated
onto each candidate source grid (H3 res-8 hexagons, or square raster pixels of
a given size), then rebinned onto A5, then compared against the field
integrated directly onto the same A5 cells.  Everything else is held fixed, so
the only variable is how finely the source carved up the world.

Run:  uv run experiments/a5_rebin/source_grid.py
"""

from __future__ import annotations

import math
import sys
from collections import defaultdict
from pathlib import Path

import a5
import h3
from shapely.geometry import Polygon

sys.path.insert(0, str(Path(__file__).parent))
from rebin import (  # noqa: E402
    SOMERVILLE, a5_polygon, candidates, hex_polygon, integrate, lattice, rebin_area,
    true_density,
)

# Kontur's "400 m" is the H3 res-8 edge length; the cell is 0.737 km2, so the
# fair square comparison is 860 m, not 400 m.
SOURCES = [
    ("H3 res 8 (Kontur)", None),
    ("raster 860m (= hex area)", 860.0),
    ("raster 100m (GHS-POP)", 100.0),
    ("raster 30m (HRSL)", 30.0),
]


def raster_cells(bbox: Polygon, metres: float):
    """Square pixels covering `bbox`, as (polygon, area_km2) in lon/lat.

    Equirectangular pixels sized at the bbox centre latitude -- the fixture
    only needs pixels that tile the area, not a real projection.
    """
    minx, miny, maxx, maxy = bbox.bounds
    lat0 = (miny + maxy) / 2
    dlat = metres / 110_570.0
    dlon = metres / (111_320.0 * math.cos(math.radians(lat0)))
    km2 = (metres / 1000.0) ** 2
    ny = int(math.ceil((maxy - miny) / dlat))
    nx = int(math.ceil((maxx - minx) / dlon))
    for j in range(ny):
        for i in range(nx):
            x, y = minx + i * dlon, miny + j * dlat
            yield Polygon([(x, y), (x + dlon, y), (x + dlon, y + dlat), (x, y + dlat)]), km2


def bin_polygons(cells, res: int) -> dict[int, float]:
    """Area-weighted push of (polygon, population) into A5 cells.

    Fast path: when a pixel's corners and centre all index to the same A5
    cell, the pixel is wholly inside it -- true for ~95% of 30 m pixels
    against a 0.5 km2 cell -- so only the stragglers get clipped.
    """
    out: dict[int, float] = defaultdict(float)
    for poly, pop in cells:
        pts = list(poly.exterior.coords)[:4] + [poly.centroid.coords[0]]
        indexed = {a5.lonlat_to_cell(p, res) for p in pts}
        if len(indexed) == 1:
            out[indexed.pop()] += pop
            continue
        parts = [(c, poly.intersection(a5_polygon(c)).area) for c in candidates(poly, res)]
        total = sum(a for _, a in parts)
        for cell, area in parts:
            if area > 0:
                out[cell] += pop * area / total
    return dict(out)


def build_source(bbox: Polygon, metres: float | None):
    """(source cells with population, count) for one candidate upstream grid."""
    if metres is None:
        cells = h3.polygon_to_cells(
            h3.LatLngPoly([(lat, lng) for lng, lat in bbox.exterior.coords]), 8)
        return [(cell, integrate(hex_polygon(cell), h3.cell_area(cell, "km^2")))
                for cell in cells], len(cells)
    # a raster pixel is small enough that one central sample is its integral:
    # 30-400 m against a field whose structure is ~1 km
    pixels = [(poly, true_density(*poly.centroid.coords[0]) * km2)
              for poly, km2 in raster_cells(bbox, metres)]
    return pixels, len(pixels)


def main() -> int:
    w, s, e, n = SOMERVILLE
    bbox = Polygon([(w, s), (e, s), (e, n), (w, n)])
    # margin of source data around the scored area; cells that still poke out
    # of it are dropped below rather than scored against truncated input
    pad = 0.02
    grown = Polygon([(w - pad, s - pad), (e + pad, s - pad),
                     (e + pad, n + pad), (w - pad, n + pad)])

    print("mean / max per-cell error, rebinning each source onto A5\n")
    header = f"{'source grid':<26}{'cells':>9}"
    for res in (12, 13, 14):
        header += f"{'A5 res ' + str(res):>18}"
    print(header)

    truths = {}
    for res in (12, 13, 14):
        km2 = a5.cell_area(res) / 1e6
        scored = {a5.lonlat_to_cell(p, res) for p in lattice(bbox, 4000)}
        # only score cells the source fully covers -- a cell hanging over the
        # edge of the source extent measures truncation, not resampling
        scored = {c for c in scored if grown.contains(a5_polygon(c))}
        truths[res] = {c: integrate(a5_polygon(c), km2) for c in scored}
        print(f"  (res {res}: scoring {len(scored)} cells)", file=sys.stderr)

    for label, metres in SOURCES:
        src, count = build_source(grown, metres)
        row = f"{label:<26}{count:>9,}"
        for res in (12, 13, 14):
            got = (rebin_area(src, res) if metres is None else bin_polygons(src, res))
            errs = [abs(got.get(c, 0.0) - v) / v for c, v in truths[res].items() if v > 0]
            row += f"{sum(errs) / len(errs):>10.1%} /{max(errs):>6.1%}"
        print(row)

    print("\nA5 cell sizes: res 12 = 2.027 km2, res 13 = 0.507 km2, res 14 = 0.127 km2")
    print("Error here is resampling loss only -- every source integrates the *same*")
    print("true field, so this is the cost of the grid hop, not of the source's own")
    print("population model.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
