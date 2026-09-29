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

from typemap.fills import (PER_CHAR_HERO, _partitions, _polygons,  # noqa: E402
                           fitted_hero, polygon_ds)
from typemap.svgdoc import SvgDoc, est_width  # noqa: E402

CELL, PAD, COLS = 520, 26, 5
HERE = Path(__file__).parent

HERO_STYLE = {
    "font_family": "Arial Rounded MT Bold, Cooper Black, Chalkboard SE, sans-serif",
    "font_weight": "900",
    # dark gray, still luminance < 128 so measure.py counts it as ink
    "fill": "#333333",
    "font_size": 40,  # overwritten by the algorithm
}

FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf"

# taste rule: names that may break mid-word into close separate words
SPLITS = {"HILLSIDE": "HILL SIDE"}


def algo_baseline(doc, polygon, name):
    """Today's fitted_hero: biggest clean 1-3 baselines that fit."""
    fitted_hero(doc, polygon, name, dict(HERO_STYLE))


# --- shared per-line layout (fitted_hero's chords, one size per line) -----

def _perline_layout(polygon, name, max_size=140, min_size=13, cram=0.80,
                    flip=False):
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
    if flip:  # user override: true 180° rotation — BOTH axes flip,
        # otherwise the glyphs come out mirrored
        ux, uy, px, py = -ux, -uy, -px, -py
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
                # earlier (smaller) lines may float from the big line's
                # start to a bit past its center — far right reads as a
                # suffix, but gluing to the start wastes room (user notes)
                t_tgt = min(max(t_of(r["center"]), t_big - slack),
                            t_big + 0.3 * slack)
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
            bad = {i for i, r in enumerate(rows)
                   if r["size"] > min_size
                   and not r["box"].within(polygon.buffer(r["size"] * 0.12))}
            # rows must not collide with each other either (interleaving
            # glyphs score well on paper but are unreadable)
            for i, ra in enumerate(rows):
                for j in range(i + 1, len(rows)):
                    inter = ra["box"].intersection(rows[j]["box"]).area
                    if inter > 0.04 * min(ra["box"].area, rows[j]["box"].area):
                        bad |= {k for k in (i, j) if rows[k]["size"] > min_size}
            if not bad:
                break
            for i in bad:
                sizes[i] *= 0.93
            rows = line_layout(lines, sizes)
        sizes = [max(s, min_size) for s in sizes]
        rows = line_layout(lines, sizes)

        def fits(rows):
            for i, r in enumerate(rows):
                if not r["box"].within(polygon.buffer(r["size"] * 0.12)):
                    return False
                for j in range(i + 1, len(rows)):
                    if r["box"].intersection(rows[j]["box"]).area > \
                       0.04 * min(r["box"].area, rows[j]["box"].area):
                        return False
            return True

        # grow lines that still have room after floating into place
        # (user note: INNER should fill its corner, not just sit there)
        for i in range(len(sizes)):
            for _ in range(12):
                trial = list(sizes)
                trial[i] = min(trial[i] * 1.06, max_size, cap * 1.1)
                if trial[i] <= sizes[i]:
                    break
                trows = line_layout(lines, trial)
                if not fits(trows):
                    break
                sizes, rows = trial, trows
        score = sum(r["size"] ** 2 * len(r["line"]) for r in rows)
        return rows, score

    words = SPLITS.get(name.upper(), name.upper()).split()
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


# taste rule: lobed shapes whose words split across the lobes
REGION_SPLIT = {"HILLSIDE", "BALL SQUARE", "PORTER SQUARE"}


def _lobe_regions(polygon, n):
    """Split a lobed polygon into n regions by erosion, or None.

    Erode until the shape falls apart into n sizable cores, then grow
    each core back and clip to the original — every lobe keeps roughly
    its natural share of the shape."""
    area = polygon.area
    best = None  # (n-th core area, cores, r) — favor balanced splits;
    # thin legs survive only as slivers, so even tiny cores count
    for fr in (0.05, 0.08, 0.11, 0.15, 0.19):
        r = fr * math.sqrt(area)
        comps = sorted((g for g in _polygons(polygon.buffer(-r))
                        if g.area > 0.005 * area),
                       key=lambda g: g.area, reverse=True)
        if len(comps) >= n and (best is None or comps[n - 1].area > best[0]):
            best = (comps[n - 1].area, comps[:n], r)
    if best is None:
        return None
    _, comps, r = best
    regs, claimed = [], None
    for comp in comps:  # largest core claims the shared elbow first
        reg = comp.buffer(r * 1.3).intersection(polygon)
        if claimed is not None:
            reg = reg.difference(claimed)
        reg = max(_polygons(reg), key=lambda g: g.area, default=None)
        if reg is None:
            return None
        claimed = reg if claimed is None else claimed.union(reg)
        regs.append(reg)
    return regs


# taste rule: per-label words whose reading direction flips 180°
# (user: HILL must flow the same way as SIDE)
FLIPS = {"HILLSIDE": {"HILL"}}
REGION_SIZE_RATIO = 2.2  # user: PORTER vs SQUARE contrast too big


def algo_envelope(doc, polygon, name, margin=2.5, max_ratio=3.0):
    """Per-line envelope stretch — see _envelope_render. Lobed shapes in
    REGION_SPLIT split into regions first, one word per lobe, read
    top-to-bottom (user suggestion: HILL and SIDE in Hillside's legs)."""
    words = SPLITS.get(name.upper(), name.upper()).split()
    if name.upper() in REGION_SPLIT and len(words) >= 2:
        regs = _lobe_regions(polygon, len(words))
        if regs:
            order = sorted(range(len(regs)),
                           key=lambda i: (regs[i].centroid.y, regs[i].centroid.x))
            pairs = [(regs[idx], w, w in FLIPS.get(name.upper(), ()))
                     for idx, w in zip(order, words)]
            # keep the words sized as one label: cap the ratio between
            # the biggest and smallest word (user: PORTER vs SQUARE)
            nats = []
            for reg, w, fl in pairs:
                l = _perline_layout(reg, w, flip=fl)
                nats.append(max((r["size"] for r in l["rows"]), default=0)
                            if l else 0)
            floor = min((v for v in nats if v > 0), default=0)
            cap = floor * REGION_SIZE_RATIO if floor else 140
            for reg, w, fl in pairs:
                _envelope_render(doc, reg, w, margin, max_ratio,
                                 flip=fl, max_size=cap)
            return
    _envelope_render(doc, polygon, name, margin, max_ratio)


def _envelope_render(doc, polygon, name, margin=2.5, max_ratio=3.0,
                     flip=False, max_size=140):
    """perline's layout, glyphs as outlines, vertically warped to the
    polygon's local height. The vertical scale is sampled at every
    glyph's advance edges (samples are shared between neighbors, so
    letter tops form a continuous envelope) and interpolated
    piecewise-linearly inside each glyph."""
    from fontTools.pens.svgPathPen import SVGPathPen

    lay = _perline_layout(polygon, name, max_size=max_size, flip=flip)
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
            usable = 2 * min(s_pos, ch.length - s_pos) * 0.96
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

        # pull the line off sharp tapers, asymmetrically: find the widest
        # window along the baseline with readable vertical room and fit
        # the text there (user notes: the T in TEELE, HILLSIDE's tail —
        # a crushed end glyph is worse than a slightly shorter line)
        h_min = 0.45 * s
        for _ in range(1):  # one trim only — repeated passes compound
            N = 24
            xs = [w_nat * j / (N - 1) for j in range(N)]
            rooms = [up_dn_at(x) for x in xs]
            spans = [rm[0] + rm[1] for rm in rooms if rm is not None]
            if not spans:
                break
            # relative floor: an end with a small fraction of the line's
            # best room crushes its glyph even if nominally "readable" —
            # but on elongated slivers (North Point) the widest pocket
            # would swallow the whole label, so use the absolute floor
            h_eff = max(h_min, 0.35 * max(spans))
            if max(spans) < 0.35 * usable or sum(
                    1 for rm in rooms
                    if rm is not None and rm[0] + rm[1] >= h_eff
            ) < 0.5 * len(rooms):
                h_eff = h_min
            good = [rm is not None and rm[0] + rm[1] >= h_eff for rm in rooms]
            best = (0, -1)
            a = None
            for j, g in enumerate(good + [False]):
                if g and a is None:
                    a = j
                elif not g and a is not None:
                    if j - 1 - a > best[1] - best[0]:
                        best = (a, j - 1)
                    a = None
            if best[1] <= best[0]:
                break
            x_lo, x_hi = xs[best[0]], xs[best[1]]
            # never trim below 70% of the natural width — a short readable
            # line beats a long crushed one, but not by that much
            if x_hi - x_lo < 0.7 * w_nat:
                mid_w = (x_lo + x_hi) / 2
                x_lo = max(0.0, mid_w - 0.35 * w_nat)
                x_hi = min(w_nat, x_lo + 0.7 * w_nat)
            if x_lo <= 0.0 and x_hi >= w_nat:
                break
            shift = ((x_lo + x_hi) / 2 - w_nat / 2) * sx
            bx, by = bx + ux * shift, by + uy * shift
            usable = (x_hi - x_lo) * sx * 0.98
            sx = min(usable / w_nat, s / upm * max_ratio)

        # pass 1: per-glyph envelope samples + within-glyph coherence.
        # two-sided envelope: at each sample the glyph's ink is mapped
        # into the full free span [-dn, +up]; samples sit at advance
        # edges (shared with the neighbors → continuous curves)
        glyphs = []
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
            knots, ups, dns = [], [], []
            n_k = max(3, min(17, int(adv * sx / 8) + 2))  # dense on wide glyphs
            for j in range(n_k):
                x_k = x_pen + adv * j / (n_k - 1)
                room = up_dn_at(x_k)
                if room is not None:
                    knots.append(x_k)
                    ups.append(room[0])
                    dns.append(room[1])
            g = {"name": gname, "adv": adv, "x_pen": x_pen,
                 "g_lo": g_lo, "gy1": gy1,
                 "knots": knots, "ups": ups, "dns": dns, "tops": None}
            if knots:
                tops = [max(min((u + d) / (gy1 - g_lo), max_ratio * sx),
                            0.02 * sx) for u, d in zip(ups, dns)]
                # glyph coherence: a letter is one shape — compress the
                # tall side to ≤1.6× the short side instead of letting a
                # taper crush half of it (user note: the T in TEELE)
                lo = min(tops)
                g["tops"] = [min(t, lo * 1.6) for t in tops]
            glyphs.append(g)
            x_pen += adv

        # word-level height-gradient cap: adjacent letters ≤1.5× — the
        # TEELE T vanished beside 4×-taller E's (user call)
        hs = [max(g["tops"]) * (g["gy1"] - g["g_lo"]) if g["tops"] else None
              for g in glyphs]
        idxs = [k for k, h in enumerate(hs) if h is not None]
        for seq in (idxs, idxs[::-1]):
            prev = None
            for k in seq:
                if prev is not None:
                    hs[k] = min(hs[k], hs[prev] * 1.5)
                prev = k
        for k, g in enumerate(glyphs):
            if g["tops"] and hs[k] is not None:
                cur = max(g["tops"]) * (g["gy1"] - g["g_lo"])
                if hs[k] < cur:
                    f = hs[k] / cur
                    g["tops"] = [t * f for t in g["tops"]]

        # pass 2a: bottoms + de-skew per glyph
        for g in glyphs:
            adv = g["adv"]
            g_lo, gy1 = g["g_lo"], g["gy1"]
            knots, ups, dns, tops = g["knots"], g["ups"], g["dns"], g["tops"]
            if knots:
                bots = [-d + (u + d - (gy1 - g_lo) * t) / 2
                        for u, d, t in zip(ups, dns, tops)]
                # de-skew: cap the baseline tilt inside one glyph (user
                # calls: T in TEELE, R in PORTER, U in Union's SQUARE) —
                # the word may ride a wavy baseline, but each letter
                # stays upright, not sheared into a parallelogram
                if len(bots) > 1:
                    mean_b = sum(bots) / len(bots)
                    dev = 0.10 * adv * sx  # ≈ ±11° across the glyph
                    bots = [min(max(b, mean_b - dev), mean_b + dev)
                            for b in bots]
                    bots = [max(b, -d) for b, d in zip(bots, dns)]
                    tops = [max(min(t, (u - b) / (gy1 - g_lo)), 0.02 * sx)
                            for t, u, b in zip(tops, ups, bots)]
            else:
                # baseline sample outside the polygon: stay banded anyway
                sy0 = min(s / upm, max_ratio * sx)
                if band_up != float("inf"):
                    sy0 = min(sy0, band_up / gy1)
                if band_dn != float("inf") and g_lo < 0:
                    sy0 = min(sy0, band_dn / -g_lo)
                sy0 = max(sy0, 0.02 * sx)
                knots, tops, bots = [g["x_pen"]], [sy0], [g_lo * sy0]
            g["knots"], g["tops"], g["bots"] = knots, tops, bots

        # pass 2b: word-level baseline-step cap — a letter whose bottom
        # jumps far from its neighbors reads as its own line (user call:
        # the S in BALL SQUARE's SQUARE)
        step = 0.25 * s
        means = [sum(g["bots"]) / len(g["bots"]) for g in glyphs]
        order_ = list(range(1, len(glyphs)))
        for seq in (order_, order_[::-1]):  # both ways so an outlier end
            for k in seq:                   # glyph is pulled to the word
                prev = k - 1 if seq is order_ else k + 1
                if prev < 0 or prev >= len(glyphs):
                    continue
                delta = means[k] - means[prev]
                capped = min(max(delta, -step), step)
                if capped != delta:
                    shift = capped - delta
                    g = glyphs[k]
                    g["bots"] = [b + shift for b in g["bots"]]
                    means[k] += shift
                    if g["ups"]:  # keep the shifted glyph inside its room
                        g["bots"] = [max(b, -d)
                                     for b, d in zip(g["bots"], g["dns"])]
                        g["tops"] = [max(min(t, (u - b) /
                                             (g["gy1"] - g["g_lo"])),
                                         0.02 * sx)
                                     for t, u, b in
                                     zip(g["tops"], g["ups"], g["bots"])]

        # pass 2c: render
        for g in glyphs:
            gname, gx_pen, g_lo = g["name"], g["x_pen"], g["g_lo"]
            knots, tops, bots = g["knots"], g["tops"], g["bots"]

            def interp(x, vals, knots=knots):
                if x <= knots[0] or len(knots) == 1:
                    return vals[0]
                for a, b, va, vb in zip(knots, knots[1:], vals, vals[1:]):
                    if x <= b:
                        return va + (vb - va) * (x - a) / (b - a)
                return vals[-1]

            def warp(pt, x_pen=gx_pen, g_lo=g_lo, tops=tops, bots=bots,
                     interp=interp):
                gx, gy = pt
                x = x_pen + gx
                t = x * sx - w_nat * sx / 2
                v = interp(x, bots) + (gy - g_lo) * interp(x, tops)
                return (bx + ux * t - px * v, by + uy * t - py * v)

            pen = SVGPathPen(gs, ntos=lambda v: f"{v:.1f}")
            gs[gname].draw(_WarpPen(pen, warp))
            doc.raw(f'<path d="{pen.getCommands()}" fill="{HERO_STYLE["fill"]}"/>')


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
        # border at luminance ≥ 128 (#888 = 136) so measure.py never counts it
        doc.raw(f'<path d="{" ".join(polygon_ds(cell_poly))}" fill="none" '
                f'stroke="#888888" stroke-width="4" fill-rule="evenodd"/>')
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
