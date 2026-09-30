"""Hero layout search — neighborhood names fitted into their polygons.

Developed in experiments/warp (algorithm 4 in its README, the spec and
results log); promoted to the engine for L5.

Undistorted glyph outlines; the layout is *searched* over discrete
choices instead of bending letters:

  - text candidates: the full name + config HERO_VARIANTS, with the
    SQUARE→SQ rule (HERO_ABBREVIATIONS) applied to every form, and every
    allowed line break (spaces; "-" marks optional hyphenated breaks);
  - angle: min-rect long axis, the longest straight edges, horizontal,
    and a 15° sweep;
  - placement: each line at its own position across the shape, lines
    kept together (bounded gap, horizontal overlap);
  - size trades: a line may shrink so its siblings grow;
  - split: a 2-line label may put one word in each lobe of a bent shape
    (HILL / SIDE), both at one angle so they read the same way.
Curved baselines come later (phase 6).

Sizing runs on a raster of the shape (fast, conservative boxes); the top
few layouts are then refined against the real glyph outlines — letters
tuck into corners their boxes can't (the empty top-right of an L), and
descending tails (Q) are caught. Score = √(smallest size × √ink) ×
(1 − penalties): legibility and fill balanced, shortenings, hyphen
breaks, splits and tilt must win by a margin.
"""

import itertools
import math

import shapely
from shapely.affinity import affine_transform
from shapely.geometry import Polygon
from shapely.ops import unary_union

from config.words import (HERO_ABBREVIATIONS, HERO_CURVES, HERO_SPLITS,  # noqa: E402
                          HERO_VARIANTS)
from typemap.fills import _polygons  # noqa: E402

# score penalties (fractions of ink): the full name should win ties
PENALTY = {"abbrev": 0.08, "hyphen": 0.12, "variant": 0.04,
           "split": 0.10,  # a label in two places reads less as one
           "curve": 0.06,  # a curved baseline reads a little slower
           "tilt": 0.06}  # × |sin angle|: horizontal reads easiest
MAX_LINES = 3
LEADING = 0.30   # gap between stacked lines, as a fraction of cap height
MARGIN = 3.0     # px kept clear of the polygon edge
MAX_SIZE = 220   # em size cap (px)
MIN_SIZE = 6     # below this a candidate is infeasible
GRID = 160       # raster cells across the shape's longer extent
ANGLE_STEP = 15  # degrees, coarse sweep
TRADE = 0.8      # a line may give up 20% so its siblings can grow
MAX_GAP = 1.0    # lines stay together: gap ≤ this × the upper line's cap
                 # (North Point had NORTH and POINT at opposite ends)
OVERLAP = 0.4    # consecutive lines overlap along the baseline by ≥ this
                 # share of the shorter one
SPLIT_RATIO = 2.2  # split words: bigger ≤ 2.2× smaller (user: PORTER/SQUARE)
REFINE_TOP = 4   # layouts refined against real outlines
CURVE_ELONGATION = 3.0  # only shapes ≥ this long/wide try curved baselines
PRESENCE = 0.25  # score × span^this: spanning the shape's length matters a little
MAX_RATIO = 2.0  # biggest line ≤ 2× the smallest — one label, not a headline
                 # + footnote (run 1: SQ dwarfed ASSEMBLY, MA- dwarfed GOUN)


# --- text candidates -------------------------------------------------------

def forms(name: str):
    """(text, penalty) for the full name, its variants, and SQ forms."""
    out = {}
    for i, v in enumerate([name.upper()] + HERO_VARIANTS.get(name, [])):
        base = PENALTY["variant"] if i else 0.0
        words = v.split()
        for mask in itertools.product(*[(False, True) if w in HERO_ABBREVIATIONS
                                        else (False,) for w in words]):
            text = " ".join(HERO_ABBREVIATIONS[w] if m else w
                            for w, m in zip(words, mask))
            pen = base + PENALTY["abbrev"] * sum(mask)
            if text not in out or pen < out[text]:
                out[text] = pen
    return list(out.items())


def breakings(text: str):
    """Every way to set `text` in 1..MAX_LINES lines.

    Spaces break or stay spaces; each "-" is an optional hyphenated break
    (break → "BRICK-" / "BOTTOM", no break → "BRICKBOTTOM").
    Yields (lines, n_hyphen_breaks).
    """
    # tokens alternate: piece, joint, piece, joint, ...
    pieces, joints = [], []
    for wi, word in enumerate(text.split()):
        if wi:
            joints.append(" ")
        parts = word.split("-")
        for pi, part in enumerate(parts):
            if pi:
                joints.append("-")
            pieces.append(part)
    for brk in itertools.product((False, True), repeat=len(joints)):
        if sum(brk) + 1 > MAX_LINES:
            continue
        lines, cur, hyph = [], pieces[0], 0
        for joint, b, piece in zip(joints, brk, pieces[1:]):
            if b:
                if joint == "-":
                    cur += "-"
                    hyph += 1
                lines.append(cur)
                cur = piece
            else:
                cur += " " + piece if joint == " " else piece
        lines.append(cur)
        yield lines, hyph


def candidates(name: str):
    """[(lines, penalty)] — every form × every breaking, deduplicated."""
    seen = {}
    for text, pen in forms(name):
        for lines, hyph in breakings(text):
            key = tuple(lines)
            p = pen + PENALTY["hyphen"] * hyph
            if key not in seen or p < seen[key]:
                seen[key] = p
    return list(seen.items())


_METRICS = {}


# --- font metrics ------------------------------------------------------------

class Metrics:
    @classmethod
    def load(cls, path):
        """Metrics for the font file at `path` (cached per path)."""
        path = str(path)
        if path not in _METRICS:
            from fontTools.pens.boundsPen import BoundsPen
            from fontTools.ttLib import TTFont

            f = TTFont(path)
            gs = f.getGlyphSet()

            def bounds(g):
                pen = BoundsPen(gs)
                gs[g].draw(pen)
                return pen.bounds

            _METRICS[path] = cls({"gs": gs, "cmap": f.getBestCmap(),
                                  "upm": f["head"].unitsPerEm, "bounds": bounds})
        return _METRICS[path]

    def __init__(self, glyphs):
        self.gs, self.cmap, self.upm = glyphs["gs"], glyphs["cmap"], glyphs["upm"]
        b = glyphs["bounds"](self.cmap[ord("H")])
        self.cap = b[3] / self.upm  # cap height, em

        self._line_polys = {}

    def line_poly(self, text: str):
        """Union of the line's glyph outlines, font units, pen at x=0."""
        if text not in self._line_polys:
            parts, x = [], 0
            for ch in text:
                g = self.cmap.get(ord(ch))
                if g is None:
                    continue
                pen = _FlatPen(self.gs)
                self.gs[g].draw(pen)
                for c in pen.contours:
                    if len(c) >= 3:
                        parts.append(affine_transform(
                            Polygon(c).buffer(0), [1, 0, 0, 1, x, 0]))
                x += self.gs[g].width
            self._line_polys[text] = unary_union(parts)
        return self._line_polys[text]

    def advance(self, text: str) -> float:
        """Advance width of `text` in em (no kerning — phase 4)."""
        return sum(self.gs[self.cmap[ord(ch)]].width
                   for ch in text if ord(ch) in self.cmap) / self.upm


def _flat_pen_class():
    from fontTools.pens.basePen import BasePen

    class FlatPen(BasePen):
        """Glyph outline → polylines (curves sampled)."""

        def __init__(self, gs):
            super().__init__(gs)
            self.contours, self.cur = [], []

        def _moveTo(self, pt):
            self.cur = [pt]

        def _lineTo(self, pt):
            self.cur.append(pt)

        def _curveToOne(self, p1, p2, p3):
            (x0, y0) = self.cur[-1]
            for i in range(1, 7):
                t = i / 6
                a, b, c, d = (1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t * t * (1 - t), t ** 3
                self.cur.append((a * x0 + b * p1[0] + c * p2[0] + d * p3[0],
                                 a * y0 + b * p1[1] + c * p2[1] + d * p3[1]))

        def _closePath(self):
            if len(self.cur) >= 3:
                self.contours.append(self.cur)
            self.cur = []

        _endPath = _closePath

    return FlatPen


def _FlatPen(gs):
    global _FLAT
    try:
        cls = _FLAT
    except NameError:
        cls = _FLAT = _flat_pen_class()
    return cls(gs)


# --- geometry ----------------------------------------------------------------

def lobe_regions(polygon, n):
    """Split a lobed polygon into n regions by erosion, or None (from the
    envelope experiment: erode until n sizable cores appear, grow each
    back, clip; the largest core claims the shared elbow first)."""
    area = polygon.area
    best = None
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
    for comp in comps:
        reg = comp.buffer(r * 1.3).intersection(polygon)
        if claimed is not None:
            reg = reg.difference(claimed)
        reg = max(_polygons(reg), key=lambda g: g.area, default=None)
        if reg is None:
            return None
        claimed = reg if claimed is None else claimed.union(reg)
        regs.append(reg)
    return regs


def axis(theta):
    """(u, p) for baseline angle theta (radians, screen coords): u reads
    left→right (bottom→top when vertical), p points screen-down."""
    ux, uy = math.cos(theta), math.sin(theta)
    if ux < -1e-9 or (abs(ux) <= 1e-9 and uy > 0):
        ux, uy = -ux, -uy
    return (ux, uy), (-uy, ux)


def angles(polygon):
    """Candidate baseline angles: min-rect long axis, the longest straight
    edges (Brickbottom's long side), horizontal, and a coarse sweep."""
    out = [0.0] + [math.radians(d) for d in range(0, 180, ANGLE_STEP)]
    mrr = list(polygon.minimum_rotated_rectangle.exterior.coords)[:4]
    e = max(zip(mrr, mrr[1:] + mrr[:1]), key=lambda e: math.dist(*e))
    out.append(math.atan2(e[1][1] - e[0][1], e[1][0] - e[0][0]))
    ring = list(polygon.simplify(4).exterior.coords)
    edges = sorted(zip(ring, ring[1:]), key=lambda e: -math.dist(*e))
    out += [math.atan2(b[1] - a[1], b[0] - a[0]) for a, b in edges[:3]]
    uniq = []
    for th in out:
        th %= math.pi
        if all(min(abs(th - q), math.pi - abs(th - q)) > math.radians(2)
               for q in uniq):
            uniq.append(th)
    return uniq


class Frame:
    """A polygon seen along one baseline angle: t along u, v along p,
    rasterized so band queries are array ops.

    free[r, j]: how many consecutive inside cells start at row r going
    down (screen-down = +v) — a band of hr rows fits at (r, j) iff
    free[r, j] >= hr. widest(hr) gives, for every start row, the widest
    run of such columns: one numpy pass per band height, cached.
    """

    def __init__(self, polygon, u, p):
        import numpy as np

        self.poly, self.u, self.p = polygon, u, p
        shapely.prepare(polygon)
        self.c = polygon.centroid
        tv = [self.tv(xy) for xy in polygon.exterior.coords]
        t0, t1 = min(t for t, _ in tv), max(t for t, _ in tv)
        v0, v1 = min(v for _, v in tv), max(v for _, v in tv)
        self.res = max(t1 - t0, v1 - v0) / GRID
        self.tmin, self.vmin = t0, v0
        nt = int((t1 - t0) / self.res) + 1
        nv = int((v1 - v0) / self.res) + 1
        tt = t0 + (np.arange(nt) + 0.5) * self.res
        vv = v0 + (np.arange(nv) + 0.5) * self.res
        T, V = np.meshgrid(tt, vv)
        X = self.c.x + u[0] * T + p[0] * V
        Y = self.c.y + u[1] * T + p[1] * V
        inside = shapely.contains_xy(polygon, X, Y)
        free = np.zeros(inside.shape, dtype=np.int32)
        free[-1] = inside[-1]
        for r in range(nv - 2, -1, -1):
            free[r] = (free[r + 1] + 1) * inside[r]
        self.free, self.np = free, np
        self._cache = {}

    def widest(self, hr):
        """(run_len, end_col) arrays over start rows for bands of hr rows."""
        if hr not in self._cache:
            np = self.np
            m = self.free >= hr
            c = np.cumsum(m, axis=1)
            base = np.maximum.accumulate(np.where(~m, c, 0), axis=1)
            run = c - base
            self._cache[hr] = (run.max(axis=1), run.argmax(axis=1))
        return self._cache[hr]

    def tv(self, xy):
        dx, dy = xy[0] - self.c.x, xy[1] - self.c.y
        return dx * self.u[0] + dy * self.u[1], dx * self.p[0] + dy * self.p[1]

    def xy(self, t, v):
        return (self.c.x + self.u[0] * t + self.p[0] * v,
                self.c.y + self.u[1] * t + self.p[1] * v)

    def box(self, t0, t1, v0, v1):
        return Polygon([self.xy(t0, v0), self.xy(t1, v0),
                        self.xy(t1, v1), self.xy(t0, v1)])

    def place(self, r, M):
        """[(ch, glyph, affine)] for the row's glyphs: font units → page."""
        (ux, uy), (px, py) = self.u, self.p
        k = r["size"] / M.upm
        out, pen = [], r["t0"]
        for ch in r["line"]:
            g = M.cmap.get(ord(ch))
            if g is None:
                continue
            ox, oy = self.xy(pen, r["v1"])  # baseline = bottom of cap band
            out.append((ch, g, [ux * k, -px * k, uy * k, -py * k, ox, oy]))
            pen += M.gs[g].width * k
        return out


# --- layout ------------------------------------------------------------------

def fit_lines(frame, lines, M):
    """Place `lines` top to bottom, each at its own position across the
    shape, kept together.

    1. Binary-search the largest common size s where the lines fit in
       order: each line takes the earliest row where a band of its cap
       height has a run ≥ its width, within MAX_GAP of the line above.
    2. Trade-offs: from s, or with some lines dropped to TRADE × s.
    3. Spread + grow: each line re-centers in the window its neighbors
       allow and grows (≤ MAX_RATIO × its smallest sibling) there.
    Returns a list of row-sets (one per trade-off that fits).
    """
    res = frame.res
    adv = [M.advance(ln) for ln in lines]
    nv = frame.free.shape[0]
    np = frame.np

    def need(s, a):  # (band rows, run cols) for a line of size s
        return (max(1, math.ceil(s * M.cap / res)), math.ceil(s * a / res))

    def gap(s):
        return math.ceil(LEADING * s * M.cap / res)

    def maxgap(s):
        return math.ceil(MAX_GAP * s * M.cap / res)

    def rows_ok(s, a):
        hr, wr = need(s, a)
        if hr > nv:
            return None
        run, _ = frame.widest(hr)
        return run >= wr

    def pack_sized(sizes):
        """Earliest-fit start rows, lines within MAX_GAP; or None."""
        starts, cur, prev = [], 0, None
        for s, a in zip(sizes, adv):
            ok = rows_ok(s, a)
            if ok is None:
                return None
            hi = nv if prev is None else min(nv, cur + maxgap(prev) - gap(prev) + 1)
            idx = np.flatnonzero(ok[cur:hi])
            if not len(idx):
                return None
            r = cur + int(idx[0])
            starts.append(r)
            cur, prev = r + need(s, a)[0] + gap(s), s
        return starts

    n = len(lines)
    smax = min(MAX_SIZE, getattr(frame, "max_cap", math.inf) / M.cap)
    if smax < MIN_SIZE or pack_sized([MIN_SIZE] * n) is None:
        return []
    lo, hi = MIN_SIZE, smax
    for _ in range(14):
        mid = (lo + hi) / 2
        if pack_sized([mid] * n) is not None:
            lo = mid
        else:
            hi = mid
    common = lo
    plans = [(1.0,) * n] + [tuple(TRADE if k in drop else 1.0 for k in range(n))
                            for r_ in range(1, n)
                            for drop in itertools.combinations(range(n), r_)]
    out = []
    for plan in plans:
        rows = _grow(frame, lines, adv, [common * m for m in plan], common,
                     need, gap, maxgap, rows_ok, pack_sized, M)
        if rows:
            out.append(rows)
    return out


def _grow(frame, lines, adv, sizes, common, need, gap, maxgap, rows_ok,
          pack_sized, M):
    """Spread + grow from base `sizes`, then realize boxes. Rows or None."""
    np = frame.np
    nv = frame.free.shape[0]
    starts = pack_sized(sizes)
    if starts is None:
        return None
    cap = min(MAX_SIZE, MAX_RATIO * min(sizes), MAX_RATIO * common,
              getattr(frame, "max_cap", math.inf) / M.cap)

    def latest_bound(i, s_list):
        """Last start row for line i so lines i+1.. still fit below."""
        end = nv
        for k in range(len(lines) - 1, i, -1):
            ok = rows_ok(s_list[k], adv[k])
            hr = need(s_list[k], adv[k])[0]
            idx = np.flatnonzero(ok[:max(0, end - hr + 1)])
            if not len(idx):
                return None
            end = int(idx[-1]) - gap(s_list[k])
        return end - need(s_list[i], adv[i])[0] + 1

    cur, prev = 0, None
    for i, a in enumerate(adv):
        best = None
        s = sizes[i]
        while s <= cap + 1e-9:
            trial = sizes[:i] + [s] + sizes[i + 1:]
            last = latest_bound(i, trial)
            if prev is not None and last is not None:
                last = min(last, cur + maxgap(prev) - gap(prev))
            ok = rows_ok(s, a)
            if ok is None or last is None or last < cur:
                break
            idx = np.flatnonzero(ok[cur:last + 1])
            if not len(idx):
                break
            cand = cur + idx
            mid = (cur + last) / 2
            best = (s, int(cand[np.argmin(abs(cand - mid))]))
            s *= 1.04
        if best is None:
            return None
        sizes[i], starts[i] = best
        cur, prev = starts[i] + need(sizes[i], a)[0] + gap(sizes[i]), sizes[i]

    rows, prev_mid = [], None
    for ln, s, a, r0 in zip(lines, sizes, adv, starts):
        hr, _ = need(s, a)
        run, end = frame.widest(hr)
        L, e = int(run[r0]), int(end[r0])
        c0 = frame.tmin + (e - L + 1) * frame.res
        c1 = frame.tmin + (e + 1) * frame.res
        w = s * a
        # first line centers in its run; later lines lean toward the line
        # above (one block, not scattered words)
        target = (c0 + c1) / 2 if prev_mid is None else prev_mid
        mid = min(max(target, c0 + w / 2), c1 - w / 2)
        v0 = frame.vmin + r0 * frame.res
        rows.append({"line": ln, "size": s, "t0": mid - w / 2, "t1": mid + w / 2,
                     "v0": v0, "v1": v0 + s * M.cap, "frame": frame})
        prev_mid = mid
    for ra, rb in zip(rows, rows[1:]):
        ov = min(ra["t1"], rb["t1"]) - max(ra["t0"], rb["t0"])
        if ov < OVERLAP * min(ra["t1"] - ra["t0"], rb["t1"] - rb["t0"]):
            return None
    _suffix_cap(rows)
    # exact box check (the raster is ± one cell): shrink offenders
    for _ in range(30):
        bad = [r for r in rows if not frame.box(
            r["t0"], r["t1"], r["v0"], r["v1"]).within(frame.poly)]
        if not bad:
            return rows
        for r in bad:
            _scale_row(r, 0.96)
    return None


def _suffix_cap(rows):
    """A suffix-only line (SQ) never carries more ink than the name line:
    DAVIS / giant SQ read as "SQ" (run 1), but capping SQ at the name's
    *size* left TEELE / SQ's two letters looking small (user). Ink ∝
    size × width, so SQ may be bigger than the name while it's shorter."""
    suffix = set(HERO_ABBREVIATIONS.values()) | set(HERO_ABBREVIATIONS)
    names = [r["size"] * (r["t1"] - r["t0"]) for r in rows
             if r["line"] not in suffix]
    if names:
        for r in rows:
            ink = r["size"] * (r["t1"] - r["t0"])
            if r["line"] in suffix and ink > min(names):
                _scale_row(r, math.sqrt(min(names) / ink))


def _scale_row(r, f):
    """Scale a row's size and box by `f` about the box center."""
    mid, vm = (r["t0"] + r["t1"]) / 2, (r["v0"] + r["v1"]) / 2
    hw, hh = (r["t1"] - r["t0"]) / 2 * f, (r["v1"] - r["v0"]) / 2 * f
    r["size"] *= f
    r["t0"], r["t1"], r["v0"], r["v1"] = mid - hw, mid + hw, vm - hh, vm + hh


def _shift_row(r, dt, dv):
    r["t0"] += dt
    r["t1"] += dt
    r["v0"] += dv
    r["v1"] += dv


# --- outline refinement --------------------------------------------------------

def outline(r, M):
    """The row's real glyph outlines on the page."""
    fr = r["frame"]
    if isinstance(fr, SpineFrame):
        return unary_union([affine_transform(M.line_poly(ch), m)
                            for ch, _, m in fr.place(r, M) if ch != " "])
    (ux, uy), (px, py) = fr.u, fr.p
    k = r["size"] / M.upm
    ox, oy = fr.xy(r["t0"], r["v1"])  # pen start on the baseline
    return affine_transform(M.line_poly(r["line"]),
                            [ux * k, -px * k, uy * k, -py * k, ox, oy])


def _letters_apart(r, M):
    """On a bend, neighboring letters of one word must not touch (BR in
    BRICKBOTTOM did at a tight spot of the spine)."""
    polys = [affine_transform(M.line_poly(ch), m)
             for ch, _, m in r["frame"].place(r, M) if ch != " "]
    gap = 0.02 * r["size"]
    return all(a.distance(b) >= gap for a, b in zip(polys, polys[1:]))


def refine(rows, M, ratio):
    """Fit rows to their real outlines: shrink what pokes out (Q tails),
    then grow each row — nudging it a little along and across the
    baseline — while its outline stays inside and clear of its siblings.
    Returns the refined rows or None."""
    rows = [dict(r) for r in rows]
    shapes = [outline(r, M) for r in rows]

    def clear(i, shp):
        gap = 0.5 * LEADING * M.cap * min(r["size"] for r in rows)
        return all(shp.distance(shapes[j]) >= gap
                   for j in range(len(rows)) if j != i)

    def bands_apart(i, r):
        """Stacked lines keep their cap bands apart: outlines alone let
        SQUARE's letters slot between PORTER's (interlocked, unreadable)."""
        # the packing's own leading — tighter read as interlocked
        g = LEADING * M.cap * min(x["size"] for x in rows)
        for j, o in enumerate(rows):
            if j == i or o["frame"] is not r["frame"]:
                continue
            if j < i and o["v1"] + g > r["v0"]:
                return False
            if j > i and r["v1"] + g > o["v0"]:
                return False
        return True

    def ok(i, r):
        if not bands_apart(i, r):
            return False, None
        if isinstance(r["frame"], SpineFrame) and not _letters_apart(r, M):
            return False, None
        shp = outline(r, M)
        return (shp.within(r["frame"].poly) and clear(i, shp)), shp

    def attempt(i, f):
        r0 = rows[i]
        d = 0.04 * r0["size"]
        for dt, dv in ((0, 0), (d, 0), (-d, 0), (0, d), (0, -d),
                       (2 * d, 0), (-2 * d, 0), (0, 2 * d), (0, -2 * d)):
            r = dict(r0)
            _scale_row(r, f)
            _shift_row(r, dt, dv)
            good, shp = ok(i, r)
            if good:
                rows[i], shapes[i] = r, shp
                return True
        return False

    for i in range(len(rows)):  # 1. make every row legal
        tries = 0
        while not ok(i, rows[i])[0]:
            if not attempt(i, 0.97):
                _scale_row(rows[i], 0.97)
            shapes[i] = outline(rows[i], M)
            tries += 1
            if tries > 30:
                return None
    grew = True  # 2. grow round-robin, respecting the size ratios
    for _ in range(20):
        if not grew:
            break
        grew = False
        for i in range(len(rows)):
            others = [r["size"] for j, r in enumerate(rows) if j != i]
            limit = min([MAX_SIZE, getattr(rows[i]["frame"], "max_cap", math.inf)
                         / M.cap] + [ratio * s for s in others])
            if rows[i]["size"] * 1.03 > limit:
                continue
            if attempt(i, 1.03):
                grew = True
    before = [r["size"] for r in rows]
    _suffix_cap(rows)
    if [r["size"] for r in rows] != before:
        for i, r in enumerate(rows):
            shapes[i] = outline(r, M)
    return rows


# --- curved baselines (phase 6) ------------------------------------------------

def centerline(poly, step=2.0, smooth=24.0, extend=0.3):
    """The shape's spine: the longest path through the medial axis
    (Voronoi edges of boundary samples that lie inside), smoothed with a
    ±`smooth` px moving average, extended straight past both ends by
    `extend` × its length (the raster decides what's inside), evenly
    resampled every `step` px, oriented to read left→right (bottom→top
    when vertical). Returns [(x, y)] or None."""
    import heapq

    from shapely.geometry import LineString, MultiPoint
    from shapely.ops import voronoi_diagram

    ring = poly.exterior
    n = 240
    pts = MultiPoint([ring.interpolate(i / n, normalized=True) for i in range(n)])
    vor = voronoi_diagram(pts, edges=True)  # a collection of multilines
    edges = [e for g in vor.geoms for e in getattr(g, "geoms", [g])
             if e.within(poly)]
    if not edges:
        return None
    adj = {}
    for e in edges:
        a, b = (tuple(round(c, 3) for c in e.coords[0]),
                tuple(round(c, 3) for c in e.coords[-1]))
        adj.setdefault(a, []).append((b, e.length))
        adj.setdefault(b, []).append((a, e.length))

    def far(src):
        dist, prev, pq = {src: 0.0}, {}, [(0.0, src)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist[u]:
                continue
            for v, w in adj[u]:
                if d + w < dist.get(v, math.inf):
                    dist[v], prev[v] = d + w, u
                    heapq.heappush(pq, (d + w, v))
        return max(dist, key=dist.get), prev

    a, _ = far(max(adj, key=lambda k: len(adj[k])))  # tree diameter
    b, prev = far(a)
    path = [b]
    while path[-1] in prev:
        path.append(prev[path[-1]])
    if len(path) < 3:
        return None

    def resample(cs):
        ln = LineString(cs)
        k = max(2, int(ln.length / step))
        return [ln.interpolate(i / k, normalized=True).coords[0] for i in range(k + 1)]

    pts = resample(path)
    # moving average, 3 passes, ends pinned: the medial axis wiggles with
    # every boundary notch; letters riding the wiggles pinch together
    q = max(2, int(smooth / step))
    for _ in range(3):
        pts = [pts[0]] + [
            tuple(sum(c[d] for c in pts[max(0, i - q):i + q + 1])
                  / len(pts[max(0, i - q):i + q + 1]) for d in (0, 1))
            for i in range(1, len(pts) - 1)] + [pts[-1]]
    pts = resample(pts)
    L = step * (len(pts) - 1)
    m = max(2, int(0.1 * len(pts)))  # end tangents over the last 10%
    (x0, y0), (x1, y1) = pts[0], pts[m]
    (x2, y2), (x3, y3) = pts[-1 - m], pts[-1]
    d0, d1 = math.dist(pts[0], pts[m]), math.dist(pts[-1 - m], pts[-1])
    e = extend * L
    pts = ([(x0 - (x1 - x0) / d0 * e, y0 - (y1 - y0) / d0 * e)] + pts
           + [(x3 + (x3 - x2) / d1 * e, y3 + (y3 - y2) / d1 * e)])
    pts = resample(pts)
    dx, dy = pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1]
    if dx < -1e-6 or (abs(dx) <= 1e-6 and dy > 0):
        pts = pts[::-1]
    return pts


class SpineFrame:
    """A polygon seen along a curved spine: t = distance along the spine,
    v = offset across it (screen-down side positive, like Frame.p). Same
    raster interface as Frame, so the whole straight-line search — stacked
    lines, placement, size trades, outline refinement — runs on curves.

    Offsets are kept below the spine's tightest radius (no fold-over) and
    letter cap height below RADIUS_CAPS× less than it, so letters on the
    inside of a bend don't collide."""

    # letters are spaced along their mid-height line, so on a bend of
    # radius R their tops pinch by ~(cap/2)/R: R ≥ 4 caps keeps it ≤ 12%
    # (2.5 caps with baseline spacing let BRICK's letters collide)
    RADIUS_CAPS = 4.0

    def __init__(self, polygon, spine, reverse=False):
        import numpy as np

        if reverse:
            spine = spine[::-1]

        self.poly, self.np = polygon, np
        shapely.prepare(polygon)
        P = np.asarray(spine, dtype=float)
        seg = np.hypot(*np.diff(P, axis=0).T)
        self.s = np.concatenate([[0.0], np.cumsum(seg)])
        T = np.gradient(P, self.s, axis=0)
        T /= np.hypot(T[:, 0], T[:, 1])[:, None]
        self.P, self.T = P, T
        self.N = np.stack([-T[:, 1], T[:, 0]], axis=1)  # screen-down side
        ang = np.unwrap(np.arctan2(T[:, 1], T[:, 0]))
        q = max(1, int(10 / max(seg.mean(), 1e-6)))
        kappa = np.zeros(len(P))
        kappa[q:-q] = (np.abs(ang[2 * q:] - ang[:-2 * q])
                       / (self.s[2 * q:] - self.s[:-2 * q]))
        radius = 1 / np.maximum(kappa, 1e-6)
        clear = max(polygon.exterior.distance(shapely.Point(p)) for p in spine[::5])
        # offsets stay inside the tightest bend *near the shape* (no fold)
        inside_pts = [i for i, p in enumerate(spine) if polygon.contains(shapely.Point(p))]
        rmin = radius[inside_pts].min() if inside_pts else radius.min()
        vmax = min(0.9 * rmin, 1.6 * clear)
        L = self.s[-1]
        self.res = max(L, 2 * vmax) / GRID
        self.tmin, self.vmin = 0.0, -vmax
        nt = int(L / self.res) + 1
        nv = int(2 * vmax / self.res) + 1
        tt = (np.arange(nt) + 0.5) * self.res
        vv = -vmax + (np.arange(nv) + 0.5) * self.res
        px, py = np.interp(tt, self.s, P[:, 0]), np.interp(tt, self.s, P[:, 1])
        nx, ny = np.interp(tt, self.s, self.N[:, 0]), np.interp(tt, self.s, self.N[:, 1])
        X = px[None, :] + nx[None, :] * vv[:, None]
        Y = py[None, :] + ny[None, :] * vv[:, None]
        inside = shapely.contains_xy(polygon, X, Y)
        free = np.zeros(inside.shape, dtype=np.int32)
        free[-1] = inside[-1]
        for r in range(nv - 2, -1, -1):
            free[r] = (free[r + 1] + 1) * inside[r]
        self.free = free
        self._cache = {}
        self.angle = math.atan2(P[-1, 1] - P[0, 1], P[-1, 0] - P[0, 0])
        # local bend limit per column: a band of hr rows (≈ cap height)
        # needs radius ≥ RADIUS_CAPS × its height *where it sits* (a global
        # limit pinned every label to the spine's tightest wiggle)
        self.radius_col = np.interp(tt, self.s, radius)

    def widest(self, hr):
        """Frame.widest, with columns too tightly bent for hr excluded."""
        if hr not in self._cache:
            np = self.np
            ok_col = self.radius_col >= self.RADIUS_CAPS * hr * self.res
            m = (self.free >= hr) & ok_col[None, :]
            c = np.cumsum(m, axis=1)
            base = np.maximum.accumulate(np.where(~m, c, 0), axis=1)
            run = c - base
            self._cache[hr] = (run.max(axis=1), run.argmax(axis=1))
        return self._cache[hr]

    def xy(self, t, v):
        np = self.np
        x = np.interp(t, self.s, self.P[:, 0]) + np.interp(t, self.s, self.N[:, 0]) * v
        y = np.interp(t, self.s, self.P[:, 1]) + np.interp(t, self.s, self.N[:, 1]) * v
        return float(x), float(y)

    def box(self, t0, t1, v0, v1, n=12):
        top = [self.xy(t0 + (t1 - t0) * i / n, v0) for i in range(n + 1)]
        bot = [self.xy(t1 - (t1 - t0) * i / n, v1) for i in range(n + 1)]
        return Polygon(top + bot)

    def place(self, r, M):
        """Glyphs along the band's baseline (v1), each rotated to the local
        direction across its own width; spacing is measured along the
        baseline itself, so bends neither stretch nor squash the word."""
        k = r["size"] / M.upm
        vm = (r["v0"] + r["v1"]) / 2  # letters are spaced along mid-height
        half = (r["v1"] - r["v0"]) / 2
        out, t = [], r["t0"]
        for ch in r["line"]:
            g = M.cmap.get(ord(ch))
            if g is None:
                continue
            w = M.gs[g].width * k
            a = self.xy(t, vm)
            dt = w  # advance t until the mid-line has covered w
            for _ in range(3):
                b = self.xy(t + dt, vm)
                dt *= w / max(math.dist(a, b), 1e-6)
            b = self.xy(t + dt, vm)
            d = max(math.dist(a, b), 1e-6)
            ux, uy = (b[0] - a[0]) / d, (b[1] - a[1]) / d
            px, py = -uy, ux
            # glyph origin: the mid-line point dropped half a cap to the
            # baseline, across this glyph's own direction
            ox, oy = a[0] + px * half, a[1] + py * half
            out.append((ch, g, [ux * k, -px * k, uy * k, -py * k, ox, oy]))
            t += dt
        return out

    def reads_forward(self, rows):
        """Every row reads left→right (bottom→top when vertical) *where it
        sits* — a spine's overall direction can disagree locally (Hillside
        came out upside down)."""
        for r in rows:
            vm = (r["v0"] + r["v1"]) / 2
            (x0, y0), (x1, y1) = self.xy(r["t0"], vm), self.xy(r["t1"], vm)
            dx, dy = x1 - x0, y1 - y0
            if dx < -0.15 * math.hypot(dx, dy) or (abs(dx) <= 0.15 * math.hypot(dx, dy) and dy > 0):
                return False
        return True


def spines(poly):
    """Spines at increasing smoothness: straighter spines allow bigger
    letters (the bend limit scales with cap height)."""
    out = []
    for sm in (24, 60, 120):
        sp = centerline(poly, smooth=sm)
        if sp is not None:
            out.append(sp)
    return out


def _elongation(poly):
    mrr = list(poly.minimum_rotated_rectangle.exterior.coords)[:4]
    a, b = math.dist(mrr[0], mrr[1]), math.dist(mrr[1], mrr[2])
    # long side over mean width (area / length) — slivers and bent strips
    L = max(a, b)
    return L / max(poly.area / L, 1e-6)


# --- search ----------------------------------------------------------------------

def _score(rows, pen, th, M, shape=None):
    ink = sum((r["t1"] - r["t0"]) * (r["v1"] - r["v0"]) for r in rows)
    floor = min(r["size"] for r in rows)
    sc = (math.sqrt(floor * math.sqrt(ink / M.cap)) * (1 - pen)
          * (1 - PENALTY["tilt"] * abs(math.sin(th))))
    if shape is not None:
        # presence: a label bunched into one corner of a long shape reads
        # as a footnote (user: North Point "comical"). Reward the share of
        # the shape's length the label spans, gently.
        sc *= _span(rows, shape) ** PRESENCE
    return sc


def _span(rows, shape):
    """Share of the shape's long-axis length covered by the label."""
    mrr = list(shape.minimum_rotated_rectangle.exterior.coords)[:4]
    a, b = max(zip(mrr, mrr[1:] + mrr[:1]), key=lambda e: math.dist(*e))
    L = math.dist(a, b)
    ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    ts = []
    for r in rows:
        fr = r["frame"]
        for t in (r["t0"], r["t1"]):
            for v in (r["v0"], r["v1"]):
                x, y = fr.xy(t, v)
                ts.append(x * ux + y * uy)
    return min(1.0, (max(ts) - min(ts)) / L)


def _splits(regs, cands, M):
    """One word per lobe (HILL / SIDE in Hillside's legs). Each lobe takes
    its own best angle — at a shared angle the small lobe starves (Hillside:
    33k vs 7.6k px², ~45px) — letters stay upright via axis(), and the
    first word must sit in the lobe that comes first in reading order.
    A hyphen at the split is dropped: two words, not a broken one."""
    fits = {}  # (lobe, word) -> (rows, theta) best single-line fit

    def best(k, word):
        if (k, word) not in fits:
            top = None
            for th in angles(regs[k]):
                u, p = axis(th)
                for rows in fit_lines(Frame(regs[k], u, p), [word], M):
                    if top is None or rows[0]["size"] > top[0][0]["size"]:
                        top = (rows, th)
            fits[k, word] = top
        return fits[k, word]

    out = []
    pairs = [(a, b) for a in range(len(regs)) for b in range(len(regs)) if a != b]
    for lines, pen in cands:
        if len(lines) != 2:
            continue
        hyph = lines[0].endswith("-")
        words = [lines[0].rstrip("-"), lines[1]]
        pen = pen - (PENALTY["hyphen"] if hyph else 0) + PENALTY["split"]
        for order in pairs:
            got = [best(k, w) for k, w in zip(order, words)]
            if None in got:
                continue
            (r1, th1), (r2, th2) = got
            u, p = axis(th1)
            c1, c2 = regs[order[0]].centroid, regs[order[1]].centroid
            dv = (c2.x - c1.x) * p[0] + (c2.y - c1.y) * p[1]
            dt = (c2.x - c1.x) * u[0] + (c2.y - c1.y) * u[1]
            if 2 * dv + dt <= 0:  # second word must read after the first
                continue
            parts = [dict(r1[0]), dict(r2[0])]
            lo_ = min(r["size"] for r in parts)
            for r in parts:  # one label: cap the size contrast
                if r["size"] > SPLIT_RATIO * lo_:
                    _scale_row(r, SPLIT_RATIO * lo_ / r["size"])
            _suffix_cap(parts)
            th = th1 if abs(math.sin(th1)) > abs(math.sin(th2)) else th2
            out.append((_score(parts, pen, th, M), parts, tuple(words), pen, th,
                        SPLIT_RATIO))
    return out


def search(polygon, name, M):
    """Best layout for `name` in `polygon` over candidates × angles
    (stacked, or split across lobes), refined against real outlines."""
    inner = polygon.buffer(-MARGIN)
    if inner.is_empty:
        return None
    if inner.geom_type == "MultiPolygon":
        inner = max(inner.geoms, key=lambda g: g.area)
    cands = candidates(name)
    # lobes: try 2- and 3-way decompositions (North Point: NORTH in the
    # middle lobe, POINT in the last — user)
    regs = None
    if name in HERO_SPLITS:
        regs = []
        for n_ in (2, 3):
            regs += lobe_regions(inner, n_) or []
    scored = []  # (score, rows, lines, pen, th, ratio)
    for th in angles(inner):
        u, p = axis(th)
        frame = Frame(inner, u, p)
        for lines, pen in cands:
            for rows in fit_lines(frame, lines, M):
                scored.append((_score(rows, pen, th, M, inner), rows, lines,
                               pen, th, MAX_RATIO))
    if regs:
        scored += [(_score(x[1], x[3], x[4], M, inner),) + x[1:]
                   for x in _splits(regs, cands, M)]
    forced = name in HERO_CURVES
    if forced or _elongation(inner) >= CURVE_ELONGATION:
        if forced:
            scored = []  # curves only (config HERO_CURVES)
        for sp in spines(inner):
            for rev in (False, True):  # readability is judged locally
                frame = SpineFrame(inner, sp, reverse=rev)
                for lines, pen in cands:
                    pen_c = pen + PENALTY["curve"]
                    for rows in fit_lines(frame, lines, M):
                        if frame.reads_forward(rows):
                            scored.append((_score(rows, pen_c, frame.angle, M,
                                                  inner),
                                           rows, lines, pen_c, frame.angle,
                                           MAX_RATIO))
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    best = None
    for _, rows, lines, pen, th, ratio in scored[:REFINE_TOP]:
        rows = refine(rows, M, ratio)
        if rows is None:
            continue
        sc = _score(rows, pen, th, M, inner)
        if best is None or sc > best[0]:
            best = (sc, rows, lines, pen, th)
    if best is None:
        return None
    return {"rows": best[1], "lines": best[2], "penalty": best[3],
            "angle": math.degrees(best[4])}


def render(doc, result, M, fill):
    """Emit glyph outlines, undistorted, each where its frame places it."""
    from fontTools.pens.svgPathPen import SVGPathPen

    for r in result["rows"]:
        for ch, g, m in r["frame"].place(r, M):
            if ch == " ":
                continue
            sp = SVGPathPen(M.gs, ntos=lambda v: f"{v:.1f}")
            M.gs[g].draw(sp)
            a, b, d, e, x, y = m  # shapely order → SVG matrix(a d b e x y)
            doc.raw(f'<path transform="matrix({a:.5f} {d:.5f} {b:.5f} {e:.5f} '
                    f'{x:.2f} {y:.2f})" d="{sp.getCommands()}" fill="{fill}"/>')
