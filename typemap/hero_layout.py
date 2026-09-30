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
    if pack_sized([MIN_SIZE] * n) is None:
        return []
    lo, hi = MIN_SIZE, MAX_SIZE
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
    cap = min(MAX_SIZE, MAX_RATIO * min(sizes), MAX_RATIO * common)

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
    (ux, uy), (px, py) = fr.u, fr.p
    k = r["size"] / M.upm
    ox, oy = fr.xy(r["t0"], r["v1"])  # pen start on the baseline
    return affine_transform(M.line_poly(r["line"]),
                            [ux * k, -px * k, uy * k, -py * k, ox, oy])


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
            limit = min([MAX_SIZE] + [ratio * s for s in others])
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

def centerline(poly, step=2.0):
    """The shape's spine: the longest path through the medial axis
    (Voronoi edges of boundary samples that lie inside), smoothed and
    resampled every `step` px, oriented to read left→right (bottom→top
    when vertical). Returns [(x, y)] or None."""
    import heapq

    from shapely.geometry import LineString, MultiPoint

    ring = poly.exterior
    n = 240
    pts = MultiPoint([ring.interpolate(i / n, normalized=True) for i in range(n)])
    from shapely.ops import voronoi_diagram
    vor = voronoi_diagram(pts, edges=True)  # a collection of multilines
    edges = [e for g in vor.geoms for e in getattr(g, "geoms", [g])
             if e.within(poly)]
    if not edges:
        return None
    adj = {}
    for e in edges:
        a, b = (tuple(round(c, 3) for c in e.coords[0]),
                tuple(round(c, 3) for c in e.coords[-1]))
        w = e.length
        adj.setdefault(a, []).append((b, w))
        adj.setdefault(b, []).append((a, w))

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
        end = max(dist, key=dist.get)
        return end, prev

    # tree diameter (two sweeps) on the largest component
    start = max(adj, key=lambda k: len(adj[k]))
    a, _ = far(start)
    b, prev = far(a)
    path = [b]
    while path[-1] in prev:
        path.append(prev[path[-1]])
    if len(path) < 3:
        return None
    line = LineString(path).simplify(step * 2)
    cs = list(line.coords)
    for _ in range(3):  # Chaikin smoothing, endpoints kept
        cs = ([cs[0]] + [q for p0, p1 in zip(cs, cs[1:])
                         for q in ((0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1]),
                                   (0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1]))]
              + [cs[-1]])
    line = LineString(cs)
    dx, dy = cs[-1][0] - cs[0][0], cs[-1][1] - cs[0][1]
    if dx < -1e-6 or (abs(dx) <= 1e-6 and dy > 0):
        line = LineString(cs[::-1])
    k = max(2, int(line.length / step))
    pts = [line.interpolate(i / k, normalized=True).coords[0] for i in range(k + 1)]
    # moving-average smoothing (~48 px window, 3 passes; ends pinned): the
    # medial axis wiggles with every notch in the boundary, and letters
    # riding those wiggles pinch together (run 1: HI LL, TW N)
    q = max(2, int(24 / step))
    for _ in range(3):
        pts = [pts[0]] + [
            (sum(x for x, _ in pts[max(0, i - q):i + q + 1]) / len(pts[max(0, i - q):i + q + 1]),
             sum(y for _, y in pts[max(0, i - q):i + q + 1]) / len(pts[max(0, i - q):i + q + 1]))
            for i in range(1, len(pts) - 1)] + [pts[-1]]
    # resample evenly again: callers index the spine by distance / step
    line = LineString(pts)
    k = max(2, int(line.length / step))
    return [line.interpolate(i / k, normalized=True).coords[0] for i in range(k + 1)]


def fit_curve(poly, line, M):
    """Set `line` along the shape's spine: the largest size where some
    stretch of the spine has clearance ≥ half the cap height (plus a
    little for curvature) all along the word. Returns a row or None."""
    spine = centerline(poly)
    if spine is None:
        return None
    step = math.dist(spine[0], spine[1])
    bnd = poly.exterior
    clear = [bnd.distance(shapely.Point(p)) for p in spine]
    n = len(spine)
    ang = [math.atan2(spine[min(n - 1, i + 1)][1] - spine[max(0, i - 1)][1],
                      spine[min(n - 1, i + 1)][0] - spine[max(0, i - 1)][0])
           for i in range(n)]
    # curvature: turning across ±10 px, per px
    q = max(1, int(10 / step))
    kappa = [abs(math.remainder(ang[min(n - 1, i + q)] - ang[max(0, i - q)],
                                math.tau)) / (2 * q * step) for i in range(n)]
    adv = M.advance(line)

    def window(sz):
        """Start index of the best window fitting size sz, or None."""
        nwin = max(1, int(sz * adv / step))
        half = sz * M.cap / 2
        # letters pinch on the inside of a bend by ~cap/radius: keep the
        # radius ≥ 3 cap heights under the whole word (≤ ~15% squeeze),
        # and the word's total turn modest
        kmax = 1 / (3 * sz * M.cap)
        best = None
        for i in range(0, n - nwin):
            lo = min(clear[i:i + nwin + 1])
            if lo < half * 1.08 or max(kappa[i:i + nwin + 1]) > kmax:
                continue
            if abs(math.remainder(ang[i + nwin] - ang[i], math.tau)) > math.radians(35):
                continue
            if best is None or lo > best[1]:
                best = (i, lo)
        return best[0] if best else None

    lo_s, hi_s = MIN_SIZE, MAX_SIZE
    if window(lo_s) is None:
        return None
    for _ in range(14):
        mid = (lo_s + hi_s) / 2
        if window(mid) is not None:
            lo_s = mid
        else:
            hi_s = mid
    for _ in range(20):  # exact outline check, shrinking if needed
        row = _curve_row(spine, step, ang, line, lo_s, window(lo_s), M)
        if row and row["curve"]["shape"].within(poly):
            return row
        lo_s *= 0.97
        if window(lo_s) is None:
            return None
    return None


def _curve_row(spine, step, ang, line, sz, i0, M):
    """Glyphs placed along the spine from sample i0, each rotated to the
    tangent at its center, the spine running through mid cap height."""
    if i0 is None:
        return None
    k = sz / M.upm
    half = sz * M.cap / 2
    pos = i0 * step
    glyphs, parts, corners = [], [], []
    for ch in line:
        g = M.cmap.get(ord(ch))
        if g is None:
            continue
        w = M.gs[g].width * k
        c = pos + w / 2

        def at(d):
            j = max(0, min(len(spine) - 2, int(d / step)))
            f = d / step - j
            return (spine[j][0] + (spine[j + 1][0] - spine[j][0]) * f,
                    spine[j][1] + (spine[j + 1][1] - spine[j][1]) * f)

        x, y = at(c)
        # the glyph's angle is the chord across its own width, not one
        # noisy sample's tangent
        (ax_, ay_), (bx_, by_) = at(pos), at(pos + max(w, 1e-3))
        th = math.atan2(by_ - ay_, bx_ - ax_)
        ux, uy = math.cos(th), math.sin(th)
        px, py = -uy, ux  # screen-down relative to the text
        ox, oy = x - ux * w / 2 + px * half, y - uy * w / 2 + py * half
        m = [ux * k, -px * k, uy * k, -py * k, ox, oy]
        glyphs.append((ch, g, m))
        if ch != " ":
            parts.append(affine_transform(M.line_poly(ch), m))
        for tt in (0, w):
            for vv in (-half, half):
                corners.append((x + ux * (tt - w / 2) + px * vv,
                                y + uy * (tt - w / 2) + py * vv))
        pos += w
        if pos > len(spine) * step:
            return None
    width = sz * M.advance(line)
    return {"line": line, "size": sz, "t0": 0.0, "t1": width, "v0": 0.0,
            "v1": sz * M.cap, "frame": None,
            "curve": {"glyphs": glyphs, "shape": unary_union(parts),
                      "corners": corners,
                      "angle": math.atan2(corners[-1][1] - corners[0][1],
                                          corners[-1][0] - corners[0][0])}}


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
        if "curve" in r:
            ts += [x * ux + y * uy for x, y in r["curve"]["corners"]]
            continue
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
    for lines, pen in cands:
        if len(lines) != 2:
            continue
        hyph = lines[0].endswith("-")
        words = [lines[0].rstrip("-"), lines[1]]
        pen = pen - (PENALTY["hyphen"] if hyph else 0) + PENALTY["split"]
        for order in ((0, 1), (1, 0)):
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
    regs = lobe_regions(inner, 2) if name in HERO_SPLITS else None
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
            scored = []  # curve only (config HERO_CURVES)
        for lines, pen in cands:
            if len(lines) != 1:
                continue
            row = fit_curve(inner, lines[0], M)
            if row is not None:
                pen_c = pen + PENALTY["curve"]
                th = row["curve"]["angle"]
                scored.append((_score([row], pen_c, th, M, inner), [row], lines,
                               pen_c, th, MAX_RATIO))
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    best = None
    for _, rows, lines, pen, th, ratio in scored[:REFINE_TOP]:
        if not any("curve" in r for r in rows):  # curves are exact already
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
    """Emit glyph outlines, undistorted, along each row's baseline."""
    from fontTools.pens.svgPathPen import SVGPathPen

    for r in result["rows"]:
        if "curve" in r:
            for ch, g, m in r["curve"]["glyphs"]:
                if ch == " ":
                    continue
                sp = SVGPathPen(M.gs, ntos=lambda v: f"{v:.1f}")
                M.gs[g].draw(sp)
                a, b, c, d, e, f = m[0], m[2], m[1], m[3], m[4], m[5]
                doc.raw(f'<path transform="matrix({a:.5f} {b:.5f} {c:.5f} '
                        f'{d:.5f} {e:.2f} {f:.2f})" d="{sp.getCommands()}" '
                        f'fill="{fill}"/>')
            continue
        fr = r["frame"]
        (ux, uy), (px, py) = fr.u, fr.p
        k = r["size"] / M.upm
        pen_t = r["t0"]
        for ch in r["line"]:
            g = M.cmap.get(ord(ch))
            if g is None:
                continue
            bx, by = fr.xy(pen_t, r["v1"])  # baseline = bottom of cap band
            if ch != " ":
                sp = SVGPathPen(M.gs, ntos=lambda v: f"{v:.1f}")
                M.gs[g].draw(sp)
                # font units (x right, y up) → page: x along u, y along −p
                doc.raw(f'<path transform="matrix({ux * k:.5f} {uy * k:.5f} '
                        f'{-px * k:.5f} {-py * k:.5f} {bx:.2f} {by:.2f})" '
                        f'd="{sp.getCommands()}" fill="{fill}"/>')
            pen_t += M.gs[g].width * k
