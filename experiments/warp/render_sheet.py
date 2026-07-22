# /// script
# requires-python = ">=3.11"
# dependencies = ["shapely>=2.0"]
# ///
"""Render a contact sheet of hero-label algorithms over the real shapes.

    uv run experiments/warp/render_sheet.py [algorithm]

Each cell: one neighborhood polygon (light outline) + the algorithm's
label attempt in black. Writes sheet.svg and sheet_layout.json (cell
transforms + polygon coords, for measure.py).
"""

import json
import sys
from pathlib import Path

from shapely.geometry import shape
from shapely.affinity import scale as ascale, translate

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from typemap.fills import fitted_hero, polygon_ds  # noqa: E402
from typemap.svgdoc import SvgDoc  # noqa: E402

CELL, PAD, COLS = 520, 26, 5
HERE = Path(__file__).parent

HERO_STYLE = {
    "font_family": "Arial Rounded MT Bold, Cooper Black, Chalkboard SE, sans-serif",
    "font_weight": "900",
    "fill": "#111111",
    "font_size": 40,  # overwritten by the algorithm
}


def algo_baseline(doc, polygon, name):
    """Today's fitted_hero: biggest clean 1-3 baselines that fit."""
    fitted_hero(doc, polygon, name, dict(HERO_STYLE))


ALGORITHMS = {
    "baseline": algo_baseline,
    # add: "envelope": per-line vertical glyph stretch (fontTools outlines)
    # add: "ffd": quad-strip free-form deformation
}


def main():
    algo_name = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    algo = ALGORITHMS[algo_name]
    feats = json.loads((HERE / "shapes.json").read_text())["features"]

    rows = (len(feats) + COLS - 1) // COLS
    doc = SvgDoc(COLS * CELL, rows * CELL, background="#ffffff")
    layout = []
    for i, f in enumerate(feats):
        poly = shape(f["polygon"])
        minx, miny, maxx, maxy = poly.bounds
        s = min((CELL - 2 * PAD) / (maxx - minx), (CELL - 2 * PAD) / (maxy - miny))
        cx, cy = (i % COLS) * CELL, (i // COLS) * CELL
        cell_poly = translate(
            ascale(poly, s, s, origin=(minx, miny)),
            cx + PAD - minx, cy + PAD - miny)
        # recentre inside the cell
        bx0, by0, bx1, by1 = cell_poly.bounds
        cell_poly = translate(cell_poly, (CELL - (bx1 - bx0)) / 2 - (bx0 - cx),
                              (CELL - (by1 - by0)) / 2 - (by0 - cy))
        doc.raw(f'<path d="{" ".join(polygon_ds(cell_poly))}" fill="none" '
                f'stroke="#dddddd" stroke-width="1.5" fill-rule="evenodd"/>')
        algo(doc, cell_poly, f["name"])
        doc.raw(f'<text x="{cx + 8}" y="{cy + 16}" font-size="12" '
                f'font-family="monospace" fill="#999999">{f["name"]}</text>')
        layout.append({"name": f["name"],
                       "exterior": list(cell_poly.exterior.coords)
                       if cell_poly.geom_type == "Polygon" else
                       [list(g.exterior.coords) for g in cell_poly.geoms]})

    doc.write(HERE / "sheet.svg")
    (HERE / "sheet_layout.json").write_text(json.dumps(
        {"algorithm": algo_name, "cell": CELL, "cols": COLS, "cells": layout}))
    print(f"wrote {HERE / 'sheet.svg'} ({algo_name}, {len(feats)} cells)")


if __name__ == "__main__":
    main()
