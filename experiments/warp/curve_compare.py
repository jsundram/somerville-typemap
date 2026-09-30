# /// script
# requires-python = ">=3.11"
# dependencies = ["shapely>=2.0", "fonttools>=4.50", "numpy"]
# ///
"""Hero layout modes, side by side, for the thin shapes.

    uv run experiments/warp/curve_compare.py      # → compare/curves.svg

One row per mode (named in the left column), one column per shape. The
top row shows how the spine is built; every other cell shows its layout
and its **ink coverage** (glyph outlines inside ÷ shape area). The best
score for each shape is highlighted green.
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
HEAD = 70     # header band per cell: title + big coverage score
GUTTER = 250  # left column: row names
GOOD = "#2f8f4e"

# (key, row title, description, how to force it)
MODES = [
    ("construction", "SPINE", "how the curved\nbaseline is built", None),
    ("curved", "CURVED", "one line along\nthe smoothed spine", "curves"),
    ("swell", "SWELL", "letter sizes follow\nthe room (≤12% steps)", "swell"),
    ("bends", "BENDS ≤45°", "words split at sharp\nbends, ≤45° apart", "bends45"),
    ("bends30", "BENDS ≤30°", "same, words ≤30° apart\n(more continuous)", "bends30"),
    ("straight", "STRAIGHT", "straight baselines\nonly (the default)", "straight"),
]


def X(col):
    return GUTTER + col * CELL


def Y(row):
    return row * (CELL + HEAD)


def cell_poly(name, col, row, feats):
    poly = shape(feats[name]["polygon"])
    minx, miny, maxx, maxy = poly.bounds
    k = min((CELL - 2 * PAD) / (maxx - minx), (CELL - 2 * PAD) / (maxy - miny))
    return translate(ascale(poly, k, k, origin=(minx, miny)),
                     X(col) + PAD - minx, Y(row) + HEAD + PAD - miny)


def coverage(poly, res, M):
    """Ink share of the shape: glyph outlines inside ÷ shape area — the
    black-pixels-over-shape-pixels ratio, computed exactly."""
    ink = unary_union([hl.outline(r, M) for r in res["rows"]])
    return ink.intersection(poly).area / poly.area


def header(doc, col, row, title, score=None, best=False):
    y = Y(row)
    if best:  # the winning cell for this shape
        doc.raw(f'<rect x="{X(col) + 3}" y="{y + 3}" width="{CELL - 6}" '
                f'height="{CELL + HEAD - 6}" rx="10" fill="#eaf5ec" '
                f'stroke="{GOOD}" stroke-width="3"/>')
    doc.raw(f'<text x="{X(col) + 12}" y="{y + 24}" font-size="16" '
            f'font-family="monospace" fill="#666">{title}</text>')
    if score is not None:
        tag = "  ★ best" if best else ""
        doc.raw(f'<text x="{X(col) + 12}" y="{y + 62}" font-size="34" '
                f'font-weight="bold" font-family="monospace" '
                f'fill="{GOOD if best else "#222"}">{score:.1%} ink{tag}</text>')


def row_label(doc, row, title, desc):
    y = Y(row) + (CELL + HEAD) / 2 - 20
    doc.raw(f'<text x="{GUTTER - 24}" y="{y}" font-size="30" font-weight="bold" '
            f'font-family="monospace" text-anchor="end" fill="#222">{title}</text>')
    for i, ln in enumerate(desc.split("\n")):
        doc.raw(f'<text x="{GUTTER - 24}" y="{y + 30 + i * 22}" font-size="16" '
                f'font-family="monospace" text-anchor="end" fill="#777">{ln}</text>')


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
        y0 = Y(row) + HEAD
        box = shapely_box(X(col) + 4, y0, X(col) + CELL - 4, y0 + CELL - 4)
        for tip in (ext[0], ext[-1]):
            near = min((sm_pts[0], sm_pts[-1]), key=lambda q: math.dist(q, tip))
            seg = LineString([near, tip]).intersection(box)  # stay in the cell
            if not seg.is_empty:
                doc.raw(_path(list(seg.coords), 'stroke="#2f8f4e" stroke-width="1.5" '
                                                'stroke-dasharray="6 4"'))
    header(doc, col, row, f"{name}")
    if col == 0:  # legend, in North Point's empty lower half
        items = [("#c9c9c9", "Voronoi cells of 240 boundary samples"),
                 ("#d9a441", "skeleton: Voronoi edges inside the shape"),
                 ("#2f6aa8", "longest route through the skeleton"),
                 ("#8e44ad", "roomiest route (length × clearance²)"),
                 ("#f4a09a", "smoothed ±24 px"), ("#e5534b", "smoothed ±60 px"),
                 ("#2f8f4e", "extensions (30% of length, straight)")]
        for i, (color, label) in enumerate(items):
            y = Y(row) + HEAD + 300 + i * 24
            dash = (' stroke-dasharray="6 4"' if "extensions" in label else
                    ' stroke-dasharray="2 3"' if "roomiest" in label else "")
            doc.raw(f'<line x1="{X(col) + 30}" y1="{y}" x2="{X(col) + 70}" '
                    f'y2="{y}" stroke="{color}" stroke-width="3"{dash}/>')
            doc.raw(f'<text x="{X(col) + 80}" y="{y + 5}" font-size="14" '
                    f'font-family="monospace" fill="#555">{label}</text>')


def force(mode):
    """Set hero_layout's switches so the search produces only this mode."""
    hl.HERO_CURVES.clear()
    hl.HERO_SWELL.clear()
    hl.HERO_BENDS.clear()
    hl.CURVE_ELONGATION = _SAVED["elong"]
    hl.SPLIT_TURN = _SAVED["turn"]
    if mode == "curves":
        hl.HERO_CURVES.update(NAMES)
    elif mode == "swell":
        hl.HERO_SWELL.update(NAMES)
    elif mode in ("bends45", "bends30"):
        hl.HERO_BENDS.update(NAMES)
        hl.SPLIT_TURN = 30.0 if mode == "bends30" else 45.0
    elif mode == "straight":
        hl.CURVE_ELONGATION = float("inf")  # curves, swell, bends off


def main():
    feats = {f["name"]: f for f in json.loads((HERE / "shapes.json").read_text())["features"]}
    M = hl.Metrics.load(RS.FONT_PATH)
    _SAVED.update(curves=set(hl.HERO_CURVES), swell=set(hl.HERO_SWELL),
                  elong=hl.CURVE_ELONGATION, turn=hl.SPLIT_TURN)
    doc = SvgDoc(GUTTER + len(NAMES) * CELL, len(MODES) * (CELL + HEAD),
                 background="#ffffff")
    # pass 1: search every cell (so the best per shape is known)
    cells = {}
    for row, (key, title, desc, how) in enumerate(MODES):
        if how is None:
            continue
        force(how)
        for col, name in enumerate(NAMES):
            poly = cell_poly(name, col, row, feats)
            res = hl.search(poly, name, M)
            score = coverage(poly, res, M) if res else None
            cells[row, col] = (poly, res, score)
    top = {col: max(cells[k][2] or 0 for k in cells if k[1] == col)
           for col in range(len(NAMES))}
    # ties (within 0.05 pt) all count as best
    best = {k: (cells[k][2] or 0) >= top[k[1]] - 0.0005 for k in cells}
    # pass 2: draw
    for row, (key, title, desc, how) in enumerate(MODES):
        row_label(doc, row, title, desc)
        for col, name in enumerate(NAMES):
            if how is None:
                construction(doc, cell_poly(name, col, row, feats), name, col, row)
                continue
            poly, res, score = cells[row, col]
            header(doc, col, row, "", score, best=best[row, col])  # backdrop
            doc.raw(f'<path d="{" ".join(polygon_ds(poly))}" fill="none" '
                    f'stroke="#888" stroke-width="4"/>')
            note = "no fit"
            if res is not None:
                fr = res["rows"][0]["frame"]
                if isinstance(fr, hl.SpineFrame):
                    # the spine runs past the shape (extended ends); show
                    # only the part inside
                    inside = LineString(fr.P).intersection(poly)
                    for part in getattr(inside, "geoms", [inside]):
                        if isinstance(part, LineString) and not part.is_empty:
                            doc.raw(_path(list(part.coords),
                                          'stroke="#e33" stroke-width="1.5"'))
                hl.render(doc, res, M, "#333")
                note = (" / ".join(res["lines"]) + "  ·  " + ", ".join(
                    f"{round(min(r['sizes']))}–{round(max(r['sizes']))}"
                    if "sizes" in r else str(round(r["size"]))
                    for r in res["rows"]))
            doc.raw(f'<text x="{X(col) + 12}" y="{Y(row) + 24}" font-size="16" '
                    f'font-family="monospace" fill="#666">{name} · {note}</text>')
    force(None)
    hl.HERO_CURVES.update(_SAVED["curves"])
    hl.HERO_SWELL.update(_SAVED["swell"])
    out = HERE / "compare/curves.svg"
    out.parent.mkdir(exist_ok=True)
    doc.write(out)
    print(f"wrote {out}")


_SAVED = {}


if __name__ == "__main__":
    main()
