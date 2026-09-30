# /// script
# requires-python = ">=3.11"
# dependencies = ["shapely>=2.0", "fonttools>=4.50", "numpy"]
# ///
"""Curved vs straight hero layouts, side by side, for the thin shapes.

    uv run experiments/warp/curve_compare.py      # → compare/curves.svg

Top row: the layout search forced onto curved baselines (config
HERO_CURVES), the chosen spine in red. Bottom row: the same search with
curves switched off. Each cell notes the label and its line sizes.
"""

import json
import sys
from pathlib import Path

from shapely.affinity import scale as ascale, translate
from shapely.geometry import LineString, shape

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import render_sheet as RS  # noqa: E402
from typemap import hero_layout as hl  # noqa: E402
from typemap.fills import polygon_ds  # noqa: E402
from typemap.svgdoc import SvgDoc  # noqa: E402

NAMES = ["North Point", "Hillside", "Porter Square", "Brickbottom", "Twin City"]
CELL, PAD = 520, 26


def cell_poly(name, col, row, feats):
    poly = shape(feats[name]["polygon"])
    minx, miny, maxx, maxy = poly.bounds
    k = min((CELL - 2 * PAD) / (maxx - minx), (CELL - 2 * PAD) / (maxy - miny))
    return translate(ascale(poly, k, k, origin=(minx, miny)),
                     col * CELL + PAD - minx, row * CELL + PAD - miny)


def main():
    feats = {f["name"]: f for f in json.loads((HERE / "shapes.json").read_text())["features"]}
    M = hl.Metrics.load(RS.FONT_PATH)
    doc = SvgDoc(len(NAMES) * CELL, 2 * CELL, background="#ffffff")
    saved = set(hl.HERO_CURVES), hl.CURVE_ELONGATION
    for row, mode in enumerate(("curved", "straight")):
        hl.HERO_CURVES.clear()
        if mode == "curved":
            hl.HERO_CURVES.update(NAMES)
        else:
            hl.CURVE_ELONGATION = float("inf")  # curves off
        for col, name in enumerate(NAMES):
            poly = cell_poly(name, col, row, feats)
            doc.raw(f'<path d="{" ".join(polygon_ds(poly))}" fill="none" '
                    f'stroke="#888" stroke-width="4"/>')
            res = hl.search(poly, name, M)
            note = "no fit"
            if res is not None:
                fr = res["rows"][0]["frame"]
                if isinstance(fr, hl.SpineFrame):
                    # the spine runs past the shape (extended ends); show
                    # only the part inside
                    inside = LineString(fr.P).intersection(poly)
                    for part in getattr(inside, "geoms", [inside]):
                        if isinstance(part, LineString) and not part.is_empty:
                            doc.raw('<path d="M ' + " L ".join(
                                f"{x:.1f},{y:.1f}" for x, y in part.coords)
                                + '" fill="none" stroke="#e33" stroke-width="1.5"/>')
                hl.render(doc, res, M, "#333")
                note = (" / ".join(res["lines"]) + "  ·  "
                        + ", ".join(str(round(r["size"])) for r in res["rows"]))
            doc.raw(f'<text x="{col * CELL + 8}" y="{row * CELL + 16}" font-size="12" '
                    f'font-family="monospace" fill="#999">{name} — {mode}: {note}</text>')
        hl.HERO_CURVES.clear()
        hl.HERO_CURVES.update(saved[0])
        hl.CURVE_ELONGATION = saved[1]
    out = HERE / "compare/curves.svg"
    out.parent.mkdir(exist_ok=True)
    doc.write(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
