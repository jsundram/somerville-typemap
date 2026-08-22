# /// script
# requires-python = ">=3.11"
# dependencies = ["pya5>=0.9", "shapely>=2"]
# ///
"""Probe the consistency of the A5 API, since rebinning depends on it.

Three questions, each answered by measurement:

1. Do lonlat_to_cell() and cell_to_boundary() agree?  (Is a point inside the
   polygon of the cell it indexes to?)
2. Is the cell hierarchy spatially consistent?  (Does a point's fine cell sit
   under the point's own coarse cell?)
3. Do a cell's children tile the cell?

Observed with pya5 0.9.0 (and reproduced with a5-js 0.9.0): yes to 1, no to
2 and 3 -- the parent/child relation is index arithmetic, and the region a
cell's children cover overlaps the cell's own boundary by only ~58%.  So
areal work must be built on lonlat_to_cell/cell_to_boundary/grid_disk, never
on cell_to_parent/cell_to_children/uncompact.
"""

import random

import a5
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

random.seed(11)
POINTS = [(random.uniform(-71.14, -71.06), random.uniform(42.36, 42.42)) for _ in range(300)]


def main() -> int:
    print("point inside the polygon of its own cell / fine cell's parent == coarse cell")
    for res in range(10, 15):
        inside = sum(
            Polygon(a5.cell_to_boundary(a5.lonlat_to_cell(p, res))).contains(Point(p))
            for p in POINTS
        )
        nested = sum(
            a5.cell_to_parent(a5.lonlat_to_cell(p, res + 3), res) == a5.lonlat_to_cell(p, res)
            for p in POINTS
        )
        print(f"  res {res}: {inside / len(POINTS):6.1%} inside   {nested / len(POINTS):6.1%} nested")

    print("\nchildren vs their parent's own boundary")
    cell = a5.lonlat_to_cell((-71.10, 42.39), 11)
    parent = Polygon(a5.cell_to_boundary(cell))
    for child_res in range(12, 16):
        kids = a5.cell_to_children(cell, child_res)
        union = unary_union([Polygon(a5.cell_to_boundary(k)) for k in kids])
        print(f"  res {child_res}: {len(kids):4d} children, union area / parent area "
              f"{union.area / parent.area:.4f}, but only "
              f"{parent.intersection(union).area / parent.area:.1%} of the parent is covered")

    print("\npolygon_to_cells() returns a compacted, mixed-resolution covering")
    ring = [(-71.135, 42.372), (-71.072, 42.372), (-71.072, 42.418),
            (-71.135, 42.418), (-71.135, 42.372)]
    cells = a5.polygon_to_cells(ring, 13)
    hist = sorted({a5.get_resolution(c) for c in cells})
    print(f"  asked for res 13, got {len(cells)} cells at resolutions {hist}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
