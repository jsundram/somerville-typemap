"""Hero layout search — algorithm 4 in README.md.

Undistorted glyph outlines; the layout is *searched* over discrete
choices instead of bending letters:

  - text candidates: the full name + config HERO_VARIANTS, with the
    SQUARE→SQ rule (HERO_ABBREVIATIONS) applied to every form, and every
    allowed line break (spaces; "-" marks optional hyphenated breaks);
  - angle: min-rect long axis, the longest straight edges, horizontal,
    and a 15° sweep (phase 3a);
  - placement: each line at its own position across the shape (3a).
  Still to come: region splits, reading-order check (3b); curved
  baselines (phase 6).

Each candidate is sized line by line: a line sits in a band as tall as
its cap height, and gets the widest interval along the axis where the
whole band is inside the (inward-buffered) polygon. Score = inked box
legibility first — the smallest line's size × (1 − penalty) — with
total ink as a tiebreak, so shortenings and hyphen breaks must win by a
margin, and one giant short line can't buy the win (run 1 lesson).
"""

import itertools
import math
import sys
from pathlib import Path

from shapely.geometry import Polygon

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from config.words import HERO_ABBREVIATIONS, HERO_VARIANTS  # noqa: E402

# score penalties (fractions of ink): the full name should win ties
PENALTY = {"abbrev": 0.08, "hyphen": 0.12, "variant": 0.04,
           "tilt": 0.06}  # × |sin angle|: horizontal reads easiest
MAX_LINES = 3
LEADING = 0.30   # gap between stacked lines, as a fraction of cap height
MARGIN = 3.0     # px kept clear of the polygon edge
MAX_SIZE = 220   # em size cap (px)
MIN_SIZE = 6     # below this a candidate is infeasible
GRID = 160       # raster cells across the shape's longer extent
ANGLE_STEP = 15  # degrees, coarse sweep
TRADE = 0.8      # a line may give up 20% so its siblings can grow
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


# --- font metrics ------------------------------------------------------------

class Metrics:
    def __init__(self, glyphs):
        self.gs, self.cmap, self.upm = glyphs["gs"], glyphs["cmap"], glyphs["upm"]
        b = glyphs["bounds"](self.cmap[ord("H")])
        self.cap = b[3] / self.upm  # cap height, em

    def advance(self, text: str) -> float:
        """Advance width of `text` in em (no kerning — phase 4)."""
        return sum(self.gs[self.cmap[ord(ch)]].width
                   for ch in text if ord(ch) in self.cmap) / self.upm


# --- geometry ----------------------------------------------------------------

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
        import shapely

        self.poly, self.u, self.p = polygon, u, p
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
    shape (not a fixed centered stack — user notes: DUCK/VILLAGE want
    more space between them, Brickbottom wants to hug its long side).

    1. Binary-search the largest common size s where the lines fit in
       order: each line takes the earliest row where a band of its cap
       height has a run ≥ its width (earliest-fit is optimal for an
       ordered packing), then a leading gap.
    2. Trade-offs: from s, or with some lines dropped to TRADE × s.
    3. Spread + grow: each line re-centers in the window its neighbors
       allow and grows (≤ MAX_RATIO × its smallest sibling) there.
    Returns a list of row-sets (one per trade-off that fits).
    """
    res = frame.res
    adv = [M.advance(ln) for ln in lines]
    nv = frame.free.shape[0]

    def need(s, a):  # (band rows, run cols) for a line of size s
        return (max(1, math.ceil(s * M.cap / res)), math.ceil(s * a / res))

    def gap(s):
        return math.ceil(LEADING * s * M.cap / res)

    def rows_ok(s, a):
        hr, wr = need(s, a)
        if hr > nv:
            return None
        run, _ = frame.widest(hr)
        return run >= wr

    def pack(s):
        """Earliest-fit start rows at common size s, or None."""
        starts, cur = [], 0
        for a in adv:
            ok = rows_ok(s, a)
            if ok is None:
                return None
            idx = frame.np.flatnonzero(ok[cur:])
            if not len(idx):
                return None
            r = cur + int(idx[0])
            starts.append(r)
            cur = r + need(s, a)[0] + gap(s)
        return starts

    def pack_sized(sizes):
        starts, cur = [], 0
        for s, a in zip(sizes, adv):
            ok = rows_ok(s, a)
            if ok is None:
                return None
            idx = frame.np.flatnonzero(ok[cur:])
            if not len(idx):
                return None
            r = cur + int(idx[0])
            starts.append(r)
            cur = r + need(s, a)[0] + gap(s)
        return starts

    lo, hi = 0.0, MAX_SIZE
    if pack(MIN_SIZE) is None:
        return None
    lo = MIN_SIZE
    for _ in range(14):
        mid = (lo + hi) / 2
        if pack(mid) is not None:
            lo = mid
        else:
            hi = mid
    common = lo
    # size trade-offs: every line at the common size, or some lines give
    # up 20% so the others can grow (user: BALL could be much bigger if
    # SQ were smaller — pure max-min scoring kept them equal)
    n = len(lines)
    plans = [(1.0,) * n] + [tuple(TRADE if k in drop else 1.0 for k in range(n))
                            for r_ in range(1, n)
                            for drop in itertools.combinations(range(n), r_)]
    out = []
    for plan in plans:
        rows = _grow(frame, lines, adv, [common * m for m in plan], common,
                     need, gap, rows_ok, pack_sized, M)
        if rows:
            out.append(rows)
    return out


def _grow(frame, lines, adv, sizes, common, need, gap, rows_ok, pack_sized, M):
    """Spread + grow from base `sizes`, then realize boxes. Rows or None."""
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
            idx = frame.np.flatnonzero(ok[:max(0, end - hr + 1)])
            if not len(idx):
                return None
            end = int(idx[-1]) - gap(s_list[k])
        return end - need(s_list[i], adv[i])[0] + 1

    cur = 0
    for i, a in enumerate(adv):
        best = None
        s = sizes[i]
        while s <= cap + 1e-9:
            trial = sizes[:i] + [s] + sizes[i + 1:]
            last = latest_bound(i, trial)
            ok = rows_ok(s, a)
            if ok is None or last is None or last < cur:
                break
            idx = frame.np.flatnonzero(ok[cur:last + 1])
            if not len(idx):
                break
            cand = cur + idx
            # center of the feasible stretch nearest the window's middle
            mid = (cur + last) / 2
            best = (s, int(cand[frame.np.argmin(abs(cand - mid))]))
            s *= 1.04
        if best is None:
            return None
        sizes[i], starts[i] = best
        cur = starts[i] + need(sizes[i], a)[0] + gap(sizes[i])

    rows = []
    for ln, s, a, r0 in zip(lines, sizes, adv, starts):
        hr, _ = need(s, a)
        run, end = frame.widest(hr)
        L, e = int(run[r0]), int(end[r0])
        c0 = frame.tmin + (e - L + 1) * frame.res
        c1 = frame.tmin + (e + 1) * frame.res
        w = s * a
        mid = (c0 + c1) / 2
        v0 = frame.vmin + r0 * frame.res
        rows.append({"line": ln, "size": s, "t0": mid - w / 2, "t1": mid + w / 2,
                     "v0": v0, "v1": v0 + s * M.cap})
    # a suffix-only line (SQ) never outranks the name: DAVIS / giant SQ
    # read as "SQ" (run 1 lesson, back once lines could trade size)
    suffix = set(HERO_ABBREVIATIONS.values()) | set(HERO_ABBREVIATIONS)
    names = [r["size"] for r in rows if r["line"] not in suffix]
    if names:
        for r in rows:
            if r["line"] in suffix and r["size"] > min(names):
                _scale_row(r, min(names) / r["size"])
    # exact check (the raster is ± one cell): shrink offenders
    for _ in range(30):
        bad = [r for r in rows if not frame.box(
            r["t0"], r["t1"], r["v0"], r["v1"]).within(frame.poly)]
        if not bad:
            return rows
        for r in bad:
            _scale_row(r, 0.96)
    return None


def _scale_row(r, f):
    """Shrink a row's size and box by `f` about the box center."""
    mid, vm = (r["t0"] + r["t1"]) / 2, (r["v0"] + r["v1"]) / 2
    hw, hh = (r["t1"] - r["t0"]) / 2 * f, (r["v1"] - r["v0"]) / 2 * f
    r["size"] *= f
    r["t0"], r["t1"], r["v0"], r["v1"] = mid - hw, mid + hw, vm - hh, vm + hh


def search(polygon, name, M):
    """Best layout for `name` in `polygon` over candidates × angles."""
    inner = polygon.buffer(-MARGIN)
    if inner.is_empty:
        return None
    if inner.geom_type == "MultiPolygon":
        inner = max(inner.geoms, key=lambda g: g.area)
    cands = candidates(name)
    best = None
    for th in angles(inner):
        u, p = axis(th)
        frame = Frame(inner, u, p)
        tilt = PENALTY["tilt"] * abs(math.sin(th))
        for lines, pen in cands:
            for rows in fit_lines(frame, lines, M):
                # balance legibility (smallest line) and ink (√area is
                # size-like): pure max-min kept BALL no bigger than SQ
                ink = sum((r["t1"] - r["t0"]) * (r["v1"] - r["v0"])
                          for r in rows)
                floor = min(r["size"] for r in rows)
                score = (math.sqrt(floor * math.sqrt(ink / M.cap))
                         * (1 - pen) * (1 - tilt))
                if best is None or score > best[0]:
                    best = (score, rows, lines, pen, frame, th)
    if best is None:
        return None
    return {"rows": best[1], "frame": best[4], "lines": best[2],
            "penalty": best[3], "angle": math.degrees(best[5])}


def render(doc, result, M, fill):
    """Emit glyph outlines, undistorted, along each row's baseline."""
    from fontTools.pens.svgPathPen import SVGPathPen

    fr = result["frame"]
    (ux, uy), (px, py) = fr.u, fr.p
    for r in result["rows"]:
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
