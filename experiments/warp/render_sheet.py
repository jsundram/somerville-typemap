# /// script
# requires-python = ">=3.11"
# dependencies = ["shapely>=2.0", "fonttools>=4.50"]
# ///
"""Render a contact sheet of hero-label algorithms over the real shapes.

    uv run experiments/warp/render_sheet.py [algorithm]

Each cell: one neighborhood polygon (light outline) + the algorithm's
label attempt in black. Writes sheet.svg and sheet_layout.json (cell
transforms + polygon coords, for measure.py).
"""

import json
import math
import sys
from pathlib import Path

from shapely.geometry import LineString, Polygon, shape
from shapely.affinity import scale as ascale, translate

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from typemap.fills import PER_CHAR_HERO, _partitions, fitted_hero, polygon_ds  # noqa: E402
from typemap.svgdoc import SvgDoc, est_width  # noqa: E402

CELL, PAD, COLS = 520, 26, 5
HERE = Path(__file__).parent

HERO_STYLE = {
    "font_family": "Arial Rounded MT Bold, Cooper Black, Chalkboard SE, sans-serif",
    "font_weight": "900",
    "fill": "#111111",
    "font_size": 40,  # overwritten by the algorithm
}

FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf"


def algo_baseline(doc, polygon, name):
    """Today's fitted_hero: biggest clean 1-3 baselines that fit."""
    fitted_hero(doc, polygon, name, dict(HERO_STYLE))


# --- shared per-line layout (fitted_hero's chords, one size per line) -----

def _perline_layout(polygon, name, max_size=140, min_size=13, cram=0.80):
    """fitted_hero's chord layout with a font size per line.

    Taste rules 2026-07-22: each line fits its own chord (partition
    choice maximizes total ink, sum of size²·chars); reading order is
    protected by nesting every line's center within the widest line's
    along-axis extent, so a small line never reads as appended text.

    Returns None, or a dict with the frame (u, p, c), lines, sizes,
    per-line stacking offsets, chords, and (order-fixed) centers.
    """
    mrr = polygon.minimum_rotated_rectangle
    corners = list(mrr.exterior.coords)[:4]
    edges = [(corners[i], corners[(i + 1) % 4]) for i in range(4)]
    lengths = [math.dist(a, b) for a, b in edges]
    i_long = lengths.index(max(lengths))
    (ax, ay), (bx, by) = edges[i_long]
    long_len, short_len = lengths[i_long], lengths[(i_long + 1) % 4]
    ux, uy = (bx - ax) / long_len, (by - ay) / long_len
    if ux < 0:  # keep text left-to-right
        ux, uy = -ux, -uy
    px, py = -uy, ux
    if py < 0:  # keep the perpendicular pointing screen-down
        px, py = -px, -py
    c = polygon.representative_point()

    def chord_at(off):
        ox, oy = c.x + px * off, c.y + py * off
        cut = LineString([(ox - ux * long_len, oy - uy * long_len),
                          (ox + ux * long_len, oy + uy * long_len)]).intersection(polygon)
        if hasattr(cut, "geoms"):
            cut = max((g for g in cut.geoms if isinstance(g, LineString)),
                      key=lambda g: g.length, default=None)
        return cut if isinstance(cut, LineString) and not cut.is_empty else None

    def offsets(sizes):
        """Per-line stacking offsets, block centered on the polygon center."""
        offs = [0.0]
        for a, b in zip(sizes, sizes[1:]):
            offs.append(offs[-1] + (a + b) / 2 * 1.08)
        mid = (offs[0] + offs[-1]) / 2
        return [o - mid for o in offs]

    def t_of(pt):  # along-axis coordinate
        return pt[0] * ux + pt[1] * uy

    def line_layout(lines, sizes):
        rows = []
        for ln, s, off in zip(lines, sizes, offsets(sizes)):
            ch = chord_at(off)
            if ch is not None:
                mx, my = ch.interpolate(0.5, normalized=True).coords[0]
            else:
                mx, my = c.x + px * off, c.y + py * off
            rows.append({"line": ln, "size": s, "off": off, "chord": ch,
                         "center": (mx, my)})
        # reading-order fix: nest each center inside the widest line's extent
        halves = [PER_CHAR_HERO * len(r["line"]) * r["size"] / 2 for r in rows]
        big = max(range(len(rows)), key=lambda i: halves[i])
        t_big = t_of(rows[big]["center"])
        for i, r in enumerate(rows):
            if i == big or r["chord"] is None:
                continue
            slack = halves[big] - halves[i]
            if i < big:
                # earlier (smaller) lines may float between the start and
                # center of the big line — right of center reads as a
                # suffix, but gluing to the start wastes room (user note)
                t_tgt = min(max(t_of(r["center"]), t_big - slack), t_big)
            else:
                t_tgt = min(max(t_of(r["center"]), t_big - slack), t_big + slack)
            ch = r["chord"]
            t0 = t_of(ch.coords[0])
            s_pos = t_tgt - t0
            hw = halves[i]
            if ch.length > 2 * hw:
                s_pos = min(max(s_pos, hw), ch.length - hw)
                r["center"] = tuple(ch.interpolate(s_pos).coords[0])
        # glyph box per row, for the geometric shrink
        for r, hw in zip(rows, halves):
            (mx, my), s = r["center"], r["size"]
            up, dn = s * 0.62, s * 0.30
            r["box"] = Polygon([
                (mx - ux * hw - px * up, my - uy * hw - py * up),
                (mx + ux * hw - px * up, my + uy * hw - py * up),
                (mx + ux * hw + px * dn, my + uy * hw + py * dn),
                (mx - ux * hw + px * dn, my - uy * hw + py * dn),
            ])
        return rows

    def eval_partition(lines):
        """Fixed-point sizing + geometric shrink; score the *final* ink so
        a partition that collapses in practice can't win on estimates."""
        n = len(lines)
        cap = short_len * cram / (n + 0.15 * (n - 1))
        sizes = [min(max_size, cap)] * n
        for _ in range(4):  # fixed-point: offsets depend on sizes
            new = []
            for ln, off in zip(lines, offsets(sizes)):
                ch = chord_at(off)
                fit = (ch.length * 0.94) / (PER_CHAR_HERO * len(ln)) if ch else 0.0
                new.append(max(0.0, min(max_size, cap, fit)))
            sizes = new
        if min(sizes) <= 0:
            return None
        # Estimates lie; geometry doesn't — shrink only the offending lines.
        rows = line_layout(lines, sizes)
        for _ in range(40):
            bad = [i for i, r in enumerate(rows)
                   if r["size"] > min_size
                   and not r["box"].within(polygon.buffer(r["size"] * 0.12))]
            if not bad:
                break
            for i in bad:
                sizes[i] *= 0.93
            rows = line_layout(lines, sizes)
        sizes = [max(s, min_size) for s in sizes]
        rows = line_layout(lines, sizes)
        score = sum(r["size"] ** 2 * len(r["line"]) for r in rows)
        return rows, score

    words = name.upper().split()
    best = None
    for n in range(1, min(len(words), 3) + 1):
        for lines in _partitions(words, n):
            res = eval_partition(lines)
            if res and (best is None or res[1] > best[1]):
                best = res
    if best is None:
        return None
    return {"u": (ux, uy), "p": (px, py), "rows": best[0]}


def algo_perline(doc, polygon, name, bulge=0.08):
    """Per-line font sizes on fitted_hero's chords (user-suggested)."""
    lay = _perline_layout(polygon, name)
    if lay is None:
        return
    (ux, uy), (px, py) = lay["u"], lay["p"]
    for r in lay["rows"]:
        ln, s, (mx, my) = r["line"], r["size"], r["center"]
        st = {**HERO_STYLE, "font_size": round(s, 1), "text_anchor": "middle"}
        ox, oy = mx + px * s * 0.35, my + py * s * 0.35
        half = est_width(ln, s) * 0.75
        x0, y0 = ox - ux * half, oy - uy * half
        x1, y1 = ox + ux * half, oy + uy * half
        cxp = (x0 + x1) / 2 - px * bulge * 2 * half
        cyp = (y0 + y1) / 2 - py * bulge * 2 * half
        d = f"M {x0:.2f},{y0:.2f} Q {cxp:.2f},{cyp:.2f} {x1:.2f},{y1:.2f}"
        doc.text_on_path(d, ln, st, start_offset="50%")


# --- envelope: real glyph outlines, each stretched to the local height ----

_FONT = {}


def _glyphs():
    """Lazy-load the hero face: glyphset, cmap, upm, per-glyph bounds fn."""
    if not _FONT:
        from fontTools.pens.boundsPen import BoundsPen
        from fontTools.ttLib import TTFont
        f = TTFont(FONT_PATH)
        gs = f.getGlyphSet()
        bounds_cache = {}

        def bounds(gname):
            if gname not in bounds_cache:
                pen = BoundsPen(gs)
                gs[gname].draw(pen)
                bounds_cache[gname] = pen.bounds  # None for blank glyphs
            return bounds_cache[gname]

        _FONT.update(gs=gs, cmap=f.getBestCmap(),
                     upm=f["head"].unitsPerEm, bounds=bounds)
    return _FONT


def _free_span(polygon, pt, p, reach):
    """(up, down) free distance from `pt` to the boundary along ∓`p`."""
    px, py = p
    cut = LineString([(pt[0] - px * reach, pt[1] - py * reach),
                      (pt[0] + px * reach, pt[1] + py * reach)]).intersection(polygon)
    geoms = getattr(cut, "geoms", [cut]) if not cut.is_empty else []
    for g in geoms:
        if not isinstance(g, LineString):
            continue
        (x0, y0), (x1, y1) = g.coords[0], g.coords[-1]
        a = (x0 - pt[0]) * px + (y0 - pt[1]) * py
        b = (x1 - pt[0]) * px + (y1 - pt[1]) * py
        lo, hi = min(a, b), max(a, b)
        if lo <= 0 <= hi:
            return -lo, hi
    return None


class _WarpPen:
    """Pen that maps font-unit points through a warp fn into another pen."""

    def __init__(self, out, fn):
        self.out, self.fn = out, fn

    def moveTo(self, pt):
        self.out.moveTo(self.fn(pt))

    def lineTo(self, pt):
        self.out.lineTo(self.fn(pt))

    def curveTo(self, *pts):
        self.out.curveTo(*[self.fn(p) for p in pts])

    def qCurveTo(self, *pts):
        self.out.qCurveTo(*[self.fn(p) if p is not None else None for p in pts])

    def closePath(self):
        self.out.closePath()

    def endPath(self):
        self.out.endPath()

    def addComponent(self, name, transform):
        from fontTools.pens.transformPen import TransformPen
        _glyphs()["gs"][name].draw(_WarpPen(self.out, lambda pt, t=transform:
                                            self.fn(t.transformPoint(pt))))


def algo_envelope(doc, polygon, name, margin=2.5, max_ratio=2.5):
    """Per-line envelope stretch: perline's layout, glyphs as outlines,
    vertically warped to the polygon's local height. The vertical scale
    is sampled at every glyph's advance edges and midpoint (samples are
    shared between neighbors, so letter tops form a continuous envelope)
    and interpolated piecewise-linearly inside each glyph."""
    from fontTools.pens.svgPathPen import SVGPathPen

    lay = _perline_layout(polygon, name)
    if lay is None:
        return
    F = _glyphs()
    gs, cmap, upm, bounds = F["gs"], F["cmap"], F["upm"], F["bounds"]
    (ux, uy), (px, py) = lay["u"], lay["p"]
    rows = lay["rows"]
    reach = polygon.length  # ray length that always crosses the polygon

    # baseline stacking offsets (px below each row's optical center)
    base_offs = [r["off"] + 0.35 * r["size"] for r in rows]
    # one shared split per interline gap, so neighbors can't both claim it:
    # the zone below baseline i-1 (descenders/bottom growth) meets the zone
    # above baseline i (caps) at a size-proportional boundary
    splits = []
    for a, b, ra, rb in zip(base_offs, base_offs[1:], rows, rows[1:]):
        w = ra["size"] * 0.30 / (ra["size"] * 0.30 + rb["size"] * 0.75)
        splits.append(a + (b - a) * w)

    for i, r in enumerate(rows):
        ln, s, ch = r["line"], r["size"], r["chord"]
        (mx, my) = r["center"]
        bx, by = mx + px * s * 0.35, my + py * s * 0.35  # baseline midpoint
        gnames = [cmap.get(ord(c)) for c in ln]
        advs = [gs[g].width if g else upm * 0.3 for g in gnames]
        w_nat = sum(advs)
        if w_nat <= 0:
            continue
        # fill the usable chord symmetric about the (order-fixed) center
        if ch is not None:
            t0x, t0y = ch.coords[0]
            s_pos = (mx - t0x) * ux + (my - t0y) * uy
            usable = 2 * min(s_pos, ch.length - s_pos) * 0.94
        else:
            usable = PER_CHAR_HERO * len(ln) * s
        sx = usable / w_nat
        # never wider per glyph than the row is tall would allow legibly
        sx = min(sx, s / upm * max_ratio)

        # inter-line bands from the shared splits (pad keeps a hairline gap)
        pad = 1.5
        band_up = base_offs[i] - splits[i - 1] - pad if i > 0 else float("inf")
        band_dn = splits[i] - base_offs[i] - pad if i < len(rows) - 1 else float("inf")
        band_up = max(band_up, 1.0)
        band_dn = max(band_dn, 1.0)

        def up_dn_at(x_units):
            """(up, dn) room at a baseline x-position (font units from left)."""
            t_c = x_units * sx - w_nat * sx / 2
            span = _free_span(polygon, (bx + ux * t_c, by + uy * t_c),
                              (px, py), reach)
            if span is None:
                return None
            up, dn = span
            return (max(min(up - margin, band_up), 1.0),
                    max(min(dn - margin, band_dn), 1.0))

        x_pen = 0.0
        for gname, adv in zip(gnames, advs):
            if gname is None or bounds(gname) is None:
                x_pen += adv
                continue
            gx0, gy0, gx1, gy1 = bounds(gname)
            if gy1 <= 0:
                x_pen += adv
                continue
            g_lo = min(gy0, 0)  # ink bottom (descenders below the baseline)
            # two-sided envelope: at each sample the glyph's ink is mapped
            # into the full free span [-dn, +up]; samples sit at advance
            # edges + midpoint (edges are shared with the neighbors, so
            # tops AND bottoms form continuous curves)
            knots, tops, bots = [], [], []
            n_k = max(3, min(9, int(adv * sx / 15) + 2))  # dense on wide glyphs
            for j in range(n_k):
                x_k = x_pen + adv * j / (n_k - 1)
                room = up_dn_at(x_k)
                if room is None:
                    continue
                up_use, dn_use = room
                sy = min((up_use + dn_use) / (gy1 - g_lo), max_ratio * sx)
                extra = (up_use + dn_use) - (gy1 - g_lo) * sy
                bot = -dn_use + extra / 2  # leftover splits evenly
                knots.append(x_k)
                tops.append(max(sy, 0.02 * sx))
                bots.append(bot)
            if not knots:
                sy0 = min(s / upm, max_ratio * sx)
                knots, tops, bots = [x_pen], [sy0], [g_lo * sy0]

            def interp(x, vals, knots=knots):
                if x <= knots[0] or len(knots) == 1:
                    return vals[0]
                for a, b, va, vb in zip(knots, knots[1:], vals, vals[1:]):
                    if x <= b:
                        return va + (vb - va) * (x - a) / (b - a)
                return vals[-1]

            def warp(pt, x_pen=x_pen, g_lo=g_lo):
                gx, gy = pt
                x = x_pen + gx
                t = x * sx - w_nat * sx / 2
                v = interp(x, bots) + (gy - g_lo) * interp(x, tops)
                return (bx + ux * t - px * v, by + uy * t - py * v)

            pen = SVGPathPen(gs, ntos=lambda v: f"{v:.1f}")
            gs[gname].draw(_WarpPen(pen, warp))
            doc.raw(f'<path d="{pen.getCommands()}" fill="{HERO_STYLE["fill"]}"/>')
            x_pen += adv


ALGORITHMS = {
    "baseline": algo_baseline,
    "perline": algo_perline,
    "envelope": algo_envelope,
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
