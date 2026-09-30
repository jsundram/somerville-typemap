# /// script
# requires-python = ">=3.11"
# dependencies = ["shapely>=2.0", "fonttools>=4.50", "numpy"]
# ///
"""Curved vs straight hero layouts, side by side, for the thin shapes.

    uv run experiments/warp/curve_compare.py      # → compare/curves.svg

Row 0: how the spine is built — Voronoi cells of boundary samples
(gray), the skeleton = Voronoi edges inside the shape (tan), the longest
route through it (blue), the route smoothed at ±24/60/120 px (red,
light→dark), straight extensions past both ends (green, dashed).
Row 1: the layout search forced onto curved baselines (config
HERO_CURVES), the chosen spine in red. Row 2: forced swell — per-letter
sizes (config HERO_SWELL), on a spine or a straight axis. Row 3: the
same search with curves and swell off. Each cell notes the label and its
line sizes (swell: smallest–largest letter).
Row 4: forced word breaks at sharp bends of the skeleton route (HERO_BENDS).
"""

import json
import math
import sys
from pathlib import Path

from shapely.affinity import scale as ascale, translate
from shapely.geometry import LineString, box as shapely_box, shape
from shapely.ops import unary_union

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
HEAD = 70  # header band per cell: title + big coverage score


def cell_poly(name, col, row, feats):
    poly = shape(feats[name]["polygon"])
    minx, miny, maxx, maxy = poly.bounds
    k = min((CELL - 2 * PAD) / (maxx - minx), (CELL - 2 * PAD) / (maxy - miny))
    return translate(ascale(poly, k, k, origin=(minx, miny)),
                     col * CELL + PAD - minx, row * (CELL + HEAD) + HEAD + PAD - miny)


def coverage(poly, res, M):
    """Ink share of the shape: glyph outlines inside ÷ shape area — the
    black-pixels-over-shape-pixels ratio, computed exactly."""
    ink = unary_union([hl.outline(r, M) for r in res["rows"]])
    return ink.intersection(poly).area / poly.area


def header(doc, col, row, title, score=None):
    y = row * (CELL + HEAD)
    doc.raw(f'<text x="{col * CELL + 10}" y="{y + 22}" font-size="16" '
            f'font-family="monospace" fill="#666">{title}</text>')
    if score is not None:
        doc.raw(f'<text x="{col * CELL + 10}" y="{y + 60}" font-size="34" '
                f'font-weight="bold" font-family="monospace" fill="#222">'
                f'{score:.1%} ink</text>')


def _path(pts, style):
    return ('<path d="M ' + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
            + f'" fill="none" {style}/>')


def construction(doc, poly, name, col, row):
    """Draw each stage of hero_layout.centerline for this shape."""
    from shapely.geometry import MultiPoint
    from shapely.ops import voronoi_diagram

    inner = poly.buffer(-hl.MARGIN)
    stages = {}
    hl.centerline(inner, debug=stages)
    clip = poly.buffer(2)
    cells = voronoi_diagram(MultiPoint(stages["samples"]))
    for cell in cells.geoms:
        c = cell.intersection(clip)
        for part in getattr(c, "geoms", [c]):
            if part.geom_type == "Polygon" and not part.is_empty:
                doc.raw(_path(list(part.exterior.coords),
                              'stroke="#c9c9c9" stroke-width="0.7"'))
    doc.raw(f'<path d="{" ".join(polygon_ds(poly))}" fill="none" '
            f'stroke="#888" stroke-width="4"/>')
    for x, y in stages["samples"]:
        doc.raw(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1.6" fill="#999"/>')
    for e in stages["skeleton"]:
        doc.raw(_path(e, 'stroke="#d9a441" stroke-width="1.2"'))
    doc.raw(_path(stages["route"], 'stroke="#2f6aa8" stroke-width="3"'))
    roomy = {}
    hl.centerline(inner, debug=roomy, route="roomy")
    doc.raw(_path(roomy["route"], 'stroke="#8e44ad" stroke-width="3" '
                                   'stroke-dasharray="2 3"'))
    for reg in hl.bend_regions(inner) or []:  # bend cuts (word breaks)
        doc.raw(_path(list(reg.exterior.coords), 'stroke="#2f6aa8" '
                      'stroke-width="1" stroke-dasharray="3 3"'))
    for sm, color in ((24, "#f4a09a"), (60, "#e5534b")):
        st = {}
        hl.centerline(inner, smooth=sm, debug=st)
        doc.raw(_path(st["smoothed"], f'stroke="{color}" stroke-width="2"'))
        ext = st["extended"]
        sm_pts = st["smoothed"]
        # the extensions: each extended end back to its smoothed end
        y0 = row * (CELL + HEAD) + HEAD
        box = shapely_box(col * CELL + 4, y0, (col + 1) * CELL - 4, y0 + CELL - 4)
        for tip in (ext[0], ext[-1]):
            near = min((sm_pts[0], sm_pts[-1]), key=lambda q: math.dist(q, tip))
            seg = LineString([near, tip]).intersection(box)  # stay in the cell
            if not seg.is_empty:
                doc.raw(_path(list(seg.coords), 'stroke="#2f8f4e" stroke-width="1.5" '
                                                'stroke-dasharray="6 4"'))
    header(doc, col, row, f"{name} — how the spine is built")
    if col == 0:  # legend, in North Point's empty lower half
        items = [("#c9c9c9", "Voronoi cells of 240 boundary samples"),
                 ("#d9a441", "skeleton: Voronoi edges inside the shape"),
                 ("#2f6aa8", "longest route through the skeleton"),
                 ("#8e44ad", "roomiest route (length × clearance²)"),
                 ("#f4a09a", "smoothed ±24 px"), ("#e5534b", "smoothed ±60 px"),
                 ("#2f8f4e", "extensions (30% of length, straight)")]
        for i, (color, label) in enumerate(items):
            y = row * (CELL + HEAD) + HEAD + 300 + i * 24
            dash = (' stroke-dasharray="6 4"' if "extensions" in label else
                    ' stroke-dasharray="2 3"' if "roomiest" in label else "")
            doc.raw(f'<line x1="{col * CELL + 30}" y1="{y}" x2="{col * CELL + 70}" '
                    f'y2="{y}" stroke="{color}" stroke-width="3"{dash}/>')
            doc.raw(f'<text x="{col * CELL + 80}" y="{y + 5}" font-size="14" '
                    f'font-family="monospace" fill="#555">{label}</text>')


def main():
    feats = {f["name"]: f for f in json.loads((HERE / "shapes.json").read_text())["features"]}
    M = hl.Metrics.load(RS.FONT_PATH)
    modes = ("construction", "curved", "swell", "bends", "straight")
    doc = SvgDoc(len(NAMES) * CELL, len(modes) * (CELL + HEAD), background="#ffffff")
    saved = set(hl.HERO_CURVES), set(hl.HERO_SWELL), hl.CURVE_ELONGATION
    for row, mode in enumerate(modes):
        hl.HERO_CURVES.clear()
        hl.HERO_SWELL.clear()
        hl.HERO_BENDS.clear()
        hl.CURVE_ELONGATION = saved[2]
        if mode == "curved":
            hl.HERO_CURVES.update(NAMES)
        elif mode == "swell":
            hl.HERO_SWELL.update(NAMES)
        elif mode == "bends":
            hl.HERO_BENDS.update(NAMES)
        else:
            hl.CURVE_ELONGATION = float("inf")  # curves + swell off
        for col, name in enumerate(NAMES):
            poly = cell_poly(name, col, row, feats)
            if mode == "construction":
                construction(doc, poly, name, col, row)
                continue
            doc.raw(f'<path d="{" ".join(polygon_ds(poly))}" fill="none" '
                    f'stroke="#888" stroke-width="4"/>')
            res = hl.search(poly, name, M)
            note, score = "no fit", None
            if res is not None:
                score = coverage(poly, res, M)
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
                note = (" / ".join(res["lines"]) + "  ·  " + ", ".join(
                    f"{round(min(r['sizes']))}–{round(max(r['sizes']))}"
                    if "sizes" in r else str(round(r["size"]))
                    for r in res["rows"]))
            header(doc, col, row, f"{name} — {mode}: {note}", score)
    hl.HERO_BENDS.clear()
    hl.HERO_CURVES.clear()
    hl.HERO_CURVES.update(saved[0])
    hl.HERO_SWELL.clear()
    hl.HERO_SWELL.update(saved[1])
    hl.CURVE_ELONGATION = saved[2]
    out = HERE / "compare/curves.svg"
    out.parent.mkdir(exist_ok=True)
    doc.write(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
